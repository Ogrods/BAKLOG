#!/usr/bin/env python3
"""Fetch Steam wishlist into games_wishlist.json."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from clients.hltb_client import HltbClient
from clients.steam_client import SteamClient
from fetchers._base import (
    STEAM_CREDENTIALS_HINT,
    add_allow_empty_arg,
    add_only_new_arg,
    configure_stdout,
    load_existing_games,
    refuse_drift_result,
    refuse_empty_result,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, HeartbeatTimer, RunStats, run_with_heartbeat, started
from shared.money import format_price, normalize_currency_code

GAMES_WISHLIST_JSON = Path("games_wishlist.json")
HLTB_DELAY_SEC = 1.0


def fetch_wishlist_items(api_key: str, steam_id: str) -> list[dict]:
    url = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
    params = {"key": api_key, "steamid": steam_id}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("response", {}).get("items", [])
    if not items:
        # Some accounts return items at top level
        items = data.get("response", {}).get("wishlist", []) or []
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Steam wishlist")
    parser.add_argument("--skip-hltb", action="store_true")
    add_only_new_arg(parser)
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_wishlist")
    stats = RunStats()
    load_dotenv()
    api_key = resolve_env("STEAM_API_KEY", provider="steam")
    steam_id = resolve_env("STEAM_ID", provider="steam")
    if not api_key or not steam_id:
        stats.error(STEAM_CREDENTIALS_HINT)
        return stats.finish("fetch_wishlist", t0, exit_code=1)

    print("Fetching Steam wishlist...", flush=True)
    try:
        items = run_with_heartbeat(
            lambda: fetch_wishlist_items(api_key, steam_id),
            "Steam wishlist API",
        )
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            mark_invalid("steam", error=STEAM_CREDENTIALS_HINT)
            stats.error(STEAM_CREDENTIALS_HINT)
            return stats.finish("fetch_wishlist", t0, exit_code=EXIT_CODE_AUTH)
        stats.error(f"Wishlist API error: {e}")
        stats.error("Ensure your Steam profile and wishlist are public.")
        return stats.finish("fetch_wishlist", t0, exit_code=1)

    empty_exit = refuse_empty_result(
        items,
        label="Steam wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_wishlist", t0, exit_code=empty_exit)

    print(f"Found {len(items)} wishlist items.", flush=True)
    steam = SteamClient(api_key, steam_id)
    hltb = HltbClient()
    existing = load_existing_games(GAMES_WISHLIST_JSON)
    games_out: list[dict] = []

    loop_hb = HeartbeatTimer(interval=25.0)
    for i, item in enumerate(items, 1):
        appid = int(item.get("appid") or item.get("app_id") or 0)
        if not appid:
            loop_hb.tick_progress(i, len(items), "Steam wishlist", "skip")
            continue
        if args.only_new and str(appid) in existing:
            games_out.append(existing[str(appid)])
            loop_hb.tick_progress(i, len(items), "Steam wishlist", "cached")
            continue
        print(f"[{i}/{len(items)}] appid {appid}", flush=True)
        loop_hb.reset()

        details = None
        try:
            details = steam.get_app_details(appid)
        except Exception as e:
            print(f"  details warning: {e}", flush=True)

        data = (details or {}).get("data") if details else None
        name = (data or {}).get("name") or f"Steam {appid}"
        if data and data.get("type") != "game":
            loop_hb.tick_progress(i, len(items), "Steam wishlist", "non-game")
            continue

        reviews = None
        try:
            reviews = steam.get_review_summary(appid)
        except Exception:
            pass

        hltb_data = None
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb_data = hltb.lookup(name)
            except Exception as e:
                print(f"  HLTB warning: {e}", flush=True)

        price_block = (data or {}).get("price_overview") or {}
        categories = (data or {}).get("categories") or []
        category_names = {str(c.get("description") or "").strip().lower() for c in categories}
        coop_online = "online co-op" in category_names or "lan co-op" in category_names
        coop_local = "shared/split screen co-op" in category_names
        row = {
            "store": "wishlist",
            "id": appid,
            "appid": appid,
            "name": name,
            "wishlist_priority": item.get("priority"),
            "wishlist_added": item.get("date_added"),
            "playtime_minutes": 0,
            "last_played": None,
            "header_image": (data or {}).get("header_image")
            or f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg",
            "library_image": f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900_2x.jpg",
            "release_date": ((data or {}).get("release_date") or {}).get("date") or None,
            "release_coming_soon": bool(((data or {}).get("release_date") or {}).get("coming_soon")),
            "genres": [g["description"] for g in (data or {}).get("genres", [])],
            "tags": [c["description"] for c in categories[:16]],
            "coop_online": coop_online,
            "coop_local": coop_local,
            "steam_review_percent": reviews.get("percent_positive") if reviews else None,
            "steam_review_count": reviews.get("total_reviews") if reviews else None,
            "steam_review_desc": reviews.get("review_score_desc") if reviews else None,
            "hltb_main_hours": hltb_data.get("hltb_main_hours") if hltb_data else None,
            "hltb_main_extra_hours": hltb_data.get("hltb_main_extra_hours") if hltb_data else None,
            "hltb_completionist_hours": hltb_data.get("hltb_completionist_hours") if hltb_data else None,
            "hltb_match_confidence": hltb_data.get("hltb_match_confidence") if hltb_data else None,
            "hltb_name": hltb_data.get("hltb_name") if hltb_data else None,
            "store_url": f"https://store.steampowered.com/app/{appid}/",
            "type": "game",
            "price": format_price(
                price_block.get("final", 0) / 100 if price_block.get("final") else None,
                normalize_currency_code(price_block.get("currency")),
            ),
            "price_initial": format_price(
                price_block.get("initial", 0) / 100 if price_block.get("initial") else None,
                normalize_currency_code(price_block.get("currency")),
            ),
            "discount_percent": price_block.get("discount_percent"),
            "currency": normalize_currency_code(price_block.get("currency")),
        }
        games_out.append(row)
        loop_hb.tick_progress(i, len(items), "Steam wishlist", name[:40])

    empty_exit = refuse_empty_result(
        games_out,
        label="Steam wishlist rows",
        allow_empty=args.allow_empty,
        output_path=GAMES_WISHLIST_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        games_out,
        label="Steam wishlist rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_WISHLIST_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_wishlist", t0, exit_code=drift_exit)

    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "store": "wishlist",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_WISHLIST_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_WISHLIST_JSON}.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_wishlist", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
