from __future__ import annotations
import json
from http import HTTPStatus
from typing import Any
from shared.entitlement import is_pro
from shared.pro_settings import write_pro_settings
from shared.supabase_auth import auth_enabled

def _srv():
    import server
    return server

def handle_pro_settings_put(handler: Any) -> None:
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return
    authorization = handler.headers.get('Authorization')
    if not is_pro(authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {'error': 'Pro plan required'})
        return
    if auth_enabled() and (not authorization):
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {'error': 'Sign in required'})
        return
    try:
        length = int(handler.headers.get('Content-Length') or 0)
    except ValueError:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {'error': 'invalid Content-Length'})
        return
    if length <= 0:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {'error': 'empty body'})
        return
    if length > 4096:
        srv._send_json(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {'error': 'body too large'})
        return
    try:
        raw = handler.rfile.read(length).decode('utf-8')
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {'error': f'invalid JSON: {exc!r}'})
        return
    if not isinstance(payload, dict):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {'error': 'expected JSON object'})
        return
    try:
        doc = write_pro_settings(payload)
    except ValueError as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {'error': str(exc)})
        return
    except OSError as exc:
        srv._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, 'pro_settings_write_failed', exc)
        return
    srv._send_json(handler, HTTPStatus.OK, {'proSettings': doc})