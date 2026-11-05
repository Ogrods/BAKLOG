"""Auth provider HTTP wrappers (extracted from server.py Handler).

Mechanical move only: /api/auth status/open/start/disconnect/cancel/enable/
credentials/master-password/secrets-import. Handler methods stay as thin
delegates so dispatch and tests keep calling server.Handler._handle_auth_*.
"""
from __future__ import annotations

import base64
import json
import sys
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse


def _srv():
    import server

    return server


def handle_auth_status(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    try:
        from auth.manager import get_status
        from auth.secrets import secrets_store_corrupt

        s._send_json(
            handler,
            HTTPStatus.OK,
            {
                "server_platform": sys.platform,
                "providers": get_status(),
                "secrets_corrupt": secrets_store_corrupt(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_status_failed", exc)


def handle_auth_open_url(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        from auth.manager import open_manual_signin

        result = open_manual_signin(provider)
        s._send_json(handler, HTTPStatus.OK, result)
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_open_url_failed", exc)


def handle_auth_start(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        from auth.manager import start_browser_auth

        params = parse_qs(urlparse(handler.path).query)
        fresh = (params.get("fresh") or ["0"])[0].lower() in ("1", "true", "yes")
        session_id = start_browser_auth(provider, fresh=fresh)
        s._send_json(
            handler, HTTPStatus.ACCEPTED, {"session_id": session_id, "provider": provider}
        )
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_start_failed", exc)


def handle_auth_disconnect(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        from auth.manager import disconnect

        disconnect(provider)
        s._send_json(handler, HTTPStatus.OK, {"ok": True})
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_disconnect_failed", exc)


def handle_auth_cancel(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        from auth.manager import cancel_browser_auth

        cancelled = cancel_browser_auth(provider)
        s._send_json(handler, HTTPStatus.OK, {"ok": True, "cancelled": cancelled})
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_cancel_failed", exc)


def handle_auth_enable(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        from auth.manager import enable_local

        enable_local(provider)
        s._send_json(handler, HTTPStatus.OK, {"ok": True})
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "auth_enable_failed", exc)


def handle_auth_credentials(handler: SimpleHTTPRequestHandler, provider: str) -> None:
    s = _srv()
    try:
        length = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid Content-Length"})
        return
    if length <= 0 or length > 65536:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "invalid body size"})
        return
    try:
        raw = handler.rfile.read(length).decode("utf-8")
        payload: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": f"invalid JSON: {exc!r}"})
        return
    try:
        from auth.manager import set_form_credentials

        fields = payload.get("fields") if isinstance(payload, dict) else payload
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
        result = set_form_credentials(provider, fields)
        s._send_json(handler, HTTPStatus.OK, result)
    except KeyError:
        s._send_json(handler, HTTPStatus.NOT_FOUND, {"error": f"unknown provider: {provider}"})
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "credentials_failed", exc)


def handle_auth_master_password(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    payload, err = s._read_json_body(handler, max_bytes=s._AUTH_JSON_MAX_BYTES)
    if err == "empty body":
        payload = {}
    elif err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    try:
        from auth.manager import set_master_password

        set_master_password(payload.get("password"))
        s._send_json(handler, HTTPStatus.OK, {"ok": True})
    except ValueError as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "master_password_failed", exc)


def handle_auth_secrets_import(handler: SimpleHTTPRequestHandler) -> None:
    s = _srv()
    # JSON-only: {"passphrase": str, "blob": base64}. The legacy
    # octet-stream + ?passphrase= query-string fallback is removed - a
    # passphrase in the URL leaks into request logs / browser history.
    payload, err = s._read_json_body(handler, max_bytes=s._SECRETS_IMPORT_MAX_BYTES)
    if err:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    assert payload is not None
    try:
        passphrase = str(payload.get("passphrase") or "")
        blob_b64 = payload.get("blob")
        if isinstance(blob_b64, str):
            try:
                # binascii.Error subclasses ValueError, so this catch covers
                # malformed base64 too.
                blob = base64.b64decode(blob_b64, validate=True)
            except ValueError as exc:
                raise ValueError("blob is not valid base64") from exc
        else:
            blob = b""
        from auth.bundle import (
            BadMagic,
            BadPassphrase,
            BundleTooLarge,
            UnsupportedVersion,
            import_bundle,
        )

        summary = import_bundle(blob, passphrase, dry_run=False)
        s._send_json(handler, HTTPStatus.OK, summary.as_dict())
    except BadPassphrase as exc:
        s._send_json(handler, HTTPStatus.FORBIDDEN, {"error": str(exc), "code": "bad_passphrase"})
    except BadMagic as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "bad_magic"})
    except UnsupportedVersion as exc:
        s._send_json(
            handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "unsupported_version"}
        )
    except BundleTooLarge as exc:
        s._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "too_large"})
    except ValueError as exc:
        s._send_json(
            handler, HTTPStatus.BAD_REQUEST, {"error": str(exc), "code": "invalid_passphrase"}
        )
    except Exception as exc:  # noqa: BLE001
        s._api_error(handler, HTTPStatus.INTERNAL_SERVER_ERROR, "import_failed", exc)
