#!/usr/bin/env python3
"""Read Amazon Games library from the local launcher DB and write games_amazon.json."""

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

GAMES_AMAZON_JSON = Path("games_amazon.json")
HLTB_DELAY_SEC = 1.0


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _build_row(rec: dict, hltb: dict | None) -> dict:
    pid = rec["amazon_product_id"]
    row = {
        "store": "amazon",
        "id": pid,
        "amazon_id": pid,
        "amazon_entitlement_id": rec.get("amazon_entitlement_id"),
        "amazon_adg_id": rec.get("amazon_adg_id"),
        "name": rec["name"],
        "playtime_minutes": 0,
        "last_played": rec.get("last_played"),
        "header_image": rec.get("header_image"),
        "library_image": rec.get("library_image"),
        "release_date": rec.get("release_date"),
        "genres": rec.get("genres") or [],
        "tags": [],
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": rec.get("store_url"),
        "type": "game",
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
        "asin": rec.get("asin"),
        "product_line": rec.get("product_line"),
        "publisher": rec.get("publisher"),
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
    if not GAMES_AMAZON_JSON.exists():
        return {}
    data = json.loads(GAMES_AMAZON_JSON.read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import Amazon Games library from local launcher SQLite (Windows)"
    )
    parser.add_argument(
        "--sql-dir",
        type=Path,
        default=None,
        help="Override Amazon Games Sql folder (default: %%LOCALAPPDATA%%/Amazon Games/Data/Games/Sql)",
    )
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HowLongToBeat lookups")
    parser.add_argument("--only-new", action="store_true", help="Only HLTB-fetch games missing HLTB data")
    args = parser.parse_args()
    _configure_stdout()

    if sys.platform != "win32":
        print("fetch_amazon.py only runs on Windows (DPAPI).", file=sys.stderr)
        return 1

    load_dotenv()
    sql_dir = args.sql_dir
    if sql_dir is None:
        env_dir = os.getenv("AMAZON_GAMES_SQL_DIR", "").strip()
        sql_dir = Path(env_dir) if env_dir else None

    try:
        from amazon_client import AmazonGamesClient, AmazonGamesError

        client = AmazonGamesClient(sql_dir)
        print(f"Reading Amazon Games library from:\n  {client.sql_dir}")
        records = client.get_library_records()
    except ImportError as e:
        print(str(e), file=sys.stderr)
        return 1
    except AmazonGamesError as e:
        print(str(e), file=sys.stderr)
        return 1

    if not records:
        print("No games found in Amazon entitlements.", file=sys.stderr)
        return 2

    print(f"Found {len(records)} Amazon Games titles.")

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []

    for i, rec in enumerate(records, 1):
        pid = rec["amazon_product_id"]
        name = rec["name"]
        print(f"[{i}/{len(records)}] {name}")

        cached = existing.get(pid)
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

        games_out.append(_build_row(rec, hltb))

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "amazon",
        "game_count": len(games_out),
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    GAMES_AMAZON_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nWrote {len(games_out)} games to {GAMES_AMAZON_JSON}.")
    print("Reload the dashboard to see your Amazon library.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
