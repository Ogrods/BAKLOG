#!/usr/bin/env python3
"""Fetch Nintendo eShop purchase history into games_nintendo.json."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

from hltb_client import HltbClient
from auth import mark_invalid, resolve_env
from fetchers._authoritative import NINTENDO
from fetchers._base import add_allow_empty_arg, merge_cached_row, refuse_drift_result, catalog_file, write_catalog_text
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from nintendo_client import NintendoAuthError, NintendoClient

GAMES_NINTENDO_JSON = Path("games_nintendo.json")
RAW_DUMP_JSON = Path("cache/nintendo_raw.json")
HLTB_DELAY_SEC = 1.0

# Skip non-game purchases (funds, subscriptions, vouchers).
SKIP_CONTENT_TYPES = frozenset(
    {
        "funds",
        "subscription",
        "subscription_pass",
        "voucher",
        "gift_card",
        "balance",
    }
)
SKIP_TITLE_PATTERNS = re.compile(
    r"\b(nintendo switch online|expansion pack|membership|e?shop\s+card|"
    r"add-on content bundle|funds)\b",
    re.I,
)


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _clean_name(raw: str) -> str:
    return " ".join((raw or "").replace("®", "").replace("™", "").split()).strip()


def _is_game_transaction(tx: dict) -> bool:
    ctype = (tx.get("content_type") or "").lower()
    if ctype in SKIP_CONTENT_TYPES:
        return False
    title = tx.get("title") or ""
    if SKIP_TITLE_PATTERNS.search(title):
        return False
    # Refunds are negative entries for the same title.
    if (tx.get("transaction_type") or "").lower() == "refund":
        return False
    if not title.strip():
        return False
    return True


def _merge_transactions(transactions: list[dict]) -> list[dict]:
    """One row per title; keep earliest purchase date and tag DLC."""
    by_title: dict[str, dict] = {}
    for tx in transactions:
        if not _is_game_transaction(tx):
            continue
        name = _clean_name(str(tx.get("title") or ""))
        if not name:
            continue
        key = name.lower()
        ctype = (tx.get("content_type") or "").lower()
        is_dlc = ctype in ("dlc", "aoc", "addon", "add_on") or "dlc" in name.lower()
        date = tx.get("date") or ""
        tid = tx.get("transaction_id") or key

        if key not in by_title:
            by_title[key] = {
                "name": name,
                "id": str(tid),
                "nintendo_id": str(tid),
                "purchase_date": date,
                "device_type": tx.get("device_type"),
                "content_type": tx.get("content_type"),
                "tags": ["dlc"] if is_dlc else [],
            }
            continue
        row = by_title[key]
        if date and (not row.get("purchase_date") or date < row["purchase_date"]):
            row["purchase_date"] = date
        if is_dlc and "dlc" not in row["tags"]:
            row["tags"].append("dlc")

    return list(by_title.values())


def load_existing() -> dict[str, dict]:
    if not catalog_file(GAMES_NINTENDO_JSON).exists():
        return {}
    data = json.loads(catalog_file(GAMES_NINTENDO_JSON).read_text(encoding="utf-8"))
    return {str(g["id"]): g for g in data.get("games", [])}


def _build_row(item: dict, hltb: dict | None) -> dict:
    name = item["name"]
    nid = item["id"]
    row = {
        "store": "nintendo",
        "id": nid,
        "nintendo_id": nid,
        "name": name,
        "playtime_minutes": None,
        "last_played": None,
        "header_image": None,
        "library_image": None,
        "release_date": item.get("purchase_date"),
        "genres": [],
        "tags": list(item.get("tags") or []),
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": f"https://www.nintendo.com/us/store/products/{quote(name)}/",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Nintendo eShop purchase history")
    parser.add_argument("--skip-hltb", action="store_true")
    add_allow_empty_arg(parser)
    parser.add_argument(
        "--dump-raw",
        action="store_true",
        help=f"Write raw transactions to {RAW_DUMP_JSON}",
    )
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_nintendo")
    stats = RunStats()
    load_dotenv()
    cookie = resolve_env("NINTENDO_COOKIE", provider="nintendo")
    if not cookie:
        stats.error(
            "Set NINTENDO_COOKIE in .env:\n"
            "  1. https://ec.nintendo.com/my/transactions/\n"
            "  2. DevTools → Network → filter transactions\n"
            "  3. Click transactions?limit=… → copy Cookie header"
        )
        return stats.finish("fetch_nintendo", t0, exit_code=1)

    try:
        client = NintendoClient(cookie)
        raw_tx = client.fetch_all_transactions()
    except NintendoAuthError as e:
        mark_invalid("nintendo", error=str(e))
        stats.error(str(e))
        return stats.finish("fetch_nintendo", t0, exit_code=EXIT_CODE_AUTH)

    print(f"Fetched {len(raw_tx)} raw transactions.")

    if args.dump_raw:
        RAW_DUMP_JSON.parent.mkdir(parents=True, exist_ok=True)
        RAW_DUMP_JSON.write_text(
            json.dumps(raw_tx, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Wrote raw dump to {RAW_DUMP_JSON}.")

    merged = _merge_transactions(raw_tx)
    print(f"Found {len(merged)} unique game/DLC titles (after filtering funds/NSO).")

    if not merged:
        stats.error(
            "No games found. Check cache/nintendo_raw.json — cookie may be valid "
            "but account has no eShop purchases in the last ~2 years."
        )
        return stats.finish("fetch_nintendo", t0, exit_code=2)

    hltb_client = HltbClient()
    existing = load_existing()
    games_out: list[dict] = []
    for i, item in enumerate(merged, 1):
        print(f"[{i}/{len(merged)}] {item['name']}")
        cached = existing.get(str(item["id"]))
        hltb = None
        hltb_updated = False
        if not args.skip_hltb:
            try:
                time.sleep(HLTB_DELAY_SEC)
                hltb = hltb_client.lookup(item["name"])
                hltb_updated = bool(hltb)
            except Exception as e:
                print(f"  HLTB warning: {e}")
        games_out.append(
            merge_cached_row(
                _build_row(item, hltb),
                cached,
                authoritative=NINTENDO,
                hltb_updated=hltb_updated,
            )
        )

    drift_exit = refuse_drift_result(
        games_out,
        label="Nintendo library rows",
        allow_drift=args.allow_drift,
        output_path=GAMES_NINTENDO_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_nintendo", t0, exit_code=drift_exit)

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "nintendo",
        "game_count": len(games_out),
        "note": "eShop digital purchases only; ~2 year history limit; no cartridge games",
        "games": sorted(games_out, key=lambda g: g["name"].lower()),
    }
    write_catalog_text(GAMES_NINTENDO_JSON, json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nWrote {len(games_out)} games to {GAMES_NINTENDO_JSON}.", flush=True)
    print("Reload the dashboard to see your Nintendo library.", flush=True)
    stats.ok = len(games_out)
    return stats.finish("fetch_nintendo", t0, exit_code=0, extra=f"{len(games_out)} games")


if __name__ == "__main__":
    raise SystemExit(main())
