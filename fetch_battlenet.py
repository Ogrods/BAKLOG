#!/usr/bin/env python3
"""Fetch Battle.net library via the unofficial games-and-subs endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from auth import mark_connected, mark_invalid, resolve_env
from battlenet_client import BattleNetAuthError, BattleNetClient
from fetchers._authoritative import BATTLENET
from fetchers._base import (
    add_allow_empty_arg,
    catalog_file,
    merge_cached_row,
    refuse_drift_result,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient

GAMES_BATTLENET_JSON = Path("games_battlenet.json")


def raw_dump_json() -> Path:
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / "battlenet_raw.json"
HLTB_DELAY_SEC = 1.0

# Map Blizzard's franchise icon filename to the canonical game site.
FRANCHISE_STORE_URLS: dict[str, str] = {
    "world-of-warcraft.svg": "https://worldofwarcraft.blizzard.com/",
    "hearthstone.svg": "https://hearthstone.blizzard.com/",
    "overwatch-2.svg": "https://overwatch.blizzard.com/",
    "overwatch.svg": "https://overwatch.blizzard.com/",
    "diablo-ii-resurrected.svg": "https://diablo2.blizzard.com/",
    "diablo-iii.svg": "https://diablo3.blizzard.com/",
    "diablo-iv.svg": "https://diablo4.blizzard.com/",
    "starcraft-remastered.svg": "https://starcraft.blizzard.com/",
    "starcraft-ii.svg": "https://starcraft2.blizzard.com/",
    "warcraft-rumble.svg": "https://warcraftrumble.blizzard.com/",
    "heroes-of-the-storm.svg": "https://heroesofthestorm.blizzard.com/",
}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


# Strip the trademark glyphs Blizzard sprinkles into every title.
_TM_CHARS = "".maketrans({"®": "", "™": "", "©": ""})


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").translate(_TM_CHARS).split()).strip()


def _extract_records(payload: dict) -> list[dict]:
    """Pull the entries we care about from the live response shape."""
    out: list[dict] = []
    if not isinstance(payload, dict):
        return out
    for section in ("gameAccounts", "classicGames", "modernGames", "consoleGames"):
        for item in payload.get(section, []) or []:
            if isinstance(item, dict):
                item = {**item, "_source_section": section}
                out.append(item)
    return out


def _name(item: dict) -> str:
    for k in ("localizedGameName", "title", "displayName", "name"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return _clean_name(v)
    return ""


def _id(item: dict, fallback: str) -> str:
    for k in ("titleId", "productId", "id"):
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return fallback or "battlenet-unknown"


def _store_url(item: dict, name: str) -> str:
    icon = (item.get("regionalGameFranchiseIconFilename") or "").lower()
    if icon in FRANCHISE_STORE_URLS:
        return FRANCHISE_STORE_URLS[icon]
    return f"https://shop.battle.net/?search={quote(name)}"


def _last_played_iso(item: dict) -> str | None:
    ms = item.get("lastPlayedDateMillis")
    if not isinstance(ms, (int, float)) or ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_BATTLENET_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_BATTLENET_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(item: dict, hltb: dict | None) -> dict:
    name = _name(item) or "Unknown Battle.net title"
    bid = _id(item, name)
    tags: list[str] = []
    if item.get("titleHasGameTime") or item.get("titleHasSubscriptions"):
        tags.append("subscription")
    if (item.get("gameAccountStatus") or "").lower() == "good":
        tags.append("active")
    row = {
        "store": "battlenet",
        "id": bid,
        "battlenet_id": bid,
        "name": name,
        "playtime_minutes": None,
        "last_played": _last_played_iso(item),
        "header_image": None,
        "library_image": None,
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


def _build_client(browser: str, env_cookie: str) -> BattleNetClient:
    """Resolve Battle.net session: browser jar first, BATTLENET_COOKIE fallback."""
    if browser == "env":
        if not env_cookie:
            raise BattleNetAuthError(
                "--browser env was requested but BATTLENET_COOKIE is empty in .env."
            )
        return BattleNetClient(env_cookie)

    try:
        return BattleNetClient.from_browser(browser)
    except BattleNetAuthError as e:
        if env_cookie:
            print(
                f"warning: {e}\nFalling back to BATTLENET_COOKIE from .env.",
                file=sys.stderr,
            )
            return BattleNetClient(env_cookie)
        raise BattleNetAuthError(
            f"{e}\nAs a fallback, set BATTLENET_COOKIE in .env "
            "(DevTools → Network → /api/games-and-subs → Cookie header), "
            "or run with --browser env after setting it."
        ) from e


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Battle.net library (unofficial)")
    parser.add_argument("--skip-hltb", action="store_true")
    add_allow_empty_arg(parser)
    load_dotenv()
    env_cookie = resolve_env("BATTLENET_COOKIE", provider="battlenet")
    default_browser = "env" if env_cookie else os.getenv("BATTLENET_BROWSER", "edge")
    parser.add_argument(
        "--browser",
        default=default_browser,
        choices=["edge", "chrome", "brave", "firefox", "env"],
        help="Where to read session cookies from (default: edge, or BATTLENET_BROWSER env).",
    )
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=f"Also write the raw API response to {raw_dump_json()} for debugging.",
    )
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_battlenet")
    stats = RunStats()
    env_cookie = resolve_env("BATTLENET_COOKIE", provider="battlenet")

    try:
        client = _build_client(args.browser, env_cookie)
    except BattleNetAuthError as e:
        mark_invalid("battlenet", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_battlenet", t0, exit_code=EXIT_CODE_AUTH)

    raw = None
    try:
        raw = client.get_raw_account()
    except BattleNetAuthError as e:
        err = str(e)
        if (
            args.browser == "env"
            and env_cookie
            and ("401" in err or "403" in err or "rejected the session" in err.lower())
        ):
            fallback_browser = os.getenv("BATTLENET_BROWSER", "edge")
            try:
                client = BattleNetClient.from_browser(fallback_browser)
                raw = client.get_raw_account()
                print(
                    f"warning: stored BATTLENET_COOKIE was rejected; "
                    f"using {fallback_browser} browser session instead.",
                    file=sys.stderr,
                )
                cookie_header = (client.session.headers.get("Cookie") or "").strip()
                if cookie_header:
                    try:
                        mark_connected("battlenet", {"BATTLENET_COOKIE": cookie_header})
                    except Exception:  # noqa: BLE001
                        pass
            except BattleNetAuthError:
                mark_invalid("battlenet", error=err)
                stats.error(err)
                return stats.finish("fetch_battlenet", t0, exit_code=EXIT_CODE_AUTH)
        else:
            mark_invalid("battlenet", error=err)
            stats.error(err)
            return stats.finish("fetch_battlenet", t0, exit_code=EXIT_CODE_AUTH)

    if args.dump_raw:
        raw_dump_json().parent.mkdir(parents=True, exist_ok=True)
        raw_dump_json().write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote raw response to {raw_dump_json()}.")

    raw_games = _extract_records(raw)
    seen: dict[str, dict] = {}
    for item in raw_games:
        name = _name(item)
        if not name:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = item
    deduped = list(seen.values())
    print(f"Found {len(deduped)} unique Battle.net entries (from {len(raw_games)} raw).")

    if not deduped:
        stats.error(
            "No game records found in the response. Re-run with --dump-raw and inspect "
            f"{raw_dump_json()} to confirm the cookie hit the right account."
        )
        return stats.finish("fetch_battlenet", t0, exit_code=2)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []
    for i, item in enumerate(deduped, 1):
        name = _name(item)
        print(f"[{i}/{len(deduped)}] {name}")
        cached = existing.get(_id(item, name or ""))
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        row = _build_row(item, hltb)
        games_out.append(
            merge_cached_row(
                row,
                cached,
                authoritative=BATTLENET,
                hltb_updated=hltb_updated,
            )
        )

    drift_exit = refuse_drift_result(
        games_out,
        label="Battle.net library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_BATTLENET_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_battlenet", t0, exit_code=drift_exit)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "battlenet",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_BATTLENET_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_BATTLENET_JSON}.", flush=True)
    print("Reload the dashboard to see your Battle.net library.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_battlenet", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
