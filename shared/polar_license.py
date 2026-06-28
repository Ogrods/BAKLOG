from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
_VALIDATE_PATH = '/v1/customer-portal/license-keys/validate'
_GRANTED = frozenset({'granted'})

def polar_configured() -> bool:
    return bool(os.environ.get('BAKLOG_POLAR_ORG_ID', '').strip())

def polar_org_id() -> str:
    return os.environ.get('BAKLOG_POLAR_ORG_ID', '').strip()

def polar_api_base() -> str:
    return os.environ.get('BAKLOG_POLAR_API_BASE', 'https://api.polar.sh').rstrip('/')

def validate_license_key(key: str) -> dict:
    org_id = polar_org_id()
    cleaned = (key or '').strip()
    if not org_id:
        return {'ok': False, 'status': None, 'error': 'Polar org id not configured'}
    if not cleaned:
        return {'ok': False, 'status': None, 'error': 'License key is required'}
    payload = json.dumps({'key': cleaned, 'organization_id': org_id}).encode('utf-8')
    url = f'{polar_api_base()}{_VALIDATE_PATH}'
    req = urllib.request.Request(url, data=payload, method='POST', headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {'ok': False, 'status': None, 'error': 'License key not found'}
        detail = exc.read().decode('utf-8', errors='replace')[:200]
        return {'ok': False, 'status': None, 'error': detail or f'Polar HTTP {exc.code}'}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {'ok': False, 'status': None, 'error': f'Could not reach Polar ({exc})'}
    if not isinstance(body, dict):
        return {'ok': False, 'status': None, 'error': 'Unexpected Polar response'}
    status = body.get('status')
    status_norm = status.strip().lower() if isinstance(status, str) else ''
    if status_norm in _GRANTED:
        return {'ok': True, 'status': status_norm, 'error': None}
    if status_norm:
        return {'ok': False, 'status': status_norm, 'error': f'License key is {status_norm}'}
    return {'ok': False, 'status': None, 'error': 'License key is not active'}