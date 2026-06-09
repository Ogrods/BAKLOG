#!/usr/bin/env python3
"""Fetch Steam library data and write games_steam.json for the dashboard."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from fetchers._base import (
    STEAM_CREDENTIALS_HINT,
    STEAM_PRIVATE_PROFILE_HINT,
    add_allow_empty_arg,
    add_no_carry_arg,
    apply_carry_forward,
    catalog_file,
    configure_stdout,
    refuse_drift_result,
    refuse_empty_result,
    row_key_by_appid,
    write_catalog_text,
)
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from steam_client import SteamClient
from steam_metadata import coop_flags_from_categories, enrichment_from_appdetails

GAMES_STEAM_JSON = Path("games_steam.json")
HLTB_DELAY_SEC = 1.0


def _finalize_steam_row(row: dict) -> dict:
    appid = row["appid"]
    row["store"] = "steam"
    row["id"] = appid
    return row


def _parse_release_date(data: dict) -> str | None:
    rd = data.get("release_date", {}) or {}
    return rd.get("date") or None


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
    coop_online, coop_local = coop_flags_from_categories(categories)

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

    meta = enrichment_from_appdetails(details)
    row.update(
        {
            "metacritic_score": meta["metacritic_score"],
            "developers": meta["developers"],
            "publishers": meta["publishers"],
            "controller_support": meta["controller_support"],
            "early_access": meta["early_access"],
        }
    )

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
    if not catalog_file(GAMES_STEAM_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_STEAM_JSON).read_text(encoding="utf-8"))
    return {g["appid"]: g for g in data.get("games", [])}


def _row_from_cached_catalog(owned: dict, cached_row: dict) -> dict:
    """Reuse a prior catalog row; refresh playtime from GetOwnedGames only."""
    return _finalize_steam_row(
        {
            **cached_row,
            "playtime_minutes": owned.get("playtime_forever", cached_row.get("playtime_minutes", 0)),
            "last_played": owned.get("rtime_last_played", 0) or cached_row.get("last_played"),
        }
    )


def _fetch_store_data(
    steam: SteamClient,
    appid: int,
    *,
    refresh: bool,
    cached_row: dict | None,
) -> tuple[dict | None, dict | None]:
    """Return (details_data, reviews) from store APIs with cache fallback."""
    details_data: dict | None = None
    reviews: dict | None = None
    try:
        app_result = steam.get_app_details(appid, refresh=refresh)
        if app_result and app_result.get("success"):
            details_data = app_result["data"]
        reviews = steam.get_review_summary(appid, refresh=refresh)
    except requests.RequestException as exc:
        print(f"  Store API warning for {appid}: {exc}", flush=True)
        if cached_row:
            print(f"  Using cached catalog row for {appid}.", flush=True)
            reviews = {
                "percent_positive": cached_row.get("steam_review_percent"),
                "total_reviews": cached_row.get("steam_review_count"),
                "review_score_desc": cached_row.get("steam_review_desc"),
            }
            if cached_row.get("type") == "game" or cached_row.get("genres"):
                details_data = {
                    "type": cached_row.get("type", "game"),
                    "name": cached_row.get("name"),
                    "genres": [{"description": g} for g in cached_row.get("genres", [])],
                    "categories": [{"description": t} for t in cached_row.get("tags", [])],
                    "header_image": cached_row.get("header_image"),
                    "release_date": (
                        {"date": cached_row.get("release_date")}
                        if cached_row.get("release_date")
                        else {}
                    ),
                }
        else:
            reviews = None
    return details_data, reviews


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Steam library into games_steam.json")
    parser.add_argument("--refresh", action="store_true", help="Ignore API cache")
    parser.add_argument("--only-new", action="store_true", help="Only fetch games not in games_steam.json")
    parser.add_argument("--appid", type=int, help="Fetch a single app by ID")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    add_allow_empty_arg(parser)
    add_no_carry_arg(parser)
    args = parser.parse_args(sys.argv[1:])
    configure_stdout()
    t0 = started("fetch_games")
    stats = RunStats()

    load_dotenv()
    api_key = resolve_env("STEAM_API_KEY", provider="steam")
    steam_id = resolve_env("STEAM_ID", provider="steam")
    if not api_key or not steam_id:
        stats.error(STEAM_CREDENTIALS_HINT)
        return stats.finish("fetch_games", t0, exit_code=1)

    steam = SteamClient(api_key, steam_id)
    hltb_client = HltbClient()
    existing = load_existing()

    print("Fetching owned games from Steam...")
    try:
        owned_games = steam.get_owned_games()
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403):
            mark_invalid("steam", error=STEAM_CREDENTIALS_HINT)
            stats.error(STEAM_CREDENTIALS_HINT)
            return stats.finish("fetch_games", t0, exit_code=EXIT_CODE_AUTH)
        stats.error(f"Steam API error: {e}")
        return stats.finish("fetch_games", t0, exit_code=1)
    print(f"Found {len(owned_games)} entries in library.")

    if not args.appid:
        if not owned_games:
            stats.warn(STEAM_PRIVATE_PROFILE_HINT)
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

        use_cached_only = not need_store and cached_row is not None
        details_data: dict | None = None
        reviews: dict | None = None

        if use_cached_only:
            reviews = {
                "percent_positive": cached_row.get("steam_review_percent"),
                "total_reviews": cached_row.get("steam_review_count"),
                "review_score_desc": cached_row.get("steam_review_desc"),
            }
        else:
            details_data, reviews = _fetch_store_data(
                steam,
                appid,
                refresh=args.refresh,
                cached_row=cached_row,
            )

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

        if use_cached_only:
            row = _row_from_cached_catalog(owned, cached_row)
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
            games_out.append(row)
            continue

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
    drift_exit = refuse_drift_result(
        games_out,
        label="Steam library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_STEAM_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_games", t0, exit_code=drift_exit)

    games_out = apply_carry_forward(
        games_out,
        existing,
        key_fn=row_key_by_appid,
        no_carry=args.no_carry,
    )

    # Inline write (not write_games_json) because the payload includes steam_id at root.
    # Per-row enrichment is preserved via cached_row in the loop above.
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "steam_id": steam_id,
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }

    text = json.dumps(payload, indent=2, ensure_ascii=False)
    disk = write_catalog_text(GAMES_STEAM_JSON, text)
    print(f"\nWrote {len(games_out)} games to {disk} (skipped {skipped} non-game items).", flush=True)
    print("Open index.html in your browser to view the dashboard.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_games", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
