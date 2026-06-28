from __future__ import annotations
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
MIRROR_BUCKET = 'baklog-mirror'
_STORAGE_TIMEOUT_SEC = 120

def _base_url() -> str:
    from shared.supabase_auth import _supabase_url
    url = _supabase_url()
    if not url:
        raise RuntimeError('Supabase URL not configured')
    return url.rstrip('/')

def _anon_key() -> str:
    from shared.supabase_auth import _anon_key
    key = _anon_key()
    if not key:
        raise RuntimeError('Supabase anon key not configured')
    return key

def mirror_object_key(user_id: str, profile_id: str, artifact_path: str) -> str:
    uid = (user_id or '').strip().strip('/')
    pid = (profile_id or '').strip().strip('/')
    rel = (artifact_path or '').strip().lstrip('/')
    if not uid or not pid or (not rel):
        raise ValueError('invalid mirror object key parts')
    if '..' in rel.split('/'):
        raise ValueError('invalid artifact path')
    return f'{uid}/{pid}/{rel}'

def upload_mirror_object(*, user_id: str, profile_id: str, artifact_path: str, body: bytes, bearer_token: str, content_type: str='application/json') -> dict[str, Any]:
    key = mirror_object_key(user_id, profile_id, artifact_path)
    encoded = '/'.join((urllib.parse.quote(part, safe='') for part in key.split('/')))
    url = f'{_base_url()}/storage/v1/object/{MIRROR_BUCKET}/{encoded}'
    req = urllib.request.Request(url, data=body, method='POST', headers={'apikey': _anon_key(), 'Authorization': f'Bearer {bearer_token}', 'Content-Type': content_type, 'x-upsert': 'true'})
    return _json_request(req)

def download_mirror_object(*, user_id: str, profile_id: str, artifact_path: str, bearer_token: str) -> bytes:
    key = mirror_object_key(user_id, profile_id, artifact_path)
    encoded = '/'.join((urllib.parse.quote(part, safe='') for part in key.split('/')))
    url = f'{_base_url()}/storage/v1/object/{MIRROR_BUCKET}/{encoded}'
    req = urllib.request.Request(url, method='GET', headers={'apikey': _anon_key(), 'Authorization': f'Bearer {bearer_token}'})
    try:
        with urllib.request.urlopen(req, timeout=_STORAGE_TIMEOUT_SEC) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'GET mirror object HTTP {exc.code}: {detail}') from exc
MIRROR_LIST_PAGE_SIZE = 200

def _list_storage_rows(*, prefix: str, bearer_token: str, page_size: int=MIRROR_LIST_PAGE_SIZE) -> list[dict[str, Any]]:
    url = f'{_base_url()}/storage/v1/object/list/{MIRROR_BUCKET}'
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        body = json.dumps({'prefix': prefix, 'limit': page_size, 'offset': offset}).encode('utf-8')
        req = urllib.request.Request(url, data=body, method='POST', headers={'apikey': _anon_key(), 'Authorization': f'Bearer {bearer_token}', 'Content-Type': 'application/json'})
        result = _json_request(req)
        chunk = [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows

def list_mirror_objects(*, user_id: str, profile_id: str, bearer_token: str, limit: int=MIRROR_LIST_PAGE_SIZE) -> list[dict[str, Any]]:
    prefix = f'{user_id.strip()}/{profile_id.strip()}'
    if limit <= 0 or limit >= MIRROR_LIST_PAGE_SIZE:
        return _list_storage_rows(prefix=prefix, bearer_token=bearer_token)
    url = f'{_base_url()}/storage/v1/object/list/{MIRROR_BUCKET}'
    body = json.dumps({'prefix': prefix, 'limit': limit, 'offset': 0}).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={'apikey': _anon_key(), 'Authorization': f'Bearer {bearer_token}', 'Content-Type': 'application/json'})
    result = _json_request(req)
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []

def list_mirror_objects_for_user(*, user_id: str, bearer_token: str) -> list[dict[str, Any]]:
    prefix = f'{user_id.strip()}/'
    return _list_storage_rows(prefix=prefix, bearer_token=bearer_token)

def upsert_mirror_snapshot_row(*, user_id: str, profile_id: str, artifact_path: str, byte_size: int, bearer_token: str) -> None:
    url = f'{_base_url()}/rest/v1/cloud_mirror_snapshots'
    payload = {'user_id': user_id, 'profile_id': profile_id, 'artifact_path': artifact_path, 'byte_size': byte_size}
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, method='POST', headers={'apikey': _anon_key(), 'Authorization': f'Bearer {bearer_token}', 'Content-Type': 'application/json', 'Prefer': 'resolution=merge-duplicates'})
    try:
        _json_request(req)
    except RuntimeError:
        pass

def _json_request(req: urllib.request.Request) -> Any:
    try:
        with urllib.request.urlopen(req, timeout=_STORAGE_TIMEOUT_SEC) as resp:
            raw = resp.read().decode('utf-8')
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(f'{req.method} {req.full_url} HTTP {exc.code}: {detail}') from exc