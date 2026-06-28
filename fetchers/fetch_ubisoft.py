import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from clients.hltb_client import HltbClient
from clients.ubisoft_client import UbisoftAuthError, UbisoftClient
from fetchers._authoritative import UBISOFT
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
from shared.raw_dumps import profile_raw_dump_path

GAMES_UBISOFT_JSON = Path("games_ubisoft.json")
UBISOFT_RAW_DUMP = profile_raw_dump_path("ubisoft_raw.json")
HLTB_DELAY_SEC = 1.0
_TM_CHARS = "".maketrans({"®": "", "™": "", "©": ""})


def _clean_name(raw):
    return " ".join((raw or "").translate(_TM_CHARS).split()).strip()


def _last_played_from_games_played(entry):
    lp = entry.get("lastPlayed")
    if isinstance(lp, dict):
        return lp.get("updatedAt") or lp.get("createdAt")
    if isinstance(lp, str) and lp:
        return lp
    return None


def _application_id_names(catalog):
    out = {}
    for game in catalog:
        name = _clean_name(str(game.get("displayName") or ""))
        if not name:
            continue
        for plat in game.get("platforms") or []:
            if not isinstance(plat, dict):
                continue
            aid = plat.get("applicationId")
            if isinstance(aid, str) and aid:
                out.setdefault(aid, name)
        for sibling in game.get("siblingGames") or []:
            if not isinstance(sibling, dict):
                continue
            sname = _clean_name(str(game.get("displayName") or ""))
            for plat in sibling.get("platforms") or []:
                if not isinstance(plat, dict):
                    continue
                aid = plat.get("applicationId")
                if isinstance(aid, str) and aid and sname:
                    out.setdefault(aid, sname)
    return out


def _extract_records(payload):
    if not isinstance(payload, dict) or "catalog" not in payload:
        return []
    catalog = [g for g in payload.get("catalog") or [] if isinstance(g, dict)]
    games_played = [g for g in payload.get("gamesPlayed") or [] if isinstance(g, dict)]
    applications = [a for a in payload.get("applications") or [] if isinstance(a, dict)]
    last_by_space = {}
    for gp in games_played:
        sid = gp.get("spaceId")
        if isinstance(sid, str):
            lp = _last_played_from_games_played(gp)
            if lp:
                last_by_space[sid] = lp
    app_names = _application_id_names(catalog)
    seen = {}
    for game in catalog:
        name = _clean_name(str(game.get("displayName") or ""))
        sid = game.get("spaceId")
        if not name or not sid:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = {
                "name": name,
                "spaceId": str(sid),
                "id": str(sid),
                "last_played": last_by_space.get(str(sid)),
                "displayName": name,
            }
    for app in applications:
        aid = app.get("applicationId")
        if not isinstance(aid, str):
            continue
        name = app_names.get(aid)
        if not name:
            continue
        key = name.lower()
        lp = app.get("lastDatePlayed")
        if key in seen:
            if lp and (not seen[key].get("last_played")):
                seen[key]["last_played"] = lp
            continue
        seen[key] = {"name": name, "id": aid, "applicationId": aid, "last_played": lp if isinstance(lp, str) else None}
    return list(seen.values())


