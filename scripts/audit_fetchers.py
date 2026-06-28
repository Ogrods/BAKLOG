from __future__ import annotations
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auth.manager import get_status
from auth.registry import PROVIDERS
from fetchers.registry import AUTH_PROVIDER_BY_KEY, LIBRARY_JSON_BY_KEY, WISHLIST_JSON_BY_KEY, manifest_entries
from shared.profile_paths import cache_json_path, catalog_path, get_active_profile_id, itad_path, list_profiles, profile_label, runs_dir, set_request_profile_id
BASE = 'http://127.0.0.1:8765'
FRESH_MS_DEFAULT = 7 * 86400 * 1000
RECENT_MS_DEFAULT = 30 * 86400 * 1000
FRESH_MS_ITAD = 60 * 60 * 1000
RECENT_MS_ITAD = 6 * 60 * 60 * 1000
ENRICH_CACHE_BY_KEY: dict[str, str] = {'hltb': 'hltb_map.json', 'steamReviews': 'steam_review_map.json', 'steamCovers': 'cross_store_images_meta.json', 'steamTags': 'steam_tags_meta.json', 'protondb': 'protondb_map.json'}
GROUP_ORDER = ('library', 'wishlist', 'prices', 'enrich')

@dataclass
class ArtifactInfo:
    path: str | None = None
    exists: bool = False
    size_bytes: int | None = None
    mtime_iso: str | None = None
    fetched_at: str | None = None
    game_count: int | None = None

@dataclass
class RunInfo:
    status: str | None = None
    exit_code: int | None = None
    ended_at: str | None = None
    failure_kind: str | None = None

@dataclass
class FetcherRow:
    key: str
    label: str
    group: str
    status: str
    games: str
    age: str
    last_run: str
    provider: str
    artifact: ArtifactInfo = field(default_factory=ArtifactInfo)
    last_run_detail: RunInfo | None = None
    providers: list[str] = field(default_factory=list)
    provider_states: dict[str, str] = field(default_factory=dict)

