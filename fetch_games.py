#!/usr/bin/env python3
"""Fetch Steam library data and write games_steam.json for the dashboard."""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import os

from hltb_client import HltbClient
from fetchers._base import add_allow_empty_arg, refuse_empty_result
from fetchers._progress import RunStats, started
from steam_client import SteamClient

GAMES_STEAM_JSON = Path("games_steam.json")
HLTB_DELAY_SEC = 1.0


def _configure_stdout() -> None:
    """Avoid UnicodeEncodeError on Windows consoles (cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _finalize_steam_row(row: dict) -> dict:
    appid = row["appid"]
    row["store"] = "steam"
    row["id"] = appid
    return row


def _parse_release_date(data: dict) -> str | None:
    rd = data.get("release_date", {})
    if rd.get("coming_soon"):
        return None
    return rd.get("date") or None


def _coop_flags_from_categories(categories: list[dict] | None) -> tuple[bool, bool]:
    """Return (coop_online, coop_local) by scanning Steam category descriptions.

    Steam categories include "Co-op", "Online Co-op", "Shared/Split Screen Co-op",
    and "LAN Co-op". We treat LAN Co-op as online. A bare "Co-op" with no flavor
    sets both flags to False (unknown flavor) so the UI doesn't mislabel it.
    """
    if not categories:
        return (False, False)
    names = {str(c.get("description") or "").strip().lower() for c in categories}
    online = "online co-op" in names or "lan co-op" in names
    local = "shared/split screen co-op" in names
    return (online, local)


def _build_game_row(
    owned: dict,
    details: dict | None,
    reviews: dict | None,
    hltb: dict | None,
) -> dict | None:
    appid = owned["appid"]
    name = owned.get("name") or (details or {}).get("name", f"App {appid}")

    if details is None:
        return _finalize_steam_row(
            {
                "appid": appid,
                "name": name,
                "playtime_minutes": owned.get("playtime_forever", 0),
                "last_played": owned.get("rtime_last_played", 0) or None,
                "header_image": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
                "library_image": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
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
                "store_url": f"https://store.steampowered.com/app/{appid}",
                "type": "unknown",
                "price": None,
                "price_initial": None,
                "discount_percent": None,
                "currency": None,
            }
        )

    if details.get("type") != "game":
        return None

    genres = [g["description"] for g in details.get("genres", [])]
    categories = details.get("categories") or []
    tags = [c["description"] for c in categories[:16]]
    coop_online, coop_local = _coop_flags_from_categories(categories)

    price = details.get("price_overview") or {}

    row = {
        "appid": appid,
        "name": details.get("name", name),
        "playtime_minutes": owned.get("playtime_forever", 0),
        "last_played": owned.get("rtime_last_played", 0) or None,
        "header_image": details.get("header_image")
        or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
        "library_image": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
        "release_date": _parse_release_date(details),
        "genres": genres,
        "tags": tags,
        "coop_online": coop_online,
        "coop_local": coop_local,
        "steam_review_percent": (reviews or {}).get("percent_positive"),
        "steam_review_count": (reviews or {}).get("total_reviews"),
        "steam_review_desc": (reviews or {}).get("review_score_desc"),
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": f"https://store.steampowered.com/app/{appid}",
        "type": details.get("type", "game"),
        "price": price.get("final_formatted"),
        "price_initial": price.get("initial_formatted"),
        "discount_percent": price.get("discount_percent"),
        "currency": price.get("currency"),
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

    return _finalize_steam_row(row)


def load_existing() -> dict[int, dict]:
    if not GAMES_STEAM_JSON.exists():
        return {}
    data = json.loads(GAMES_STEAM_JSON.read_text(encoding="utf-8"))
    return {g["appid"]: g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Steam library into games_steam.json")
    parser.add_argument("--refresh", action="store_true", help="Ignore API cache")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_steam.json")
    parser.add_argument("--appid", type=int, help="Fetch a single app by ID")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_games")
    stats = RunStats()

    load_dotenv()
    api_key = os.getenv("STEAM_API_KEY", "").strip()
    steam_id = os.getenv("STEAM_ID", "").strip()
    if not api_key or not steam_id:
        stats.error("Set STEAM_API_KEY and STEAM_ID in .env (see .env.example)")
        return stats.finish("fetch_games", t0, exit_code=1)

    steam = SteamClient(api_key, steam_id)
    hltb_client = HltbClient()
    existing = load_existing()

    print("Fetching owned games from Steam...")
    owned_games = steam.get_owned_games()
    print(f"Found {len(owned_games)} entries in library.")

    if not args.appid:
        empty_exit = refuse_empty_result(
            owned_games,
            label="Steam owned-games API",
            allow_empty=args.allow_empty,
            output_path=GAMES_STEAM_JSON,
        )
        if empty_exit is not None:
            return stats.finish("fetch_games", t0, exit_code=empty_exit)

    if args.appid:
        owned_games = [g for g in owned_games if g["appid"] == args.appid]
        if not owned_games:
            stats.error(f"App ID {args.appid} not in your library.")
            return stats.finish("fetch_games", t0, exit_code=1)

    games_out: list[dict] = []
    skipped = 0

    for i, owned in enumerate(owned_games, 1):
        appid = owned["appid"]
        name = owned.get("name", str(appid))

        if args.only_new and appid in existing and not args.refresh and not args.appid:
            games_out.append(_finalize_steam_row(dict(existing[appid])))
            continue

        print(f"[{i}/{len(owned_games)}] {name} ({appid})")

        cached_row = existing.get(appid)
        need_store = args.refresh or cached_row is None or args.appid

        details_data = None
        if need_store:
            app_result = steam.get_app_details(appid, refresh=args.refresh)
            if app_result and app_result.get("success"):
                details_data = app_result["data"]
            reviews = steam.get_review_summary(appid, refresh=args.refresh)
        else:
            reviews = {
                "percent_positive": cached_row.get("steam_review_percent"),
                "total_reviews": cached_row.get("steam_review_count"),
                "review_score_desc": cached_row.get("steam_review_desc"),
            }
            app_result = steam.get_app_details(appid, refresh=False)
            details_data = app_result["data"] if app_result and app_result.get("success") else None

        hltb = None
        if not args.skip_hltb and (args.refresh or cached_row is None or cached_row.get("hltb_main_hours") is None):
            try:
                import time

                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        elif cached_row:
            hltb = {
                "hltb_main_hours": cached_row.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached_row.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached_row.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached_row.get("hltb_match_confidence"),
                "hltb_name": cached_row.get("hltb_name"),
            }

        row = _build_game_row(owned, details_data, reviews, hltb)
        if row is None:
            skipped += 1
            continue
        games_out.append(row)

    empty_exit = refuse_empty_result(
        games_out,
        label="Steam library rows",
        allow_empty=args.allow_empty,
        output_path=GAMES_STEAM_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_games", t0, exit_code=empty_exit)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "steam_id": steam_id,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    GAMES_STEAM_JSON.write_text(text, encoding="utf-8")
    print(f"\nWrote {len(games_out)} games to {GAMES_STEAM_JSON} (skipped {skipped} non-game items).", flush=True)
    print("Open index.html in your browser to view the dashboard.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_games", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
