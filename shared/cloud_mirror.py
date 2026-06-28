from __future__ import annotations
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any
from shared.entitlement import is_pro_background
from shared.mirror_session import get_mirror_session
from shared.pro_settings import read_pro_settings
from shared.profile_paths import get_active_profile_id, profile_root, runs_dir
DEBOUNCE_SEC = 30.0
_FLUSH_POLL_SEC = 5.0
_lock = threading.Lock()
_pending: dict[str, dict[str, Any]] = {}
_worker_started = False

def start_flush_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
    thread = threading.Thread(target=_flush_loop, name='cloud-mirror-flush', daemon=True)
    thread.start()

def _flush_loop() -> None:
    while True:
        time.sleep(_FLUSH_POLL_SEC)
        try:
            maybe_flush_mirror_uploads()
        except Exception as exc:
            if os.environ.get('BAKLOG_DEBUG'):
                print(f'[cloud_mirror] flush loop error: {exc!r}', file=sys.stderr)

def mirrorable_relative_path(path: Path, *, profile_id: str | None=None) -> str | None:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    root = profile_root(profile_id=pid).resolve()
    try:
        resolved = path.resolve()
        rel = resolved.relative_to(root)
    except (ValueError, OSError):
        return None
    rel_posix = rel.as_posix()
    if _is_denied_relative(rel_posix):
        return None
    if _is_allowed_relative(rel_posix):
        return rel_posix
    return None

def _is_denied_relative(rel_posix: str) -> bool:
    lower = rel_posix.lower()
    if lower.startswith('cache/') or '/cache/' in lower:
        return True
    if lower.startswith('auth/') or '/auth/' in lower:
        return True
    if lower.endswith('secrets.bin') or lower.endswith('.env'):
        return True
    if lower.endswith('pro_settings.json'):
        return True
    return False

def _is_allowed_relative(rel_posix: str) -> bool:
    name = Path(rel_posix).name
    if rel_posix == 'data/personal.json':
        return True
    if name in ('itad_prices.json', 'free_claims.json'):
        return True
    if name.startswith('games_wishlist_') and name.endswith('.json'):
        return True
    if name.startswith('games_') and name.endswith('.json'):
        return True
    return False

def mirror_upload_allowed(*, profile_id: str | None=None) -> bool:
    if not is_pro_background():
        return False
    settings = read_pro_settings(profile_id=profile_id)
    if not settings.get('cloudMirrorEnabled'):
        return False
    return True

def mirror_read_allowed(*, authorization: str | None) -> bool:
    from shared.entitlement import is_pro
    from shared.supabase_auth import auth_enabled
    if not auth_enabled():
        return False
    return is_pro(authorization)

def schedule_mirror_upload(path: Path, *, profile_id: str | None=None) -> None:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    rel = mirrorable_relative_path(path, profile_id=pid)
    if rel is None:
        return
    now = time.time()
    with _lock:
        entry = _pending.setdefault(pid, {'paths': set(), 'flush_at': now + DEBOUNCE_SEC})
        paths = entry['paths']
        if not isinstance(paths, set):
            paths = set(paths)
            entry['paths'] = paths
        paths.add(rel)
        entry['flush_at'] = now + DEBOUNCE_SEC

def maybe_flush_mirror_uploads(*, force: bool=False) -> None:
    now = time.time()
    due: list[tuple[str, set[str]]] = []
    with _lock:
        for pid, entry in list(_pending.items()):
            flush_at = float(entry.get('flush_at') or 0)
            paths = entry.get('paths') or set()
            if not paths:
                _pending.pop(pid, None)
                continue
            if force or now >= flush_at:
                due.append((pid, set(paths)))
                _pending.pop(pid, None)
    for pid, paths in due:
        _flush_profile_uploads(pid, paths)

def _mirror_state_path(profile_id: str) -> Path:
    return runs_dir(profile_id=profile_id) / 'mirror_upload_state.json'

