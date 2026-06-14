"""Backfill steam_review_percent for non-Steam library rows.

For each game in any non-Steam games_*.json that lacks a steam_review_percent,
search Steam's store for a matching title, then pull the review summary. Saves
a small mapping file so repeat runs are fast. Pass --retry-misses to re-attempt
rows previously cached as having no Steam app match (appid 0).

Covered stores: gog, epic, psn, amazon, xbox, battlenet, ubisoft, nintendo, humble, itch.

itch.io: only videogame rows per itch_game.itch_is_videogame (skips tools, assets, etc.).
"""

import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import requests

from auth import resolve_env
from fetchers._base import STEAM_CREDENTIALS_HINT, catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, started
from itch_game import itch_is_videogame as _itch_is_videogame
from shared.profile_paths import cache_json_path
from shared.steam_match import pick_appid
from steam_client import SteamClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def mapping_file() -> Path:
    return cache_json_path("steam_review_map.json")
SEARCH_DELAY_SEC = 1.0
SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
HEADERS = {"User-Agent": "Mozilla/5.0 backlog/1.0"}

STORE_FILES: list[tuple[str, str, Callable[[dict], bool] | None]] = [
    ("games_gog.json", "gog", None),
    ("games_epic.json", "epic", None),
    ("games_psn.json", "psn", None),
    ("games_amazon.json", "amazon", None),
    ("games_xbox.json", "xbox", None),
    ("games_battlenet.json", "battlenet", None),
    ("games_ubisoft.json", "ubisoft", None),
    ("games_nintendo.json", "nintendo", None),
    ("games_humble.json", "humble", None),
    ("games_itch.json", "itch", _itch_is_videogame),
    ("games_ea.json", "ea", None),
]


def _humble_steam_appid(g: dict) -> int | None:
    """Steam app id embedded by fetch_humble (skips store search when present)."""
    raw = g.get("humble_steam_app_id") or g.get("steam_app_id")
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def load_mapping() -> dict:
    path = mapping_file()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_mapping(mapping: dict) -> None:
    mapping["fetched_at"] = datetime.now(UTC).isoformat()
    path = mapping_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def steam_search(name: str) -> int | None:
    """Return the most likely Steam appid for a game title, or None."""
    time.sleep(SEARCH_DELAY_SEC)
    try:
        r = requests.get(
            SEARCH_URL,
            params={"term": name, "l": "english", "cc": "us"},
            headers=HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            snippet = (r.text or "")[:120].replace("\n", " ")
            print(
                f"  HTTP {r.status_code} for {r.url}: {snippet}",
                flush=True,
            )
            return None
        items = r.json().get("items") or []
    except Exception as e:
        print(f"  search error for {name!r}: {e}", flush=True)
        return None
    if not items:
        return None
    return pick_appid(items, name)


def steam_appids_by_id() -> set[int]:
    try:
        data = json.loads(catalog_file(Path("games_steam.json")).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    return {g["id"] for g in data.get("games", [])}


def main() -> int:
    import argparse

    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="Backfill Steam review fields on non-Steam library JSON.")
    parser.add_argument(
        "--stores",
        nargs="+",
        choices=["gog", "epic", "psn", "amazon", "xbox", "battlenet", "ubisoft", "nintendo", "humble", "itch"],
        metavar="STORE",
        help="Only process these stores (default: all). Example: --stores nintendo",
    )
    parser.add_argument(
        "--retry-misses",
        action="store_true",
        help='Re-attempt rows previously cached as "no Steam app match" (appid 0).',
    )
    parser.add_argument(
        "--refresh-empty",
        action="store_true",
        help=(
            "Re-fetch Steam review summaries for rows that have a mapped appid "
            "but steam_review_percent is still null (skips store search)."
        ),
    )
    args = parser.parse_args()
    t0 = started("enrich_steam_reviews")
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
        return stats.finish("enrich_steam_reviews", t0, exit_code=1)

    steam = SteamClient(api_key=api_key, steam_id=steam_id)
    mapping = load_mapping()
    owned_ids = steam_appids_by_id()
    hb = HeartbeatTimer(45.0)

    for filename, store, row_filter in store_files:
        rel = Path(filename)
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        games = data.get("games", [])
        eligible = [g for g in games if row_filter is None or row_filter(g)]
        print(f"\n=== {filename} ({len(eligible)} eligible / {len(games)} rows) ===", flush=True)
        hb.reset()
        updated = 0
        searched = 0
        for i, g in enumerate(games, 1):
            hb.tick_progress(i, len(games), f"reviews {filename}", f"{updated} updated")
            if row_filter is not None and not row_filter(g):
                continue
            if g.get("steam_review_percent") is not None:
                continue
            key = f"{store}:{g['id']}"
            cached_appid = mapping.get(key)

            if cached_appid == 0 and not args.retry_misses:
                continue
            if cached_appid == 0 and args.retry_misses:
                del mapping[key]
                cached_appid = None
            appid: int | None = cached_appid

            if appid is None:
                if args.refresh_empty:
                    continue
                if store == "humble":
                    direct = _humble_steam_appid(g)
                    if direct:
                        appid = direct
                        mapping[key] = direct
                if appid is None:
                    appid = steam_search(g["name"])
                    searched += 1
                    mapping[key] = appid if appid else 0
                if searched % 10 == 0:
                    save_mapping(mapping)
                    print(
                        f"  [{i}/{len(games)}] searched {searched}, {updated} updated so far",
                        flush=True,
                    )
            if not appid:
                continue

            if appid in owned_ids:
                pass

            try:
                reviews = steam.get_review_summary(appid, refresh=args.refresh_empty)
            except Exception as e:
                stats.warn(f"reviews error for {g['name']} ({appid}): {e}")
                continue
            if not reviews or reviews.get("percent_positive") is None:
                continue
            g["steam_review_percent"] = reviews["percent_positive"]
            g["steam_review_count"] = reviews.get("total_reviews")
            g["steam_review_desc"] = reviews.get("review_score_desc")
            updated += 1
            stats.ok += 1
            if updated % 25 == 0:
                print(
                    f"  [{i}/{len(games)}] {updated} updated so far "
                    f"({g['name']} -> {reviews['percent_positive']}%)",
                    flush=True,
                )

        data["game_count"] = len(games)
        write_catalog_text(rel, json.dumps(data, indent=2, ensure_ascii=False))
        print(f"  updated {updated} rows in {filename}", flush=True)
        save_mapping(mapping)

    save_mapping(mapping)
    return stats.finish("enrich_steam_reviews", t0, exit_code=0, extra=f"{stats.ok} rows")


if __name__ == "__main__":
    raise SystemExit(main())
