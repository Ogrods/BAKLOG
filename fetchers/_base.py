from __future__ import annotations
import argparse
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from shared.json_util import dumps_games_json
from shared.profile_paths import resolve_catalog_path
from shared.safe_write import safe_write_text
STEAM_CREDENTIALS_HINT = 'Steam is not connected for this profile. Open Connections → Steam → Connect (sign in to capture your API key and SteamID).'
STEAM_PRIVATE_PROFILE_HINT = 'Steam returned 0 games — set Steam Profile → Privacy → Game details to Public, then retry.'

def catalog_file(path: Path) -> Path:
    return resolve_catalog_path(path)

def write_catalog_text(path: Path, text: str) -> Path:
    disk = resolve_catalog_path(path)
    safe_write_text(disk, text)
    try:
        from shared.cloud_mirror import schedule_mirror_upload
        schedule_mirror_upload(disk)
    except Exception:
        pass
    return disk

def configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, OSError):
            pass

def add_only_new_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--only-new', action='store_true', help='Skip per-row enrichment for titles already in the output file')

def add_hltb_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--skip-hltb', action='store_true', help='Skip HowLongToBeat lookups')
    add_only_new_arg(parser)

def add_dry_run_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--dry-run', action='store_true', help='Print summary and skip writing the output JSON file')

def add_allow_empty_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--allow-empty', action='store_true', help='Allow writing an empty result (e.g. genuinely empty wishlist).')
    parser.add_argument('--allow-drift', action='store_true', help='Allow writing a result that is sharply smaller than the previous fetch (default threshold: 50%%). Use when a store legitimately lost titles (delisted, deauthorized devices, etc.).')

def add_no_carry_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument('--rebuild', '--no-carry', dest='no_carry', action='store_true', help='Write only games returned by this fetch (drop stale carried rows). Use to prune genuinely removed titles.')
STALE_FIELD = 'stale'
STALE_SINCE_FIELD = 'stale_since'
LAST_SEEN_FIELD = 'last_seen'
RowKeyFn = Callable[[dict[str, Any]], str]

def carry_forward_missing(fresh_rows: list[dict[str, Any]], existing_rows: list[dict[str, Any]], *, key_fn: RowKeyFn, now_iso: str | None=None) -> list[dict[str, Any]]:
    now = now_iso or datetime.now(UTC).isoformat()
    present = {key_fn(r) for r in fresh_rows}
    out: list[dict[str, Any]] = []
    for row in fresh_rows:
        merged = dict(row)
        merged[LAST_SEEN_FIELD] = now
        merged.pop(STALE_FIELD, None)
        merged.pop(STALE_SINCE_FIELD, None)
        out.append(merged)
    for old in existing_rows:
        if key_fn(old) in present:
            continue
        carried = dict(old)
        carried[STALE_FIELD] = True
        carried.setdefault(STALE_SINCE_FIELD, now)
        carried.setdefault(LAST_SEEN_FIELD, old.get(LAST_SEEN_FIELD))
        out.append(carried)
    return out

def apply_carry_forward(games_out: list[dict[str, Any]], existing: dict[str, dict[str, Any]] | list[dict[str, Any]], *, key_fn: RowKeyFn, no_carry: bool=False, now_iso: str | None=None) -> list[dict[str, Any]]:
    if no_carry:
        return games_out
    existing_rows = list(existing.values()) if isinstance(existing, dict) else list(existing)
    carried = carry_forward_missing(games_out, existing_rows, key_fn=key_fn, now_iso=now_iso)
    added = len(carried) - len(games_out)
    if added:
        print(f'  Carried forward {added} game(s) missing from this fetch (marked {STALE_FIELD}=true).', flush=True)
    return carried

def row_key_by_id(row: dict[str, Any]) -> str:
    return str(row.get('id'))

def row_key_by_appid(row: dict[str, Any]) -> str:
    return str(row.get('appid') or row.get('id'))

def refuse_empty_result(items: list[Any] | int, *, label: str, allow_empty: bool, output_path: Path | None=None) -> int | None:
    count = len(items) if isinstance(items, list) else items
    if count or allow_empty:
        return None
    where = f' ({output_path})' if output_path else ''
    print(f'ERROR: {label} returned 0 items{where} — refusing to overwrite existing file.\nIf this is genuinely empty, re-run with --allow-empty.', file=sys.stderr, flush=True)
    return 2

