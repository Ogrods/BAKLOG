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

from fetchers._base import catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, heartbeat, started
from hltb_client import HltbClient
from itch_game import itch_is_videogame as _itch_is_videogame
from shared.profile_paths import cache_json_path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def mapping_file() -> Path:
    return cache_json_path("hltb_map.json")
QUERY_DELAY_SEC = 0.4  # be polite to HLTB; howlongtobeatpy doesn't throttle itself
SAVE_EVERY_N_LOOKUPS = 25
HEARTBEAT_EVERY = 25

STORE_FILES = [
    ("games_steam.json", "steam", None),
    ("games_gog.json", "gog", None),
    ("games_psn.json", "psn", None),
    ("games_epic.json", "epic", None),
    ("games_amazon.json", "amazon", None),
    ("games_xbox.json", "xbox", None),
    ("games_battlenet.json", "battlenet", None),
    ("games_ubisoft.json", "ubisoft", None),
    ("games_nintendo.json", "nintendo", None),
    ("games_wishlist.json", "wishlist", None),
    ("games_itch.json", "itch", _itch_is_videogame),
    ("games_ea.json", "ea", None),
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
    path = mapping_file()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_mapping(mapping: dict) -> None:
    mapping["fetched_at"] = datetime.now(timezone.utc).isoformat()
    path = mapping_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
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
        choices=[s for _, s, _ in STORE_FILES],
        help="Only enrich one store (default: all).",
    )
    args = parser.parse_args()

    t0 = started("enrich_hltb")
    stats = RunStats()
    hltb = HltbClient()
    mapping = load_mapping()
    grand_lookups = 0
    grand_updated = 0
    # Wall-clock heartbeat: HLTB network lookups are slow and often miss, so a
    # batch of new lookups (e.g. a fresh GOG library) can stay silent well past
    # the dev server's 180s stall watchdog and get force-killed. Ticked before
    # each lookup so silence never approaches that ceiling.
    hb = HeartbeatTimer(45.0)

    for filename, store, row_filter in STORE_FILES:
        if args.store and args.store != store:
            continue
        rel = Path(filename)
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        eligible = games if row_filter is None else [g for g in games if row_filter(g)]
        missing = [g for g in eligible if g.get("hltb_main_hours") is None]
        if not missing:
            print(f"=== {filename}: nothing to enrich ===", flush=True)
            continue
        filter_note = f" ({len(eligible)} eligible)" if row_filter is not None else ""
        print(
            f"\n=== {filename}: {len(missing)}/{len(games)} need HLTB{filter_note} ===",
            flush=True,
        )
        hb.reset()
        updated = 0
        store_lookups = 0
        store_hits = 0
        store_misses = 0
        store_skipped = 0
        processed = 0
        for i, g in enumerate(missing, 1):
            key = f"{store}:{g.get('id')}"
            cached = mapping.get(key)
            processed += 1
            hb.tick(
                f"{filename}: [{i}/{len(missing)}] {store_lookups} lookups "
                f"(+{store_hits} hits) — still working"
            )

            if cached is False and not args.retry_misses:
                store_skipped += 1
                if processed % HEARTBEAT_EVERY == 0:
                    heartbeat(
                        f"[{i}/{len(missing)}] skipped {store_skipped} cached misses, "
                        f"{store_lookups} lookups (+{store_hits} hits) — still working"
                    )
                    hb.reset()
                continue

            if isinstance(cached, dict):
                hit = cached
            else:
                time.sleep(QUERY_DELAY_SEC)
                try:
                    hit = hltb.lookup(g.get("name") or "")
                except Exception as e:
                    stats.warn(f"hltb error for {g.get('name')!r}: {e}")
                    continue
                grand_lookups += 1
                store_lookups += 1
                if hit:
                    store_hits += 1
                else:
                    store_misses += 1
                mapping[key] = hit if hit else False
                if grand_lookups % SAVE_EVERY_N_LOOKUPS == 0:
                    save_mapping(mapping)
                if store_lookups % HEARTBEAT_EVERY == 0:
                    heartbeat(
                        f"[{i}/{len(missing)}] checked {store_lookups} "
                        f"(+{store_hits} hits, {store_misses} no-match) — still working"
                    )
                    hb.reset()

            if not hit:
                continue

            for field in HLTB_FIELDS:
                if hit.get(field) is not None:
                    g[field] = hit[field]
            updated += 1
            grand_updated += 1
            stats.ok += 1
            if updated % 25 == 0:
                print(
                    f"  [{i}/{len(missing)}] {updated} updated so far "
                    f"({g.get('name')} -> {hit.get('hltb_main_hours')}h, "
                    f"match {hit.get('hltb_match_confidence')})",
                    flush=True,
                )
                hb.reset()

        data["game_count"] = len(games)
        write_catalog_text(rel, json.dumps(data, indent=2, ensure_ascii=False))
        print(
            f"  saved {updated} HLTB updates to {filename} "
            f"({store_lookups} lookups: {store_hits} hits, {store_misses} no-match, "
            f"{store_skipped} skipped from cache)",
            flush=True,
        )
        save_mapping(mapping)

    save_mapping(mapping)
    stats.ok = grand_updated
    return stats.finish(
        "enrich_hltb",
        t0,
        exit_code=0,
        extra=f"{grand_lookups} lookups, {grand_updated} updated",
    )


if __name__ == "__main__":
    raise SystemExit(main())
