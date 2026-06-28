import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from clients.hltb_client import HltbClient
from clients.xbox_client import XboxAuthError, XboxClient, XboxRateLimitError
from fetchers._authoritative import XBOX
from fetchers._base import (
    add_allow_empty_arg,
    add_no_carry_arg,
    add_only_new_arg,
    apply_carry_forward,
    catalog_file,
    configure_stdout,
    merge_cached_row,
    refuse_drift_result,
    refuse_empty_result,
    row_key_by_id,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, HeartbeatTimer, RunStats, run_with_heartbeat, started

GAMES_XBOX_JSON = Path("games_xbox.json")
HLTB_DELAY_SEC = 1.0


def _https(url):
    if not url:
        return None
    u = str(url).strip()
    if u.startswith("http://"):
        u = "https://" + u[7:]
    u = u.replace("://images-eds.xboxlive.com/", "://images-eds-ssl.xboxlive.com/")
    return u if u.startswith("https://") else u


def _store_url(title):
    name = title.get("name") or ""
    tid = title.get("modernTitleId") or title.get("titleId")
    if tid:
        return f"https://www.xbox.com/en-us/games/store/_/{tid}"
    return f"https://www.xbox.com/en-us/search/results?q={quote(name)}"


def load_existing():
    if not catalog_file(GAMES_XBOX_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_XBOX_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(title, hltb):
    tid = str(title.get("titleId") or title.get("modernTitleId") or "")
    ach = title.get("achievement") or {}
    hist = title.get("titleHistory") or {}
    image = _https(title.get("displayImage"))
    tags = []
    devices = title.get("devices") or []
    if devices:
        tags.extend(str(d).lower() for d in devices)
    row = {
        "store": "xbox",
        "id": tid,
        "xbox_title_id": tid,
        "name": title.get("name") or "Unknown",
        "playtime_minutes": None,
        "last_played": hist.get("lastTimePlayed"),
        "header_image": image,
        "library_image": image,
        "release_date": None,
        "genres": [],
        "tags": list(dict.fromkeys(tags)),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "trophy_progress": ach.get("progressPercentage"),
        "store_url": _store_url(title),
        "type": (title.get("type") or "game").lower(),
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "xbox_gamerscore_current": ach.get("currentGamerscore"),
        "xbox_gamerscore_total": ach.get("totalGamerscore"),
    }
    if hltb:
        row.update(
            {
                "hltb_main_hours": hltb.get("hltb_main_hours"),
                "hltb_main_extra_hours": hltb.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": hltb.get("hltb_completionist_hours"),
                "hltb_match_confidence": hltb.get("hltb_match_confidence"),
                "hltb_name": hltb.get("hltb_name"),
            }
        )
    return row


def main():
    parser = argparse.ArgumentParser(description="Fetch Xbox library via OpenXBL")
    parser.add_argument("--skip-hltb", action="store_true")
    add_only_new_arg(parser)
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_xbox")
    stats = RunStats()
    load_dotenv()
    api_key = resolve_env("XBL_API_KEY", provider="xbox")
    if not api_key:
        stats.error("Set XBL_API_KEY in .env (https://xbl.io/)")
        return stats.finish("fetch_xbox", t0, exit_code=1)
    try:
        client = XboxClient(api_key)
        gt = client.get_gamertag()
        print(f"OpenXBL account: {gt or '(unknown gamertag)'}", flush=True)
        titles = run_with_heartbeat(client.get_title_history, "Xbox title history")
    except XboxRateLimitError as e:
        stats.error(str(e))
        return stats.finish("fetch_xbox", t0, exit_code=1)
    except XboxAuthError as e:
        mark_invalid("xbox", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_xbox", t0, exit_code=EXIT_CODE_AUTH)
    games = [t for t in titles if (t.get("type") or "Game").lower() in ("game", "dlc")]
    print(f"Found {len(games)} Xbox titles in title history.", flush=True)
    empty_exit = refuse_empty_result(
        games, label="Xbox library", allow_empty=args.allow_empty, output_path=GAMES_XBOX_JSON
    )
    if empty_exit is not None:
        return stats.finish("fetch_xbox", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        games, label="Xbox library", allow_drift=args.allow_drift, output_path=GAMES_XBOX_JSON
    )
    if drift_exit is not None:
        return stats.finish("fetch_xbox", t0, exit_code=drift_exit)
    hltb_client = HltbClient()
    existing = load_existing()
    games_out = []
    loop_hb = HeartbeatTimer(interval=25.0)
    for i, title in enumerate(games, 1):
        name = title.get("name") or tid_placeholder(title)
        tid = str(title.get("titleId") or title.get("modernTitleId") or "")
        cached = existing.get(tid)
        if args.only_new and cached:
            games_out.append(cached)
            stats.ok += 1
            loop_hb.tick_progress(i, len(games), "Xbox library", "cached")
            continue
        print(f"[{i}/{len(games)}] {name}", flush=True)
        loop_hb.reset()
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                stats.warn(f"HLTB for {name!r}: {e}")
        games_out.append(
            merge_cached_row(_build_row(title, hltb), cached, authoritative=XBOX, hltb_updated=hltb_updated)
        )
        stats.ok += 1
        loop_hb.tick_progress(i, len(games), "Xbox library", name[:40])
    games_out = apply_carry_forward(games_out, existing, key_fn=row_key_by_id, no_carry=args.no_carry)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "xbox",
        "gamertag": gt,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_XBOX_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_XBOX_JSON}.", flush=True)
    print("Reload the dashboard to see your Xbox library.", flush=True)
    return stats.finish("fetch_xbox", t0, exit_code=0, extra=f"{len(games_out)} games")


def tid_placeholder(title):
    return str(title.get("titleId") or "unknown")


if __name__ == "__main__":
    raise SystemExit(main())