def _name_of(item):
    for k in ("name", "title", "displayName", "productName", "applicationName", "spaceName"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return _clean_name(v)
        if isinstance(v, dict):
            for inner in ("en_US", "enUS", "default", "value"):
                iv = v.get(inner)
                if isinstance(iv, str) and iv.strip():
                    return _clean_name(iv)
    return ""


def _id_of(item, fallback):
    for k in ("spaceId", "applicationId", "appId", "productId", "uplayId", "id", "uuid"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return fallback or ""


def _image_of(item):
    for k in ("thumbImage", "thumbnail", "imageUrl", "image", "boxArt", "coverImage", "hero", "logo"):
        v = item.get(k)
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, dict):
            for inner in ("url", "src", "default"):
                iv = v.get(inner)
                if isinstance(iv, str) and iv.startswith("http"):
                    return iv
    return None


def _last_played_iso(item):
    v = item.get("last_played")
    if isinstance(v, str) and v:
        return v
    for k in ("lastPlayed", "lastPlayedDate", "lastDatePlayed", "lastUsedDate"):
        v = item.get(k)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            inner = v.get("updatedAt") or v.get("createdAt")
            if isinstance(inner, str) and inner:
                return inner
    return None


def _store_url(item, name):
    space_id = item.get("spaceId") or item.get("space_id")
    if isinstance(space_id, str) and space_id:
        return f"https://store.ubisoft.com/us/search?q={quote(name)}"
    return f"https://store.ubisoft.com/us/search?q={quote(name)}"


def load_existing():
    if not catalog_file(GAMES_UBISOFT_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_UBISOFT_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(item, hltb):
    name = _name_of(item) or "Unknown Ubisoft title"
    uid = _id_of(item, name)
    image = _image_of(item)
    row = {
        "store": "ubisoft",
        "id": uid,
        "ubisoft_id": uid,
        "name": name,
        "playtime_minutes": None,
        "last_played": _last_played_iso(item),
        "header_image": image,
        "library_image": image,
        "release_date": None,
        "genres": [],
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": _store_url(item, name),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
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
    parser = argparse.ArgumentParser(description="Fetch Ubisoft Connect library (unofficial)")
    parser.add_argument("--skip-hltb", action="store_true")
    add_only_new_arg(parser)
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    parser.add_argument(
        "--dump-raw", action="store_true", help=f"Also write the raw API response to {UBISOFT_RAW_DUMP} for debugging."
    )
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_ubisoft")
    stats = RunStats()
    load_dotenv()
    auth = resolve_env("UBISOFT_AUTH", provider="ubisoft")
    session_id = resolve_env("UBISOFT_SESSION_ID", provider="ubisoft")
    app_id = resolve_env("UBISOFT_APP_ID", provider="ubisoft") or None
    if not auth or not session_id:
        stats.error(
            "Set UBISOFT_AUTH and UBISOFT_SESSION_ID in .env. To get them:\n  1. Sign in at https://connect.ubisoft.com/ and open your library\n  2. DevTools → Network → click any request to public-ubiservices.ubi.com\n  3. Copy the 'Authorization' value (starts with 'Ubi_v1 t=')\n     and the 'Ubi-SessionId' value\n  4. Paste into .env as UBISOFT_AUTH and UBISOFT_SESSION_ID"
        )
        return stats.finish("fetch_ubisoft", t0, exit_code=1)
    try:
        client = UbisoftClient(auth, session_id, app_id=app_id)
        raw, endpoint = run_with_heartbeat(client.get_library, "Ubisoft library API")
    except UbisoftAuthError as e:
        mark_invalid("ubisoft", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_ubisoft", t0, exit_code=EXIT_CODE_AUTH)
    print(f"Hit Ubisoft endpoint: {endpoint}", flush=True)
    if args.dump_raw:
        UBISOFT_RAW_DUMP.parent.mkdir(parents=True, exist_ok=True)
        UBISOFT_RAW_DUMP.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote raw response to {UBISOFT_RAW_DUMP}.")
    raw_games = _extract_records(raw)
    seen = {}
    for item in raw_games:
        name = _name_of(item)
        if not name:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = item
    deduped = list(seen.values())
    print(f"Found {len(deduped)} unique Ubisoft entries (from {len(raw_games)} raw).", flush=True)
    empty_exit = refuse_empty_result(
        deduped, label="Ubisoft library", allow_empty=args.allow_empty, output_path=GAMES_UBISOFT_JSON
    )
    if empty_exit is not None:
        stats.error(
            f"No game records found in the response. Re-run with --dump-raw and inspect {UBISOFT_RAW_DUMP} to confirm the endpoint hit your library."
        )
        return stats.finish("fetch_ubisoft", t0, exit_code=empty_exit)
    hltb_client = HltbClient()
    existing = load_existing()
    games_out = []
    loop_hb = HeartbeatTimer(interval=25.0)
    for i, item in enumerate(deduped, 1):
        name = _name_of(item)
        row_id = _id_of(item, name or "")
        cached = existing.get(row_id)
        if args.only_new and cached:
            games_out.append(cached)
            loop_hb.tick_progress(i, len(deduped), "Ubisoft library", "cached")
            continue
        print(f"[{i}/{len(deduped)}] {name}", flush=True)
        loop_hb.reset()
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}", flush=True)
        games_out.append(
            merge_cached_row(_build_row(item, hltb), cached, authoritative=UBISOFT, hltb_updated=hltb_updated)
        )
        loop_hb.tick_progress(i, len(deduped), "Ubisoft library", (name or "")[:40])
    drift_exit = refuse_drift_result(
        games_out, label="Ubisoft library rows", allow_drift=args.allow_drift, output_path=GAMES_UBISOFT_JSON
    )
    if drift_exit is not None:
        return stats.finish("fetch_ubisoft", t0, exit_code=drift_exit)
    games_out = apply_carry_forward(games_out, existing, key_fn=row_key_by_id, no_carry=args.no_carry)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "ubisoft",
        "endpoint": endpoint,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_UBISOFT_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_UBISOFT_JSON}.", flush=True)
    print("Reload the dashboard to see your Ubisoft Connect library.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_ubisoft", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
