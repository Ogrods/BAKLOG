#!/usr/bin/env python3
"""Fetch itch.io owned games and write games_itch.json.

Requires ``ITCH_API_KEY`` in .env (https://itch.io/user/settings/api-keys).

Notes
-----
- Includes free games and claimed bundle items.
- Unclaimed bundle items (e.g. Palestine/Racial Justice bundles) won't appear
  until you claim each one on itch.io.
- itch doesn't expose playtime or aggregate ratings, so those fields stay
  empty. HLTB is best-effort (most jam games won't have entries).
- All owned keys are written to JSON (including tools, soundtracks, etc.).
  The dashboard itch.io tab hides non-games by default; use the filter toggle
  to show everything.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from fetchers._base import (
    add_allow_empty_arg,
    add_dry_run_arg,
    add_hltb_args,
    configure_stdout,
    load_existing_games,
    merge_cached_row,
    print_id_diff,
    refuse_drift_result,
    write_games_json,
)
from auth import mark_invalid, resolve_env
from fetchers._progress import RunStats, started
from hltb_client import HltbClient
from itch_client import ItchApiError, ItchAuthError, ItchClient

GAMES_ITCH_JSON = Path("games_itch.json")
HLTB_DELAY_SEC = 1.0

# Fields refreshed from itch.io on every fetch; everything else is preserved from cache.
FETCHER_AUTHORITATIVE = frozenset({
    "store", "id", "itch_id", "name", "header_image", "library_image",
    "release_date", "genres", "store_url", "type", "price", "price_initial",
    "discount_percent", "currency", "publisher", "short_text",
    "classification", "min_price", "in_press_system",
    "download_key_id", "purchase_id",
})


def _release_date(game: dict) -> str | None:
    for key in ("published_at", "created_at"):
        raw = game.get(key)
        if isinstance(raw, str) and raw:
            return raw[:10]
    return None


_ITCH_NOISE_GENRES = {
    "default", "html", "html5", "flash", "java", "unity", "godot",
    "physical_game", "physical game", "assets", "asset_pack", "asset pack",
    "tool", "book", "comic", "soundtrack", "other", "game",
}


def _genres(game: dict) -> list[str]:
    """Collect itch.io tags as genres, filtering out classification/engine noise.

    The itch.io owned-keys API does not expose real genres in the listing
    endpoint - the ``classification`` field already captures format (game vs.
    tool vs. soundtrack, etc.) and ``type`` is engine metadata (html, flash).
    Neither belongs in the genres array. Tags array (if present) holds real
    genre-ish tags such as "shooter" or "platformer".
    """

    genres: list[str] = []
    for key in ("tags", "tag_list"):
        val = game.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.strip():
                    genres.append(item.strip())
        elif isinstance(val, str) and val.strip():
            genres.append(val.strip())
    cleaned = []
    seen = set()
    for g in genres:
        norm = g.strip().lower()
        if not norm or norm in _ITCH_NOISE_GENRES:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        cleaned.append(g)
    return cleaned


def _build_row(entry: dict, hltb: dict | None) -> dict | None:
    game = entry.get("game") or {}
    gid = game.get("id")
    if gid is None:
        return None
    user = game.get("user") or {}
    cover = game.get("cover_url") or game.get("still_cover_url")
    row = {
        "store": "itch",
        "id": int(gid),
        "itch_id": int(gid),
        "name": (game.get("title") or "Untitled").strip(),
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": cover,
        "library_image": cover,
        "release_date": _release_date(game),
        "genres": _genres(game),
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": game.get("url"),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "publisher": user.get("username") or user.get("display_name"),
        "short_text": game.get("short_text"),
        "classification": game.get("classification"),
        "min_price": game.get("min_price"),
        "in_press_system": bool(game.get("in_press_system")),
        "download_key_id": entry.get("id"),
        "purchase_id": entry.get("purchase_id"),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch itch.io library into games_itch.json")
    add_hltb_args(parser)
    parser.add_argument(
        "--min-price",
        type=int,
        default=None,
        help="Skip games whose listed min_price is below this (in cents). Useful to drop free jam games.",
    )
    add_dry_run_arg(parser)
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    configure_stdout()
    t0 = started("fetch_itch")
    stats = RunStats()
    load_dotenv()

    api_key = resolve_env("ITCH_API_KEY", provider="itch")
    if not api_key:
        stats.error("Set ITCH_API_KEY in .env (https://itch.io/user/settings/api-keys)")
        return stats.finish("fetch_itch", t0, exit_code=1)

    try:
        client = ItchClient(api_key)
        user = client.me()
        if user.get("username"):
            print(f"Signed in to itch.io as {user['username']}")
        print("Walking owned-keys pages (this can take a minute for big libraries)...")
        keys = client.all_owned_keys()
    except ItchAuthError as e:
        stats.error(str(e))
        return stats.finish("fetch_itch", t0, exit_code=1)
    except ItchApiError as e:
        stats.error(f"itch.io API error: {e}")
        return stats.finish("fetch_itch", t0, exit_code=1)

    if not keys:
        stats.error("No owned games returned from itch.io.")
        return stats.finish("fetch_itch", t0, exit_code=2)

    print(f"Found {len(keys)} owned keys.")

    filtered: list[dict] = []
    skipped_price = 0
    for entry in keys:
        game = entry.get("game") or {}
        if args.min_price is not None and (game.get("min_price") or 0) < args.min_price:
            skipped_price += 1
            continue
        filtered.append(entry)
    if skipped_price:
        print(f"  filtered {skipped_price} items below --min-price")

    hltb_client = HltbClient()
    existing = load_existing_games(GAMES_ITCH_JSON)
    games_out: list[dict] = []

    for i, entry in enumerate(filtered, 1):
        game = entry.get("game") or {}
        name = (game.get("title") or "Untitled").strip()
        gid = game.get("id")
        if gid is None:
            continue
        print(f"[{i}/{len(filtered)}] {name}")

        cached = existing.get(str(gid))
        hltb = None
        hltb_updated = False
        if not args.skip_hltb and not (
            args.only_new and cached and cached.get("hltb_main_hours") is not None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        elif cached and not args.skip_hltb:
            hltb = {
                "hltb_main_hours": cached.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached.get("hltb_match_confidence"),
                "hltb_name": cached.get("hltb_name"),
            }

        row = _build_row(entry, hltb)
        if row:
            games_out.append(
                merge_cached_row(
                    row,
                    cached,
                    authoritative=FETCHER_AUTHORITATIVE,
                    hltb_updated=hltb_updated,
                )
            )

    existing_ids = set(existing.keys())
    new_ids = {str(g["id"]) for g in games_out}
    print_id_diff(existing_ids, new_ids)
    preserved_enrichment = sum(
        1 for g in games_out
        if existing.get(str(g["id"]))
        and (
            g.get("steam_review_percent") is not None
            or g.get("hltb_main_hours") is not None
        )
    )
    if preserved_enrichment:
        print(f"  {preserved_enrichment} rows kept enrichment from cache (reviews/HLTB)")

    if args.dry_run:
        print("\nDry run — not writing games_itch.json.", flush=True)
        return stats.finish("fetch_itch", t0, exit_code=0, extra="dry run")

    drift_exit = refuse_drift_result(
        games_out,
        label="itch.io library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_ITCH_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_itch", t0, exit_code=drift_exit)

    sorted_games = sorted(games_out, key=lambda g: g["name"].lower())
    write_games_json(GAMES_ITCH_JSON, store="itch", games=sorted_games)
    print(f"\nWrote {len(sorted_games)} games to {GAMES_ITCH_JSON}.", flush=True)
    print("Reload the dashboard to see your itch.io library.", flush=True)
    stats.ok = len(sorted_games)
    return stats.finish("fetch_itch", t0, exit_code=0, extra=f"{len(sorted_games)} games")


if __name__ == "__main__":
    raise SystemExit(main())
