"""Backfill Steam-derived co-op tags onto non-Steam library rows.

For every non-Steam library row that has a Steam appid match (built and
maintained by ``enrich_steam_reviews.py`` in ``cache/steam_review_map.json``),
this script pulls the Steam ``appdetails`` payload (using the existing
``SteamClient`` disk cache) and writes a small set of normalized fields onto
the row:

    Always written (Steam is authoritative — no fetcher produces these):
      - coop_online            bool
      - coop_local             bool

    Filled only when the row is missing them (store data wins when present):
      - genres                 list[str]
      - release_date           str

The script never calls the Steam *search* endpoint — that's
``enrich_steam_reviews.py``'s job. If a row's appid hasn't been mapped yet, we
skip it; running review enrichment first is the prerequisite.

Covered stores: gog, epic, psn, amazon, xbox, battlenet, ubisoft, nintendo,
itch (videogame classification only).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from auth import resolve_env
from clients.itch_game import itch_is_videogame as _itch_is_videogame
from clients.steam_client import SteamClient
from clients.steam_metadata import (
    ALWAYS_WRITE_FIELDS,
    FILL_IF_MISSING_FIELDS,
    apply_enrichment_to_row,
    enrichment_from_appdetails,
)
from fetchers._base import STEAM_CREDENTIALS_HINT, catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, started
from shared.profile_paths import cache_json_path

HEARTBEAT_EVERY = 25  # Steam API lookups between progress lines (avoids server stall-kill)

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

def mapping_file() -> Path:
    return cache_json_path("steam_review_map.json")


def meta_file() -> Path:
    return cache_json_path("steam_tags_meta.json")


STORE_FILES: list[tuple[str, str, Callable[[dict], bool] | None]] = [
    ("games_gog.json", "gog", None),
    ("games_epic.json", "epic", None),
    ("games_psn.json", "psn", None),
    ("games_amazon.json", "amazon", None),
    ("games_xbox.json", "xbox", None),
    ("games_battlenet.json", "battlenet", None),
    ("games_ubisoft.json", "ubisoft", None),
    ("games_ea.json", "ea", None),
    ("games_nintendo.json", "nintendo", None),
    ("games_itch.json", "itch", _itch_is_videogame),
]


def load_mapping() -> dict:
    path = mapping_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _row_changed(before: dict, after: dict) -> bool:
    """True if any of the fields this script manages differs between dicts."""
    fields = ALWAYS_WRITE_FIELDS | FILL_IF_MISSING_FIELDS
    return any(before.get(k) != after.get(k) for k in fields)


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(
        description=(
            "Backfill coop tags + missing genres/release_date on non-Steam "
            "library rows from Steam appdetails."
        )
    )
    parser.add_argument(
        "--stores",
        nargs="+",
        choices=[s[1] for s in STORE_FILES],
        metavar="STORE",
        help="Only process these stores (default: all).",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-fetch Steam appdetails even when cached locally.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show counts without writing JSON back to disk.",
    )
    args = parser.parse_args(argv)
    t0 = started("enrich_steam_tags")
    stats = RunStats()

    store_files = STORE_FILES
    if args.stores:
        wanted = set(args.stores)
        store_files = [row for row in STORE_FILES if row[1] in wanted]

    load_dotenv()
    api_key = resolve_env("STEAM_API_KEY", provider="steam")
    steam_id = resolve_env("STEAM_ID", provider="steam")
    if not api_key or not steam_id:
        stats.error(STEAM_CREDENTIALS_HINT)
        return stats.finish("enrich_steam_tags", t0, exit_code=1)

    mapping = load_mapping()
    if not mapping:
        stats.error(
            "cache/steam_review_map.json is missing or empty. "
            "Run enrich_steam_reviews.py first to build the appid map."
        )
        return stats.finish("enrich_steam_tags", t0, exit_code=1)

    steam = SteamClient(api_key=api_key, steam_id=steam_id)
    hb = HeartbeatTimer(45.0)
    total_updated = 0
    total_appid_mapped = 0
    total_coop = 0

    for filename, store, row_filter in store_files:
        rel = Path(filename)
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        eligible = [g for g in games if row_filter is None or row_filter(g)]
        print(
            f"\n=== {filename} ({len(eligible)} eligible / {len(games)} rows) ===",
            flush=True,
        )

        rows_updated = 0
        rows_with_appid = 0
        coop_set = 0
        genres_filled = 0
        release_filled = 0

        for i, g in enumerate(games, 1):
            hb.tick_progress(i, len(games), f"tags {filename}", f"{rows_updated} updated")
            if row_filter is not None and not row_filter(g):
                continue
            key = f"{store}:{g.get('id')}"
            appid = mapping.get(key)
            if not appid:  # None or 0 → no Steam match recorded
                continue
            rows_with_appid += 1

            try:
                result = steam.get_app_details(int(appid), refresh=args.refresh)
            except Exception as e:  # noqa: BLE001 - log + continue
                stats.warn(f"appdetails error for {g.get('name')} ({appid}): {e}")
                continue
            if not result or not result.get("success"):
                continue

            enrichment = enrichment_from_appdetails(result.get("data"))
            before = {k: g.get(k) for k in ALWAYS_WRITE_FIELDS | FILL_IF_MISSING_FIELDS}
            apply_enrichment_to_row(g, enrichment)
            if _row_changed(before, g):
                rows_updated += 1
                stats.ok += 1
            # Per-field tallies for the run summary
            if g.get("coop_online") or g.get("coop_local"):
                coop_set += 1
            if not before.get("genres") and g.get("genres"):
                genres_filled += 1
            if not before.get("release_date") and g.get("release_date"):
                release_filled += 1

            if rows_updated and rows_updated % 50 == 0:
                print(
                    f"  [{i}/{len(games)}] {rows_updated} rows updated so far "
                    f"(last: {g.get('name')})",
                    flush=True,
                )

        if not args.dry_run and rows_updated:
            data["game_count"] = len(games)
            write_catalog_text(rel, json.dumps(data, indent=2, ensure_ascii=False))
        print(
            f"  appid-mapped: {rows_with_appid}  "
            f"updated: {rows_updated}  "
            f"coop_true: {coop_set}  "
            f"genres_filled: {genres_filled}  "
            f"release_filled: {release_filled}"
            + ("  [dry run, not written]" if args.dry_run else ""),
            flush=True,
        )
        total_updated += rows_updated
        total_appid_mapped += rows_with_appid
        total_coop += coop_set

    if not args.dry_run:
        meta = meta_file()
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps(
                {
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "rows_updated": total_updated,
                    "rows_with_appid": total_appid_mapped,
                    "rows_coop": total_coop,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    return stats.finish(
        "enrich_steam_tags", t0, exit_code=0, extra=f"{stats.ok} rows updated"
    )


if __name__ == "__main__":
    raise SystemExit(main())
