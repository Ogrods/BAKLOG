import json
from http import HTTPStatus

from shared.entitlement import pro_features_unlocked
from shared.pro_settings import write_pro_settings
from shared.supabase_auth import auth_enabled


def _srv():
    import server

    return server


def handle_pro_settings_put(handler):
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return
    authorization = handler.headers.get("Authorization")
    if auth_enabled() and (not authorization):
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return
    if not pro_features_unlocked(authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
        return
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
        return
    if length <= 0:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "empty body"})
        return
    if length > 4096:
        srv._send_json(handler, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
        return
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc!r}"})
        return
    if not isinstance(payload, dict):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "expected JSON object"})
        return
    if "cloudMirrorEnabled" in payload and not isinstance(payload.get("cloudMirrorEnabled"), bool):
        srv._send_json(
            handler,
            HTTPStatus.BAD_REQUEST,
            {"error": "cloudMirrorEnabled must be boolean"},
        )
        return
    if payload.get("cloudMirrorEnabled") is True:
        from shared.pro_capabilities import capability_registry_status

        if capability_registry_status("cloud_sync_mirror") != "live":
            srv._send_json(
                handler,
                HTTPStatus.FORBIDDEN,
                {"error": "Cloud sync is not available yet"},
            )
            return
    try:
        doc = write_pro_settings(payload)
    except ValueError as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return
    except OSError as exc:
        srv._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "pro_settings_write_failed", exc)
        return
    srv._send_json(handler, HTTPStatus.OK, {"proSettings": doc})
