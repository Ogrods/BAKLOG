"""Tray deal alert routes: GET /api/deal-alerts/pending, POST /api/deal-alerts/ack.

Dispatched ahead of ``_require_api_auth`` (like ``/api/shutdown``) because the
tray holds no Supabase bearer. Gate is localhost Host plus ``X-BAKLOG-Local: 1``
on both verbs; Pro is decided with ``is_pro_background()`` via
``deal_alerts.alerts_enabled()``. A failed Pro/opt-in gate answers
``{"enabled": false}`` instead of 403 so the tray quietly idles.
"""

from __future__ import annotations

import json
from http import HTTPStatus

MAX_ACK_BODY = 16 * 1024


def _srv():
    import server

    return server


def _tray_request_ok(handler) -> bool:
    srv = _srv()
    if srv._request_host_is_local(handler) and handler.headers.get(srv._BAKLOG_LOCAL_HEADER) == "1":
        return True
    srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "local requests only"})
    return False


def _alerts_live() -> bool:
    from shared.deal_alerts import alerts_enabled
    from shared.pro_capabilities import capability_registry_status

    return capability_registry_status("deal_watchlist_alerts") == "live" and alerts_enabled()


def handle_deal_alerts_pending_get(handler) -> None:
    if not _tray_request_ok(handler):
        return
    srv = _srv()
    if not _alerts_live():
        srv._send_json(handler, HTTPStatus.OK, {"enabled": False, "alerts": []})
        return
    from shared.deal_alerts import MAX_PENDING, take_pending

    srv._send_json(handler, HTTPStatus.OK, {"enabled": True, "alerts": take_pending(MAX_PENDING)})


def handle_deal_alerts_ack_post(handler) -> None:
    if not _tray_request_ok(handler):
        return
    srv = _srv()
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        length = -1
    if length <= 0 or length > MAX_ACK_BODY:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid body"})
        return
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
        return
    ids = payload.get("ids") if isinstance(payload, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "ids must be a list of strings"})
        return
    from shared.deal_alerts import ack

    srv._send_json(handler, HTTPStatus.OK, {"acked": ack(ids)})
