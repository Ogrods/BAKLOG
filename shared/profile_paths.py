from __future__ import annotations
import contextvars
import json
import os
import re
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from shared.install_paths import data_root
_request_profile_id: contextvars.ContextVar[str | None] = contextvars.ContextVar('_request_profile_id', default=None)

def set_request_profile_id(profile_id: str | None) -> None:
    _request_profile_id.set(profile_id)

def clear_request_profile_id() -> None:
    _request_profile_id.set(None)
ROOT = data_root()
PROFILES_DIR = ROOT / 'profiles'
INDEX_FILE = PROFILES_DIR / 'index.json'
DEFAULT_PROFILE_ID = 'default'
MIGRATION_COMPLETE_MARKER = '.migration_complete'
_ENV_OVERRIDE = 'BAKLOG_PROFILE'
_SLUG_RE = re.compile('[^a-z0-9]+')
_PROFILE_ID_RE = re.compile('^[a-z0-9][a-z0-9-]*$')
_RESERVED_WIN_NAMES = frozenset({'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)), *(f'lpt{i}' for i in range(1, 10))})
_index_lock = threading.RLock()

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()

def _empty_index() -> dict[str, Any]:
    return {'active': DEFAULT_PROFILE_ID, 'profiles': [{'id': DEFAULT_PROFILE_ID, 'label': 'Default', 'created_at': _now_iso()}]}

def _quarantine_corrupt_index(exc: BaseException) -> Path | None:
    if not INDEX_FILE.is_file():
        return None
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')
    dest = INDEX_FILE.with_name(f'index.json.corrupt-{stamp}')
    try:
        INDEX_FILE.replace(dest)
    except OSError:
        return None
    print(f'[profiles] corrupt index.json quarantined to {dest.name}: {exc!r}', file=sys.stderr, flush=True)
    return dest

def _load_index_unlocked() -> dict[str, Any]:
    if not INDEX_FILE.exists():
        return _empty_index()
    try:
        doc = json.loads(INDEX_FILE.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        _quarantine_corrupt_index(exc)
        return _empty_index()
    if not isinstance(doc, dict):
        _quarantine_corrupt_index(ValueError('index root is not an object'))
        return _empty_index()
    doc.setdefault('active', DEFAULT_PROFILE_ID)
    profiles = doc.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        doc['profiles'] = _empty_index()['profiles']
    return doc

def load_index() -> dict[str, Any]:
    with _index_lock:
        return _load_index_unlocked()

def _validate_index_doc(doc: dict[str, Any]) -> None:
    active = doc.get('active')
    if active is not None and (not is_valid_profile_id(str(active))):
        raise ValueError(f'invalid active profile in index: {active!r}')
    profiles = doc.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        raise ValueError('profiles index must list at least one profile')
    profile_ids: set[str] = set()
    for p in profiles:
        if isinstance(p, dict) and p.get('id') is not None:
            pid = normalize_profile_id(str(p['id']))
            profile_ids.add(pid)
    if active is not None and str(active) not in profile_ids:
        raise ValueError(f'active profile {active!r} is not in profiles list')

def _save_index_unlocked(doc: dict[str, Any]) -> None:
    _validate_index_doc(doc)
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, INDEX_FILE)

def save_index(doc: dict[str, Any]) -> None:
    with _index_lock:
        _save_index_unlocked(doc)

@contextmanager
def mutate_index() -> Iterator[dict[str, Any]]:
    with _index_lock:
        doc = _load_index_unlocked()
        yield doc
        _save_index_unlocked(doc)

def is_valid_profile_id(profile_id: str) -> bool:
    pid = (profile_id or '').strip()
    if not pid or pid in ('.', '..'):
        return False
    if pid.lower() in _RESERVED_WIN_NAMES:
        return False
    if not _PROFILE_ID_RE.match(pid):
        return False
    try:
        resolved = (PROFILES_DIR / pid).resolve()
        base = PROFILES_DIR.resolve()
        return resolved == base or str(resolved).startswith(str(base) + os.sep)
    except (OSError, RuntimeError):
        return False

def normalize_profile_id(profile_id: str) -> str:
    pid = (profile_id or '').strip()
    if not is_valid_profile_id(pid):
        raise ValueError(f'invalid profile id: {profile_id!r}')
    return pid

def get_active_profile_id(*, doc: dict[str, Any] | None=None) -> str:
    ctx = _request_profile_id.get()
    if ctx is not None:
        return ctx
    override = os.environ.get(_ENV_OVERRIDE, '').strip()
    if override:
        if is_valid_profile_id(override):
            return override
        print(f'WARN: ignoring invalid {_ENV_OVERRIDE}={override!r}; using index active', file=sys.stderr, flush=True)
    if doc is None:
        active = str(load_index().get('active') or DEFAULT_PROFILE_ID)
    else:
        active = str(doc.get('active') or DEFAULT_PROFILE_ID)
    if is_valid_profile_id(active):
        return active
    return DEFAULT_PROFILE_ID

def profile_data_dir(profile_id: str) -> Path:
    pid = normalize_profile_id(profile_id)
    return PROFILES_DIR / pid

def migration_complete_path(profile_id: str=DEFAULT_PROFILE_ID) -> Path:
    return profile_data_dir(profile_id) / MIGRATION_COMPLETE_MARKER

def is_legacy_layout(profile_id: str | None=None) -> bool:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    if pid != DEFAULT_PROFILE_ID:
        return False
    dest = profile_data_dir(DEFAULT_PROFILE_ID)
    if not dest.is_dir():
        return True
    return not migration_complete_path(DEFAULT_PROFILE_ID).is_file()

def profile_root(profile_id: str | None=None) -> Path:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    if is_legacy_layout(pid):
        return ROOT
    return profile_data_dir(pid)

def catalog_path(filename: str, *, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / filename

def itad_path(*, profile_id: str | None=None) -> Path:
    return catalog_path('itad_prices.json', profile_id=profile_id)

def free_claims_path(*, profile_id: str | None=None) -> Path:
    return catalog_path('free_claims.json', profile_id=profile_id)

def sponsors_path(*, profile_id: str | None=None) -> Path:
    return catalog_path('sponsors.json', profile_id=profile_id)

def personal_dir(*, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / 'data'

def personal_path(*, profile_id: str | None=None) -> Path:
    return personal_dir(profile_id=profile_id) / 'personal.json'

def personal_backup_dir(*, profile_id: str | None=None) -> Path:
    return personal_dir(profile_id=profile_id) / 'personal_backups'

def auth_dir(*, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / 'cache' / 'auth'

def profile_cache_dir(*, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / 'cache'

def epic_cache_dir(*, profile_id: str | None=None) -> Path:
    return profile_cache_dir(profile_id=profile_id) / 'epic'

def runs_dir(*, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / 'cache' / 'runs'

def fx_rates_path(*, profile_id: str | None=None) -> Path:
    return profile_root(profile_id) / 'cache' / 'fx_rates.json'
PROFILE_CACHE_JSON_FILES = frozenset({'hltb_map.json', 'steam_review_map.json', 'cross_store_images_meta.json', 'steam_tags_meta.json', 'protondb_map.json', 'fx_rates.json'})

def cache_json_path(filename: str, *, profile_id: str | None=None) -> Path:
    if filename not in PROFILE_CACHE_JSON_FILES:
        raise ValueError(f'unknown profile cache file: {filename!r}')
    return profile_root(profile_id) / 'cache' / filename

def games_backup_root(*, profile_id: str | None=None) -> Path:
    return personal_dir(profile_id=profile_id) / 'games_backups'

def resolve_catalog_path(path: Path, *, profile_id: str | None=None) -> Path:
    if path.is_absolute():
        return path
    name = path.name
    if name.startswith('games_') and name.endswith('.json'):
        return catalog_path(name, profile_id=profile_id)
    if name == 'itad_prices.json':
        return itad_path(profile_id=profile_id)
    if name == 'free_claims.json':
        return free_claims_path(profile_id=profile_id)
    return profile_root(profile_id) / path

def slug_from_label(label: str) -> str:
    base = _SLUG_RE.sub('-', label.strip().lower()).strip('-')
    return base or 'profile'

def list_profiles() -> list[dict[str, Any]]:
    doc = load_index()
    profiles = doc.get('profiles')
    if not isinstance(profiles, list):
        return []
    return [dict(p) for p in profiles if isinstance(p, dict) and p.get('id')]

def profile_label(profile_id: str) -> str:
    for p in list_profiles():
        if p.get('id') == profile_id:
            return str(p.get('label') or profile_id)
    return profile_id

def profile_dir_ids_on_disk() -> set[str]:
    if not PROFILES_DIR.is_dir():
        return set()
    return {child.name for child in PROFILES_DIR.iterdir() if child.is_dir() and is_valid_profile_id(child.name)}

def _label_for_orphan_profile_id(profile_id: str) -> str:
    return profile_id.replace('-', ' ').strip().title() or profile_id

def unique_profile_id_for_doc(label: str, doc: dict[str, Any]) -> str:
    base = slug_from_label(label)
    if not is_valid_profile_id(base):
        base = f'{base}-profile' if base else 'profile'
    indexed = {str(p['id']) for p in doc.get('profiles', []) if isinstance(p, dict) and p.get('id')}
    taken = indexed | profile_dir_ids_on_disk()
    if base not in taken:
        return base
    n = 2
    while f'{base}-{n}' in taken:
        n += 1
    candidate = f'{base}-{n}'
    while not is_valid_profile_id(candidate):
        n += 1
        candidate = f'{base}-{n}'
    return candidate

def reconcile_profile_store(*, adopt_orphans: bool | None=None) -> list[str]:
    if adopt_orphans is None:
        try:
            from shared.supabase_auth import auth_enabled, local_profiles_enabled
            adopt_orphans = not auth_enabled() or local_profiles_enabled()
        except Exception:
            adopt_orphans = True
    notes: list[str] = []
    with _index_lock:
        doc = _load_index_unlocked()
        profiles = doc.get('profiles')
        if not isinstance(profiles, list):
            profiles = []
            doc['profiles'] = profiles
        indexed_ids = {str(p['id']) for p in profiles if isinstance(p, dict) and p.get('id') and is_valid_profile_id(str(p['id']))}
        disk_ids = profile_dir_ids_on_disk()
        orphans = sorted(disk_ids - indexed_ids)
        for pid in orphans:
            msg = f'orphan profile dir not in index: {pid}'
            if adopt_orphans:
                profiles.append({'id': pid, 'label': _label_for_orphan_profile_id(pid), 'created_at': _now_iso()})
                indexed_ids.add(pid)
                msg = f'adopted orphan profile dir into index: {pid}'
            notes.append(msg)
        for pid in sorted(indexed_ids - disk_ids):
            notes.append(f'index entry without profile dir: {pid}')
        active = str(doc.get('active') or DEFAULT_PROFILE_ID)
        if active not in indexed_ids and indexed_ids:
            doc['active'] = sorted(indexed_ids)[0]
            notes.append(f"active profile reset to {doc['active']!r}")
        materialize_index = not INDEX_FILE.is_file() and bool(disk_ids)
        if orphans and adopt_orphans or materialize_index:
            _save_index_unlocked(doc)
            if materialize_index and (not (orphans and adopt_orphans)):
                notes.append('materialized profiles/index.json from on-disk profile dirs')
    return notes

def unique_profile_id(label: str) -> str:
    doc = load_index()
    return unique_profile_id_for_doc(label, doc)