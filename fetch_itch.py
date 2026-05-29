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
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from hltb_client import HltbClient
from itch_client import ItchApiError, ItchAuthError, ItchClient

GAMES_ITCH_JSON = Path("games_itch.json")
HLTB_DELAY_SEC = 1.0
SKIP_CLASSIFICATIONS = {"tool", "assets", "comic", "book", "soundtrack", "physical_game", "other"}


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _release_date(game: dict) -> str | None:
    for key in ("published_at", "created_at"):
        raw = game.get(key)
        if isinstance(raw, str) and raw:
            return raw[:10]
    return None


def _genres(game: dict) -> list[str]:
    genres: list[str] = []
    classification = game.get("classification")
    if classification and classification != "game":
        genres.append(classification)
    for key in ("genre", "type"):
        val = game.get(key)
        if isinstance(val, str) and val:
            genres.append(val)
    return list(dict.fromkeys(genres))


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
        "metacritic_score": None,
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


def load_existing() -> dict[str, dict]:
    if not GAMES_ITCH_JSON.exists():
        return {}
    data = json.loads(GAMES_ITCH_JSON.read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch itch.io library into games_itch.json")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups (recommended for itch)")
    parser.add_argument(
        "--only-new",
        action="store_true",
        help="Only HLTB-lookup games not already in games_itch.json",
    )
    parser.add_argument(
        "--include-tools",
        action="store_true",
        help="Include non-game classifications (tools, assets, comics, books, soundtracks)",
    )
    parser.add_argument(
        "--min-price",
        type=int,
        default=None,
        help="Skip games whose listed min_price is below this (in cents). Useful to drop free jam games.",
    )
    args = parser.parse_args()
    _configure_stdout()
    load_dotenv()

    api_key = os.getenv("ITCH_API_KEY", "").strip()
    if not api_key:
        print(
            "Set ITCH_API_KEY in .env (https://itch.io/user/settings/api-keys)",
            file=sys.stderr,
        )
        return 1

    try:
        client = ItchClient(api_key)
        user = client.me()
        if user.get("username"):
            print(f"Signed in to itch.io as {user['username']}")
        print("Walking owned-keys pages (this can take a minute for big libraries)...")
        keys = client.all_owned_keys()
    except ItchAuthError as e:
        print(str(e), file=sys.stderr)
        return 1
    except ItchApiError as e:
        print(f"itch.io API error: {e}", file=sys.stderr)
        return 1

    if not keys:
        print("No owned games returned from itch.io.", file=sys.stderr)
        return 2

    print(f"Found {len(keys)} owned games.")

    # Filter classifications + price
    filtered: list[dict] = []
    skipped_class = 0
    skipped_price = 0
    for entry in keys:
        game = entry.get("game") or {}
        classification = game.get("classification")
        if not args.include_tools and classification in SKIP_CLASSIFICATIONS:
            skipped_class += 1
            continue
        if args.min_price is not None and (game.get("min_price") or 0) < args.min_price:
            skipped_price += 1
            continue
        filtered.append(entry)
    if skipped_class:
        print(f"  filtered {skipped_class} non-game items (tools/comics/etc); use --include-tools to keep")
    if skipped_price:
        print(f"  filtered {skipped_price} items below --min-price")

    hltb_client = HltbClient()
    existing = load_existing()
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
        if not args.skip_hltb and not (
            args.only_new and cached and cached.get("hltb_main_hours") is not None
        ):
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(name)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        elif cached:
            hltb = {
                "hltb_main_hours": cached.get("hltb_main_hours"),
                "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                "hltb_match_confidence": cached.get("hltb_match_confidence"),
                "hltb_name": cached.get("hltb_name"),
            }

        row = _build_row(entry, hltb)
        if row:
            games_out.append(row)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "itch",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    GAMES_ITCH_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(games_out)} games to {GAMES_ITCH_JSON}.")
    print("Reload the dashboard to see your itch.io library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