def providers_for_fetcher(key: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    primary = AUTH_PROVIDER_BY_KEY.get(key)
    if primary and primary not in seen:
        seen.add(primary)
        out.append(primary)
    for pid, spec in PROVIDERS.items():
        if key in spec.fetcher_keys and pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out

def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.replace('Z', '+00:00')
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None

def age_label(fetched_at: str | None, *, key: str) -> str:
    dt = parse_iso(fetched_at)
    if not dt:
        return '-'
    age_ms = (datetime.now(UTC) - dt).total_seconds() * 1000
    if age_ms < 3600000:
        return f'{int(age_ms / 60000)}m'
    if age_ms < 86400000:
        return f'{int(age_ms / 3600000)}h'
    return f'{int(age_ms / 86400000)}d'

def stale_thresholds_ms(key: str) -> tuple[int, int]:
    if key == 'itad':
        return (FRESH_MS_ITAD, RECENT_MS_ITAD)
    return (FRESH_MS_DEFAULT, RECENT_MS_DEFAULT)

def is_stale(fetched_at: str | None, key: str) -> bool:
    dt = parse_iso(fetched_at)
    if not dt:
        return False
    _, recent_ms = stale_thresholds_ms(key)
    age_ms = (datetime.now(UTC) - dt).total_seconds() * 1000
    return age_ms >= recent_ms

def load_json_file(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None

def enrich_count(key: str, data: dict[str, Any]) -> int | None:
    if key == 'itad':
        by_key = data.get('by_key')
        return len(by_key) if isinstance(by_key, dict) else None
    if key in ('hltb', 'steamReviews'):
        return len([k for k in data if k != 'fetched_at'])
    if key == 'steamCovers':
        lu = data.get('last_updated')
        return int(lu) if isinstance(lu, (int, float)) else None
    if key == 'steamTags':
        ru = data.get('rows_updated')
        return int(ru) if isinstance(ru, (int, float)) else None
    return None

def enrich_fetched_at(key: str, data: dict[str, Any]) -> str | None:
    if data.get('fetched_at'):
        return str(data['fetched_at'])
    if key == 'steamCovers' and data.get('last_updated'):
        return datetime.fromtimestamp(float(data['last_updated']), UTC).isoformat()
    return None

def artifact_path_for(key: str, group: str, profile_id: str) -> Path | None:
    if group == 'library' and key in LIBRARY_JSON_BY_KEY:
        return catalog_path(LIBRARY_JSON_BY_KEY[key], profile_id=profile_id)
    if group == 'wishlist' and key in WISHLIST_JSON_BY_KEY:
        return catalog_path(WISHLIST_JSON_BY_KEY[key], profile_id=profile_id)
    if key == 'itad':
        return itad_path(profile_id=profile_id)
    if key in ENRICH_CACHE_BY_KEY:
        return cache_json_path(ENRICH_CACHE_BY_KEY[key], profile_id=profile_id)
    return None

def read_artifact(key: str, group: str, profile_id: str) -> ArtifactInfo:
    path = artifact_path_for(key, group, profile_id)
    if path is None:
        return ArtifactInfo()
    info = ArtifactInfo(path=str(path))
    if not path.is_file():
        return info
    info.exists = True
    st = path.stat()
    info.size_bytes = st.st_size
    info.mtime_iso = datetime.fromtimestamp(st.st_mtime, UTC).isoformat()
    data = load_json_file(path)
    if not data:
        return info
    if group in ('library', 'wishlist') or key == 'itad':
        info.fetched_at = data.get('fetched_at') if isinstance(data.get('fetched_at'), str) else None
        gc = data.get('game_count')
        if isinstance(gc, int):
            info.game_count = gc
        elif isinstance(data.get('games'), list):
            info.game_count = len(data['games'])
        elif key == 'itad':
            info.game_count = enrich_count('itad', data)
    elif group == 'enrich':
        info.fetched_at = enrich_fetched_at(key, data)
        info.game_count = enrich_count(key, data)
    return info

def load_history_by_key(profile_id: str) -> dict[str, dict[str, Any]]:
    hist_path = runs_dir(profile_id=profile_id) / 'history.json'
    if not hist_path.is_file():
        return {}
    try:
        rows = json.loads(hist_path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(rows, list):
        return {}
    by_key: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        k = row.get('key')
        if not k:
            continue
        prev = by_key.get(k)
        if prev is None:
            by_key[k] = row
            continue
        prev_end = prev.get('ended_at') or ''
        new_end = row.get('ended_at') or ''
        if new_end > prev_end:
            by_key[k] = row
    return by_key

def provider_status_map() -> dict[str, str]:
    return {p['key']: p.get('status') or 'disconnected' for p in get_status()}

def summarize_providers(states: dict[str, str]) -> str:
    if not states:
        return '-'
    uniq = sorted(set(states.values()))
    if len(uniq) == 1:
        return uniq[0]
    return '/'.join(uniq)

def classify_fetcher(key: str, group: str, artifact: ArtifactInfo, last_run: RunInfo | None, provider_states: dict[str, str]) -> str:
    states = list(provider_states.values()) if provider_states else []
    has_catalog = artifact.exists and artifact.fetched_at is not None
    count = artifact.game_count if artifact.game_count is not None else 0
    if states and all((s == 'unavailable' for s in states)):
        return 'UNAVAILABLE'
    if not has_catalog and states and all((s == 'disconnected' for s in states)):
        return 'DISCONNECTED'
    if any((s == 'expired' for s in states)):
        return 'BROKEN/expired'
    if last_run and last_run.status == 'failed':
        if last_run.exit_code == 4 or last_run.failure_kind == 'auth':
            return 'BROKEN/auth'
        return 'BROKEN'
    if not has_catalog and last_run is None:
        return 'NEVER_RUN'
    if has_catalog and count == 0:
        return 'EMPTY'
    if has_catalog and is_stale(artifact.fetched_at, key):
        return 'STALE'
    if has_catalog and count > 0:
        return 'HEALTHY'
    if has_catalog:
        return 'STALE' if is_stale(artifact.fetched_at, key) else 'EMPTY'
    return 'NEVER_RUN'

def format_last_run(run: RunInfo | None) -> str:
    if not run or not run.status:
        return '-'
    exit_bit = f' exit {run.exit_code}' if run.exit_code is not None else ''
    return f'{run.status}{exit_bit}'

def format_games(artifact: ArtifactInfo, group: str) -> str:
    if group == 'enrich' and artifact.game_count is None and (not artifact.exists):
        return 'N/A'
    if artifact.game_count is None:
        return '-'
    return str(artifact.game_count)

def build_rows(profile_id: str) -> list[FetcherRow]:
    set_request_profile_id(profile_id)
    try:
        pstatus = provider_status_map()
        history = load_history_by_key(profile_id)
        rows: list[FetcherRow] = []
        for entry in manifest_entries():
            key = entry.get('key')
            if not key:
                continue
            group = entry.get('group', 'library')
            label = entry.get('label', key)
            artifact = read_artifact(key, group, profile_id)
            provs = providers_for_fetcher(key)
            prov_states = {p: pstatus.get(p, 'disconnected') for p in provs}
            hist = history.get(key)
            run_info = None
            if hist:
                run_info = RunInfo(status=hist.get('status'), exit_code=hist.get('exit_code'), ended_at=hist.get('ended_at'), failure_kind=hist.get('failure_kind'))
            status = classify_fetcher(key, group, artifact, run_info, prov_states)
            rows.append(FetcherRow(key=key, label=label, group=group, status=status, games=format_games(artifact, group), age=age_label(artifact.fetched_at, key=key), last_run=format_last_run(run_info), provider=summarize_providers(prov_states), artifact=artifact, last_run_detail=run_info, providers=provs, provider_states=prov_states))
        return rows
    finally:
        set_request_profile_id(None)

def print_table(rows: list[FetcherRow], profile_id: str) -> None:
    label = profile_label(profile_id)
    print(f'\n=== Fetcher audit — profile {profile_id} ({label}) ===\n')
    header = f"{'KEY':<16} {'STATUS':<14} {'GAMES':<8} {'AGE':<8} {'LAST RUN':<22} {'PROVIDER':<16}"
    print(header)
    print('-' * len(header))
    by_group: dict[str, list[FetcherRow]] = defaultdict(list)
    for r in rows:
        by_group[r.group].append(r)
    for group in GROUP_ORDER:
        group_rows = by_group.get(group)
        if not group_rows:
            continue
        print(f'\n[{group}]')
        for r in sorted(group_rows, key=lambda x: x.key):
            print(f'{r.key:<16} {r.status:<14} {r.games:<8} {r.age:<8} {r.last_run:<22} {r.provider:<16}')
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        base = r.status.split('/')[0]
        counts[base] += 1
    parts = [f'{counts[k]} {k.lower()}' for k in sorted(counts.keys())]
    print(f"\nSummary: {(', '.join(parts) if parts else 'no fetchers')}")

def rows_to_json(rows: list[FetcherRow], profile_id: str) -> dict[str, Any]:
    return {'profile_id': profile_id, 'profile_label': profile_label(profile_id), 'generated_at': datetime.now(UTC).isoformat(), 'fetchers': [{**{k: v for k, v in asdict(r).items() if k not in ('artifact', 'last_run_detail')}, 'artifact': asdict(r.artifact), 'last_run_detail': asdict(r.last_run_detail) if r.last_run_detail else None} for r in rows]}

def api(method: str, path: str, timeout: float=30.0) -> tuple[int, dict | str]:
    req = urllib.request.Request(f'{BASE}{path}', method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return (resp.status, json.loads(body))
            except json.JSONDecodeError:
                return (resp.status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return (e.code, json.loads(body))
        except json.JSONDecodeError:
            return (e.code, body)

def wait_done(run_id: str, timeout: float=600.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, data = api('GET', '/api/runs')
        if code != 200 or not isinstance(data, dict):
            time.sleep(0.5)
            continue
        for r in data.get('history') or []:
            if r.get('id') == run_id and r.get('status') in ('done', 'failed', 'cancelled'):
                return r
        time.sleep(0.25)
    return None

def run_live(key: str, profile_id: str) -> int:
    entries = {e['key']: e for e in manifest_entries()}
    if key not in entries:
        print(f'Unknown fetcher key: {key}', file=sys.stderr)
        return 1
    before = read_artifact(key, entries[key].get('group', 'library'), profile_id)
    before_count = before.game_count
    print(f'POST /api/run/{key} …')
    code, body = api('POST', f'/api/run/{key}')
    if code not in (200, 202) or not isinstance(body, dict) or (not body.get('run_id')):
        print(f'Submit failed: HTTP {code} {body}', file=sys.stderr)
        return 1
    run_id = body['run_id']
    print(f'Run id={run_id}, waiting …')
    hist = wait_done(run_id)
    if not hist:
        print('Timed out waiting for run', file=sys.stderr)
        return 1
    after = read_artifact(key, entries[key].get('group', 'library'), profile_id)
    after_count = after.game_count
    print(f"Finished: status={hist.get('status')} exit_code={hist.get('exit_code')}")
    if hist.get('failure_kind'):
        print(f"  failure_kind={hist.get('failure_kind')}")
    print(f'  game_count: {before_count} -> {after_count}')
    return 0 if hist.get('exit_code') == 0 else 1

def audit_profile(profile_id: str, *, as_json: bool) -> list[FetcherRow]:
    rows = build_rows(profile_id)
    if as_json:
        print(json.dumps(rows_to_json(rows, profile_id), indent=2))
    else:
        print_table(rows, profile_id)
    return rows

def main() -> int:
    parser = argparse.ArgumentParser(description='Audit fetcher catalogs, runs, and Connections.')
    parser.add_argument('--profile', help='Profile id to audit (default: active from index)')
    parser.add_argument('--all-profiles', action='store_true', help='Audit every profile in index')
    parser.add_argument('--json', action='store_true', help='Emit machine-readable JSON')
    parser.add_argument('--live', metavar='KEY', help='Run one fetcher via server API and re-audit')
    args = parser.parse_args()
    if args.live:
        pid = args.profile or get_active_profile_id()
        return run_live(args.live, pid)
    if args.all_profiles:
        profiles = list_profiles()
        if not profiles:
            print('No profiles in index.', file=sys.stderr)
            return 1
        all_ok = True
        for p in profiles:
            pid = p.get('id')
            if not pid:
                continue
            rows = audit_profile(pid, as_json=args.json)
            manifest_keys = {e['key'] for e in manifest_entries()}
            if {r.key for r in rows} != manifest_keys:
                all_ok = False
        return 0 if all_ok else 1
    pid = args.profile or get_active_profile_id()
    rows = audit_profile(pid, as_json=args.json)
    manifest_keys = {e['key'] for e in manifest_entries()}
    if {r.key for r in rows} != manifest_keys:
        missing = manifest_keys - {r.key for r in rows}
        extra = {r.key for r in rows} - manifest_keys
        if missing or extra:
            print(f'WARN: key mismatch missing={missing} extra={extra}', file=sys.stderr)
            return 1
    return 0
if __name__ == '__main__':
    raise SystemExit(main())