def _previous_game_count(output_path: Path | None) -> int | None:
    if output_path is not None:
        output_path = resolve_catalog_path(output_path)
    if output_path is None or not output_path.exists():
        return None
    try:
        data = json.loads(output_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    gc = data.get('game_count')
    if isinstance(gc, int) and gc >= 0:
        return gc
    games = data.get('games')
    if isinstance(games, list):
        return len(games)
    return None

def refuse_drift_result(items: list[Any] | int, *, label: str, allow_drift: bool, output_path: Path | None, threshold: float=0.5) -> int | None:
    new_count = len(items) if isinstance(items, list) else items
    prev = _previous_game_count(output_path)
    if prev is None or prev <= 0 or allow_drift:
        return None
    floor = max(1, int(prev * threshold))
    if new_count >= floor:
        return None
    pct = new_count / prev * 100 if prev else 0.0
    where = f' ({output_path})' if output_path else ''
    print(f'ERROR: {label} returned {new_count} items{where}, but the previous run had {prev} (≈{pct:.0f}% — under the {int(threshold * 100)}% floor).\nLikely a broken auth or upstream API. If this drop is real, re-run with --allow-drift.', file=sys.stderr, flush=True)
    return 3

def guard_catalog_write(items: list[Any] | int, *, label: str, output_path: Path | None, allow_empty: bool=False, allow_drift: bool=False, threshold: float=0.5) -> int | None:
    empty_exit = refuse_empty_result(items, label=label, allow_empty=allow_empty, output_path=output_path)
    if empty_exit is not None:
        return empty_exit
    return refuse_drift_result(items, label=label, allow_drift=allow_drift, output_path=output_path, threshold=threshold)

def write_catalog_guarded(path: Path, text: str, *, count: list[Any] | int, label: str, allow_empty: bool=False, allow_drift: bool=False, threshold: float=0.5) -> int:
    refused = guard_catalog_write(count, label=label, output_path=path, allow_empty=allow_empty, allow_drift=allow_drift, threshold=threshold)
    if refused is not None:
        return refused
    write_catalog_text(path, text)
    return 0

def load_existing_games(path: Path, *, id_key: str='id') -> dict[str, dict[str, Any]]:
    path = resolve_catalog_path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    games = data.get('games') or []
    return {str(g[id_key]): g for g in games if isinstance(g, dict) and g.get(id_key) is not None}

def write_games_json(path: Path, *, store: str, games: list[dict[str, Any]], dry_run: bool=False) -> bool:
    path = resolve_catalog_path(path)
    payload = {'fetched_at': datetime.now(UTC).isoformat(), 'store': store, 'game_count': len(games), 'games': games}
    if dry_run:
        return False
    write_catalog_text(path, dumps_games_json(payload))
    return True

def print_id_diff(existing_ids: set[str], new_ids: set[str], *, label: str='Summary') -> tuple[set[str], set[str]]:
    added = new_ids - existing_ids
    removed = existing_ids - new_ids
    print(f'\n{label}: {len(new_ids)} rows ({len(added)} new, {len(removed)} dropped from file)')
    if added:
        print(f'  New ids: {len(added)}')
    if removed:
        print(f'  Removed ids: {len(removed)}')
    return (added, removed)
_IMAGE_KEYS = frozenset({'header_image', 'library_image'})
ENRICHMENT_FIELDS = ('steam_review_percent', 'steam_review_count', 'steam_review_desc', 'hltb_main_hours', 'hltb_main_extra_hours', 'hltb_completionist_hours', 'hltb_match_confidence', 'hltb_name', 'coop_online', 'coop_local', 'metacritic_score', 'developers', 'publishers', 'controller_support', 'early_access', 'acquired_at')
_ALLOW_EMPTY_OVERWRITE = frozenset({'price', 'price_initial', 'discount_percent', 'currency'})

def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value is False:
        return True
    if isinstance(value, (int, float)) and value == 0:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False

def carry_enrichment(winner: dict, loser: dict | None) -> dict:
    if not loser:
        return winner
    out = dict(winner)
    for key in ENRICHMENT_FIELDS:
        win_val = out.get(key)
        lose_val = loser.get(key)
        if (win_val is None or win_val == '' or win_val is False) and lose_val not in (None, '', False):
            out[key] = lose_val
    return out

def merge_cached_row(fresh: dict[str, Any], cached: dict[str, Any] | None, *, authoritative: frozenset[str], hltb_updated: bool=False, hltb_keys: tuple[str, ...]=('hltb_main_hours', 'hltb_main_extra_hours', 'hltb_completionist_hours', 'hltb_match_confidence', 'hltb_name')) -> dict[str, Any]:
    if not cached:
        return fresh
    merged = dict(cached)
    for key in authoritative:
        if key not in fresh:
            continue
        if key in _IMAGE_KEYS and (not fresh[key]):
            continue
        if key not in _ALLOW_EMPTY_OVERWRITE and _is_empty(fresh[key]) and (not _is_empty(merged.get(key))):
            continue
        merged[key] = fresh[key]
    if hltb_updated:
        for key in hltb_keys:
            fresh_val = fresh.get(key)
            if _is_empty(fresh_val) and (not _is_empty(merged.get(key))):
                continue
            merged[key] = fresh_val
    _apply_monotonic_play_dates(merged, cached, fresh)
    return merged

def _nonempty_iso(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

def _apply_monotonic_play_dates(merged: dict[str, Any], cached: dict[str, Any], fresh: dict[str, Any]) -> None:
    lasts = [v for v in (_nonempty_iso(cached.get('last_played')), _nonempty_iso(fresh.get('last_played'))) if v]
    if lasts:
        merged['last_played'] = max(lasts)
    firsts = [v for v in (_nonempty_iso(cached.get('first_played')), _nonempty_iso(fresh.get('first_played'))) if v]
    if firsts:
        merged['first_played'] = min(firsts)
RowBuilder = Callable[..., dict[str, Any]]