def read_mirror_upload_state(*, profile_id: str | None=None) -> dict[str, Any]:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    try:
        doc = json.loads(_mirror_state_path(pid).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {'artifacts': {}, 'last_upload_at': None}
    if not isinstance(doc, dict):
        return {'artifacts': {}, 'last_upload_at': None}
    artifacts = doc.get('artifacts')
    if not isinstance(artifacts, dict):
        artifacts = {}
    return {'artifacts': artifacts, 'last_upload_at': doc.get('last_upload_at')}

def _save_mirror_upload_state(profile_id: str, uploaded: dict[str, str]) -> None:
    if not uploaded:
        return
    path = _mirror_state_path(profile_id)
    state = read_mirror_upload_state(profile_id=profile_id)
    artifacts = dict(state.get('artifacts') or {})
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    for rel, status in uploaded.items():
        artifacts[rel] = {'status': status, 'uploaded_at': now}
    doc = {'artifacts': artifacts, 'last_upload_at': now}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
    except OSError:
        pass

def _flush_profile_uploads(profile_id: str, paths: set[str]) -> None:
    if not mirror_upload_allowed(profile_id=profile_id):
        return
    from shared.supabase_auth import auth_enabled
    if not auth_enabled():
        return
    session = get_mirror_session()
    if session is None:
        if os.environ.get('BAKLOG_DEBUG'):
            print('[cloud_mirror] skip upload: no cached bearer session', file=sys.stderr)
        return
    user_id, bearer = session
    from shared.supabase_mirror import upload_mirror_object, upsert_mirror_snapshot_row
    root = profile_root(profile_id=profile_id)
    uploaded: dict[str, str] = {}
    errors: list[str] = []
    for rel in sorted(paths):
        file_path = root / rel
        try:
            body = file_path.read_bytes()
        except OSError as exc:
            errors.append(f'{rel}: read failed ({exc})')
            continue
        try:
            upload_mirror_object(user_id=user_id, profile_id=profile_id, artifact_path=rel, body=body, bearer_token=bearer)
            upsert_mirror_snapshot_row(user_id=user_id, profile_id=profile_id, artifact_path=rel, byte_size=len(body), bearer_token=bearer)
            uploaded[rel] = 'ok'
        except Exception as exc:
            errors.append(f'{rel}: {exc}')
            uploaded[rel] = 'error'
    _save_mirror_upload_state(profile_id, uploaded)
    if os.environ.get('BAKLOG_DEBUG'):
        payload = {'profile_id': profile_id, 'uploaded': sorted(uploaded.keys()), 'errors': errors}
        print(f'[cloud_mirror] upload flush: {json.dumps(payload)}', file=sys.stderr, flush=True)

def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0

def list_remote_mirror_artifacts(*, authorization: str, profile_id: str | None=None) -> list[dict[str, Any]]:
    snap = list_remote_mirror_snapshot(authorization=authorization, profile_id=profile_id)
    return snap.get('artifacts') or []

def list_remote_mirror_snapshot(*, authorization: str, profile_id: str | None=None) -> dict[str, Any]:
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import list_mirror_objects, list_mirror_objects_for_user
    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError('invalid session')
    user_id = str(user.get('id') or '')
    token = _bearer_token(authorization)
    if profile_id is not None:
        from shared.profile_paths import normalize_profile_id
        pid = normalize_profile_id(profile_id)
        rows = list_mirror_objects(user_id=user_id, profile_id=pid, bearer_token=token)
        artifacts = _storage_rows_to_artifacts(rows, profile_id=pid)
        return {'artifacts': artifacts, 'profiles': [pid]}
    rows = list_mirror_objects_for_user(user_id=user_id, bearer_token=token)
    artifacts, profiles = _parse_multi_profile_storage_rows(rows)
    return {'artifacts': artifacts, 'profiles': profiles}

def _storage_rows_to_artifacts(rows: list[dict[str, Any]], *, profile_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get('name') or '').strip().lstrip('/')
        if not name or name.endswith('/'):
            continue
        if not _is_allowed_relative(name):
            continue
        out.append({'path': name, 'profile': profile_id, 'id': row.get('id'), 'updated_at': row.get('updated_at'), 'metadata': row.get('metadata')})
    out.sort(key=lambda item: (item.get('profile') or '', item.get('path') or ''))
    return out

def _parse_multi_profile_storage_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    from shared.profile_paths import normalize_profile_id
    artifacts: list[dict[str, Any]] = []
    profiles: set[str] = set()
    for row in rows:
        name = str(row.get('name') or '').strip().lstrip('/')
        if not name or name.endswith('/') or '/' not in name:
            continue
        slash = name.index('/')
        profile_id = name[:slash]
        artifact_path = name[slash + 1:]
        try:
            normalize_profile_id(profile_id)
        except ValueError:
            continue
        if not _is_allowed_relative(artifact_path):
            continue
        profiles.add(profile_id)
        artifacts.append({'path': artifact_path, 'profile': profile_id, 'id': row.get('id'), 'updated_at': row.get('updated_at'), 'metadata': row.get('metadata')})
    artifacts.sort(key=lambda item: (item.get('profile') or '', item.get('path') or ''))
    return (artifacts, sorted(profiles))

def download_remote_mirror_artifact(*, authorization: str, artifact_path: str, profile_id: str | None=None) -> bytes:
    from shared.supabase_auth import verify_bearer_user
    from shared.supabase_mirror import download_mirror_object
    rel = mirrorable_relative_path(profile_root(profile_id=profile_id or get_active_profile_id()) / artifact_path, profile_id=profile_id)
    if rel is None:
        raise ValueError('artifact not allowed')
    user = verify_bearer_user(authorization)
    if not user:
        raise PermissionError('invalid session')
    user_id = str(user.get('id') or '')
    if profile_id is not None:
        from shared.profile_paths import normalize_profile_id
        pid = normalize_profile_id(profile_id)
    else:
        pid = get_active_profile_id()
    token = _bearer_token(authorization)
    return download_mirror_object(user_id=user_id, profile_id=pid, artifact_path=rel, bearer_token=token)

def _bearer_token(authorization: str) -> str:
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != 'bearer':
        raise PermissionError('missing bearer token')
    token = parts[1].strip()
    if not token:
        raise PermissionError('missing bearer token')
    return token

def _parse_mirror_json(body: bytes, artifact_path: str) -> Any:
    try:
        return json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'{artifact_path}: invalid JSON') from exc

