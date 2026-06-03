#!/usr/bin/env python3
"""Fetch PlayStation Store wishlist into games_wishlist_psn.json.

Uses the same NPSSO token as fetch_psn.py via psnawp — no browser cookie or
DevTools scraping required. The store exposes ``metGetStoreWishlist`` on
``m.np.playstation.com`` GraphQL; prices come back when the request includes
Apollo CSRF headers.

Output rows match the shared dashboard wishlist schema (``store: "wishlist"``,
``wishlist_store: "psn"``) so the merged Wishlist tab + ITAD deal radar pick
them up alongside Steam, GOG, and Epic entries.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from auth import mark_invalid, resolve_env
from fetchers._base import add_allow_empty_arg, refuse_drift_result, refuse_empty_result
from fetchers._progress import EXIT_CODE_AUTH, RunStats, started
from hltb_client import HltbClient
from psn_client import PsnAuthError, PsnClient, PsnWishlistEntry

GAMES_WISHLIST_PSN_JSON = Path("games_wishlist_psn.json")
HLTB_DELAY_SEC = 1.0

# Skip obvious non-game SKUs the user probably didn't mean to track as deals.
_SKIP_CLASSIFICATIONS = frozenset(
    {
        "THEME",
        "AVATAR",
        "CONSUMABLE",
        "VIRTUAL_CURRENCY",
    }
)


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


def _build_row(entry: PsnWishlistEntry, hltb: dict | None) -> dict:
    tags: list[str] = []
    if entry.localized_classification:
        tags.append(entry.localized_classification)
    if entry.platforms:
        tags.append(", ".join(entry.platforms))

    return {
        "store": "wishlist",
        "wishlist_store": "psn",
        "id": f"psn-{entry.id}",
        "psn_product_id": entry.id,
        "name": entry.name,
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": entry.image_url,
        "library_image": entry.image_url,
        "release_date": None,
        "genres": [],
        "tags": tags,
        "psn_platforms": list(entry.platforms or []),
        "psn_wishlist_kind": entry.kind,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": (hltb or {}).get("hltb_main_hours"),
        "hltb_main_extra_hours": (hltb or {}).get("hltb_main_extra_hours"),
        "hltb_completionist_hours": (hltb or {}).get("hltb_completionist_hours"),
        "hltb_match_confidence": (hltb or {}).get("hltb_match_confidence"),
        "hltb_name": (hltb or {}).get("hltb_name"),
        "store_url": entry.store_url or "https://store.playstation.com/en-us/",
        "type": "game",
        "price": entry.price,
        "price_initial": entry.price_initial,
        "discount_percent": entry.discount_percent,
        "currency": "USD" if entry.price else None,
    }


def _load_existing() -> dict[str, dict]:
    if not GAMES_WISHLIST_PSN_JSON.exists():
        return {}
    try:
        data = json.loads(GAMES_WISHLIST_PSN_JSON.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return {g["id"]: g for g in data.get("games", []) if isinstance(g, dict) and g.get("id")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch PSN wishlist into games_wishlist_psn.json")
    parser.add_argument("--hltb", action="store_true", help="Look up HowLongToBeat hours (slow)")
    add_allow_empty_arg(parser)
    args = parser.parse_args()
    _configure_stdout()
    t0 = started("fetch_psn_wishlist")
    stats = RunStats()

    load_dotenv()
    npsso = resolve_env("PSN_NPSSO", provider="psn")
    if not npsso:
        stats.error("Set PSN_NPSSO in .env (see Connections page or README).")
        return stats.finish("fetch_psn_wishlist", t0, exit_code=1)

    try:
        psn = PsnClient(npsso)
        online_id = psn.validate_session()
    except PsnAuthError as exc:
        mark_invalid("psn", error=str(exc))
        stats.error(str(exc))
        return stats.finish("fetch_psn_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    print(f"Fetching PSN wishlist for {online_id}...", flush=True)
    try:
        items = psn.collect_wishlist()
    except PsnAuthError as exc:
        mark_invalid("psn", error=str(exc))
        stats.error(str(exc))
        return stats.finish("fetch_psn_wishlist", t0, exit_code=EXIT_CODE_AUTH)

    skipped = [
        e for e in items if (e.store_classification or "").upper() in _SKIP_CLASSIFICATIONS
    ]
    items = [e for e in items if (e.store_classification or "").upper() not in _SKIP_CLASSIFICATIONS]
    if skipped:
        print(f"  skipped {len(skipped)} non-game SKUs ({', '.join(sorted({s.store_classification for s in skipped if s.store_classification}))})")

    empty_exit = refuse_empty_result(
        items,
        label="PSN wishlist",
        allow_empty=args.allow_empty,
        output_path=GAMES_WISHLIST_PSN_JSON,
    )
    if empty_exit is not None:
        return stats.finish("fetch_psn_wishlist", t0, exit_code=empty_exit)
    drift_exit = refuse_drift_result(
        items,
        label="PSN wishlist",
        allow_drift=args.allow_drift,
        output_path=GAMES_WISHLIST_PSN_JSON,
    )
    if drift_exit is not None:
        return stats.finish("fetch_psn_wishlist", t0, exit_code=drift_exit)

    print(f"  {len(items)} wishlist items", flush=True)

    hltb_client = HltbClient() if args.hltb else None
    existing = _load_existing()
    rows: list[dict] = []

    for i, entry in enumerate(items, 1):
        row_id = f"psn-{entry.id}"
        print(f"[{i}/{len(items)}] {entry.name}")
        hltb = None
        cached = existing.get(row_id)
        if hltb_client:
            if cached and cached.get("hltb_main_hours") is not None:
                hltb = {
                    "hltb_main_hours": cached.get("hltb_main_hours"),
                    "hltb_main_extra_hours": cached.get("hltb_main_extra_hours"),
                    "hltb_completionist_hours": cached.get("hltb_completionist_hours"),
                    "hltb_match_confidence": cached.get("hltb_match_confidence"),
                    "hltb_name": cached.get("hltb_name"),
                }
            else:
                try:
                    time.sleep(HLTB_DELAY_SEC)
                    hltb = hltb_client.lookup(entry.name)
                except Exception as exc:
                    print(f"  HLTB warning: {exc}")
        rows.append(_build_row(entry, hltb))

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "store": "wishlist_psn",
        "online_id": online_id,
        "game_count": len(rows),
        "games": sorted(rows, key=lambda g: (g.get("name") or "").lower()),
    }
    GAMES_WISHLIST_PSN_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote {len(rows)} games to {GAMES_WISHLIST_PSN_JSON}.", flush=True)
    print("Reload the dashboard to see PSN items in the Wishlist tab.", flush=True)
    stats.ok = len(rows)
    return stats.finish("fetch_psn_wishlist", t0, exit_code=0, extra=f"{len(rows)} games")


if __name__ == "__main__":
    raise SystemExit(main())
