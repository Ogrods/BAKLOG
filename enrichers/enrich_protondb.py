from __future__ import annotations
import argparse
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import requests
from clients.itch_game import itch_is_videogame as _itch_is_videogame
from fetchers._base import catalog_file, write_catalog_text
from fetchers._progress import HeartbeatTimer, RunStats, started
from shared.profile_paths import cache_json_path
sys.stdout.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
SUMMARY_URL = 'https://www.protondb.com/api/v1/reports/summaries/{appid}.json'
HEADERS = {'User-Agent': 'Mozilla/5.0 backlog/1.0'}
QUERY_DELAY_SEC = 0.25
SAVE_EVERY_N_LOOKUPS = 25
HEARTBEAT_EVERY = 25
PROTONDB_FIELDS = ('protondb_tier', 'protondb_confidence', 'protondb_report_count', 'protondb_score', 'protondb_trending_tier')
STORE_FILES: list[tuple[str, str, Callable[[dict], bool] | None]] = [('games_steam.json', 'steam', None), ('games_gog.json', 'gog', None), ('games_epic.json', 'epic', None), ('games_psn.json', 'psn', None), ('games_amazon.json', 'amazon', None), ('games_xbox.json', 'xbox', None), ('games_battlenet.json', 'battlenet', None), ('games_ubisoft.json', 'ubisoft', None), ('games_nintendo.json', 'nintendo', None), ('games_humble.json', 'humble', None), ('games_itch.json', 'itch', _itch_is_videogame), ('games_ea.json', 'ea', None)]

def mapping_file() -> Path:
    return cache_json_path('protondb_map.json')

def review_map_file() -> Path:
    return cache_json_path('steam_review_map.json')

def load_mapping() -> dict:
    path = mapping_file()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            return {}
    return {}

def load_review_map() -> dict:
    path = review_map_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return {}

def save_mapping(mapping: dict) -> None:
    mapping['fetched_at'] = datetime.now(UTC).isoformat()
    path = mapping_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding='utf-8')

def effective_tier(summary: dict) -> str | None:
    tier = summary.get('tier')
    if isinstance(tier, str) and tier and (tier != 'pending'):
        return tier
    provisional = summary.get('provisionalTier')
    if isinstance(provisional, str) and provisional and (provisional != 'pending'):
        return provisional
    if isinstance(tier, str) and tier:
        return tier
    if isinstance(provisional, str) and provisional:
        return provisional
    return None

def summary_to_row_fields(summary: dict) -> dict:
    tier = effective_tier(summary)
    total = summary.get('total')
    score = summary.get('score')
    trending = summary.get('trendingTier')
    return {'protondb_tier': tier, 'protondb_confidence': summary.get('confidence'), 'protondb_report_count': int(total) if total is not None else None, 'protondb_score': float(score) if score is not None else None, 'protondb_trending_tier': trending if trending not in (None, 'pending') else None}

def fetch_summary(appid: int) -> dict | None | False:
    time.sleep(QUERY_DELAY_SEC)
    try:
        response = requests.get(SUMMARY_URL.format(appid=appid), headers=HEADERS, timeout=20)
    except requests.RequestException as exc:
        print(f'  protondb request error for {appid}: {exc}', flush=True)
        return None
    if response.status_code == 404:
        return False
    if response.status_code != 200:
        snippet = (response.text or '')[:120].replace('\n', ' ')
        print(f'  protondb HTTP {response.status_code} for appid {appid}: {snippet}', flush=True)
        return None
    try:
        data = response.json()
    except json.JSONDecodeError:
        print(f'  protondb invalid JSON for appid {appid}', flush=True)
        return None
    if not isinstance(data, dict):
        return None
    return data

def resolve_appid(store: str, game: dict, review_map: dict) -> int | None:
    if store == 'steam':
        try:
            return int(game['id'])
        except (TypeError, ValueError, KeyError):
            return None
    key = f"{store}:{game.get('id')}"
    raw = review_map.get(key)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None

def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description='Backfill ProtonDB compatibility summaries on library rows.')
    parser.add_argument('--stores', nargs='+', choices=[s for _, s, _ in STORE_FILES], metavar='STORE', help='Only process these stores (default: all).')
    parser.add_argument('--retry-misses', action='store_true', help='Re-attempt appids previously cached as "no reports" (false).')
    parser.add_argument('--refresh', action='store_true', help='Re-fetch summaries even when rows already have protondb_tier.')
    args = parser.parse_args(argv)
    t0 = started('enrich_protondb')
    stats = RunStats()
    store_files = STORE_FILES
    if args.stores:
        wanted = set(args.stores)
        store_files = [row for row in STORE_FILES if row[1] in wanted]
    review_map = load_review_map()
    mapping = load_mapping()
    hb = HeartbeatTimer(45.0)
    lookups = 0
    updated = 0
    for filename, store, row_filter in store_files:
        rel = Path(filename)
        path = catalog_file(rel)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding='utf-8'))
        games = data.get('games', [])
        eligible = [g for g in games if row_filter is None or row_filter(g)]
        print(f'\n=== {filename} ({len(eligible)} eligible / {len(games)} rows) ===', flush=True)
        hb.reset()
        file_updated = 0
        for i, g in enumerate(games, 1):
            hb.tick_progress(i, len(games), f'protondb {filename}', f'{file_updated} updated')
            if row_filter is not None and (not row_filter(g)):
                continue
            if g.get('protondb_tier') is not None and (not args.refresh):
                continue
            appid = resolve_appid(store, g, review_map)
            if appid is None:
                continue
            cache_key = str(appid)
            cached = mapping.get(cache_key)
            if cached is False and (not args.retry_misses):
                continue
            if cached is False and args.retry_misses:
                del mapping[cache_key]
                cached = None
            summary = cached if isinstance(cached, dict) else None
            if summary is None:
                fetched = fetch_summary(appid)
                lookups += 1
                if fetched is None:
                    continue
                mapping[cache_key] = fetched if fetched else False
                if lookups % SAVE_EVERY_N_LOOKUPS == 0:
                    save_mapping(mapping)
                if not fetched:
                    continue
                summary = fetched
            fields = summary_to_row_fields(summary)
            if fields['protondb_tier'] is None and fields['protondb_report_count'] in (None, 0):
                continue
            for key, value in fields.items():
                g[key] = value
            file_updated += 1
            updated += 1
            stats.ok += 1
            if file_updated % 25 == 0:
                print(f"  [{i}/{len(games)}] {file_updated} updated so far ({g.get('name')} -> {fields['protondb_tier']})", flush=True)
        if file_updated:
            data['game_count'] = len(games)
            write_catalog_text(rel, json.dumps(data, indent=2, ensure_ascii=False))
        print(f'  updated {file_updated} rows in {filename}', flush=True)
    save_mapping(mapping)
    return stats.finish('enrich_protondb', t0, exit_code=0, extra=f'{lookups} lookups, {updated} rows')
if __name__ == '__main__':
    raise SystemExit(main())