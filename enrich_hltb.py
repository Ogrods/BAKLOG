"""Backfill HowLongToBeat hours for any games_*.json row missing hltb_main_hours.

Walks every per-store JSON in the project, finds rows where hltb_main_hours is
null, and looks them up via hltb_client.HltbClient. A persistent mapping cache
(cache/hltb_map.json, keyed `${store}:${id}`) means re-runs only retry rows that
previously failed - so this is cheap to run on a cron.

Negative lookups are cached as the literal value False so retries don't spam
HowLongToBeat. Pass --retry-misses to force re-lookup of those.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from hltb_client import HltbClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAPPING_FILE = Path("cache/hltb_map.json")
QUERY_DELAY_SEC = 0.4  # be polite to HLTB; howlongtobeatpy doesn't throttle itself
SAVE_EVERY_N_LOOKUPS = 25

STORE_FILES = [
    ("games_steam.json", "steam"),
    ("games_gog.json", "gog"),
    ("games_psn.json", "psn"),
    ("games_epic.json", "epic"),
    ("games_amazon.json", "amazon"),
    ("games_xbox.json", "xbox"),
    ("games_battlenet.json", "battlenet"),
    ("games_ubisoft.json", "ubisoft"),
    ("games_nintendo.json", "nintendo"),
    ("games_itch.json", "itch"),
    ("games_wishlist.json", "wishlist"),
    ("games_wishlist_gog.json", "wishlist"),
    ("games_wishlist_epic.json", "wishlist"),
]

HLTB_FIELDS = (
    "hltb_id",
    "hltb_name",
    "hltb_main_hours",
    "hltb_main_extra_hours",
    "hltb_completionist_hours",
    "hltb_match_confidence",
)


def load_mapping() -> dict:
    if MAPPING_FILE.exists():
        try:
            return json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_mapping(mapping: dict) -> None:
    mapping["fetched_at"] = datetime.now(timezone.utc).isoformat()
    MAPPING_FILE.parent.mkdir(parents=True, exist_ok=True)
    MAPPING_FILE.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help="Re-attempt rows previously cached as having no HLTB match.",
    )
    parser.add_argument(
        "--store",
        choices=[s for _, s in STORE_FILES],
        help="Only enrich one store (default: all).",
    )
    args = parser.parse_args()

    hltb = HltbClient()
    mapping = load_mapping()
    grand_lookups = 0
    grand_updated = 0

    for filename, store in STORE_FILES:
        if args.store and args.store != store:
            continue
        path = Path(filename)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        missing = [g for g in games if g.get("hltb_main_hours") is None]
        if not missing:
            print(f"=== {filename}: nothing to enrich ===")
            continue
        print(f"\n=== {filename}: {len(missing)}/{len(games)} need HLTB ===")
        updated = 0
        for i, g in enumerate(missing, 1):
            key = f"{store}:{g.get('id')}"
            cached = mapping.get(key)

            if cached is False and not args.retry_misses:
                continue

            if isinstance(cached, dict):
                hit = cached
            else:
                time.sleep(QUERY_DELAY_SEC)
                try:
                    hit = hltb.lookup(g.get("name") or "")
                except Exception as e:
                    print(f"  hltb error for {g.get('name')!r}: {e}")
                    continue
                grand_lookups += 1
                mapping[key] = hit if hit else False
                if grand_lookups % SAVE_EVERY_N_LOOKUPS == 0:
                    save_mapping(mapping)

            if not hit:
                continue

            for field in HLTB_FIELDS:
                if hit.get(field) is not None:
                    g[field] = hit[field]
            updated += 1
            grand_updated += 1
            if updated % 25 == 0:
                print(
                    f"  [{i}/{len(missing)}] {updated} updated so far "
                    f"({g.get('name')} -> {hit.get('hltb_main_hours')}h, "
                    f"match {hit.get('hltb_match_confidence')})"
                )

        data["game_count"] = len(games)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  saved {updated} HLTB updates to {filename}")
        save_mapping(mapping)

    save_mapping(mapping)
    print(
        f"\nDone. {grand_lookups} fresh HLTB lookups, {grand_updated} rows updated."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