def _validate_mirror_staged_doc(rel: str, doc: Any, *, allow_empty_catalogs: bool) -> None:
    from shared.server_catalog_import import is_allowed_catalog_filename, validate_catalog_doc
    if rel == 'data/personal.json':
        if not isinstance(doc, dict):
            raise ValueError(f'{rel}: must be a JSON object')
        return
    if rel == 'free_claims.json':
        if not isinstance(doc, dict):
            raise ValueError(f'{rel}: must be a JSON object')
        return
    if is_allowed_catalog_filename(rel):
        validate_catalog_doc(rel, doc)
        if allow_empty_catalogs or rel == 'itad_prices.json':
            return
        if rel.startswith('games_'):
            games = doc.get('games')
            if isinstance(games, list) and len(games) == 0:
                raise ValueError(f'{rel}: empty games list refused')

def _mirror_artifact_write_path(rel: str, *, profile_id: str) -> Path:
    from shared.profile_paths import catalog_path, personal_path
    if rel == 'data/personal.json':
        return personal_path(profile_id=profile_id)
    if rel == 'free_claims.json':
        return catalog_path('free_claims.json', profile_id=profile_id)
    from shared.server_catalog_import import is_allowed_catalog_filename
    if is_allowed_catalog_filename(rel):
        return catalog_path(rel, profile_id=profile_id)
    raise ValueError(f'unsupported mirror artifact: {rel}')

def import_remote_mirror_to_profile(*, authorization: str, profile_id: str | None=None, paths: list[str] | None=None, include_personal: bool=True, allow_empty_catalogs: bool=False) -> dict[str, Any]:
    from shared.profile_paths import get_active_profile_id
    from shared.safe_write import safe_write_text
    from shared.server_catalog_import import import_catalog_payload, is_allowed_catalog_filename
    from shared.server_personal import save_personal_doc
    pid = profile_id if profile_id is not None else get_active_profile_id()
    remote_rows = list_remote_mirror_artifacts(authorization=authorization, profile_id=pid)
    remote_paths = {str(row.get('path') or '').strip() for row in remote_rows}
    remote_paths.discard('')
    candidates: list[str] = []
    for path in sorted(remote_paths):
        rel = mirrorable_relative_path(profile_root(profile_id=pid) / path, profile_id=pid)
        if rel is None:
            continue
        if rel == 'data/personal.json' and (not include_personal):
            continue
        candidates.append(rel)
    if paths is not None:
        wanted = {str(item).strip().lstrip('/') for item in paths if str(item).strip()}
        candidates = [rel for rel in candidates if rel in wanted]
    if not candidates:
        raise ValueError('no importable mirror artifacts')
    staged: dict[str, Any] = {}
    for rel in candidates:
        body = download_remote_mirror_artifact(authorization=authorization, artifact_path=rel, profile_id=pid)
        doc = _parse_mirror_json(body, rel)
        _validate_mirror_staged_doc(rel, doc, allow_empty_catalogs=allow_empty_catalogs)
        staged[rel] = doc
    write_paths = [_mirror_artifact_write_path(rel, profile_id=pid) for rel in staged]
    backups: dict[Path, bytes | None] = {}
    for path in write_paths:
        try:
            backups[path] = path.read_bytes() if path.is_file() else None
        except OSError:
            backups[path] = None
    imported: list[str] = []
    personal_saved = False
    try:
        catalogs: dict[str, Any] = {}
        for rel, doc in staged.items():
            if rel == 'data/personal.json':
                save_personal_doc(doc, allow_empty=False)
                imported.append(rel)
                personal_saved = True
                continue
            if rel == 'free_claims.json':
                dest = _mirror_artifact_write_path(rel, profile_id=pid)
                safe_write_text(dest, json.dumps(doc, ensure_ascii=False, indent=2) + '\n')
                imported.append(rel)
                continue
            if is_allowed_catalog_filename(rel):
                catalogs[rel] = doc
        if catalogs:
            batch = import_catalog_payload({'catalogs': catalogs, 'profile': pid})
            imported.extend(batch.get('imported') or [])
    except Exception:
        for path, prior in backups.items():
            try:
                if prior is None:
                    if path.is_file():
                        path.unlink()
                else:
                    path.write_bytes(prior)
            except OSError:
                pass
        raise
    seen: set[str] = set()
    ordered: list[str] = []
    for name in imported:
        if name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return {'ok': True, 'imported': ordered, 'count': len(ordered), 'personal': personal_saved}