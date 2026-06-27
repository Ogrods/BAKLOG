"""GET /api/mirror — list and download Pro cloud mirror artifacts."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from shared.cloud_mirror import (
    download_remote_mirror_artifact,
    import_remote_mirror_to_profile,
    list_remote_mirror_artifacts,
    mirror_read_allowed,
    read_mirror_upload_state,
)


def _srv():
    import server

    return server


def _query(handler: Any) -> dict[str, list[str]]:
    parsed = urlparse(handler.path)
    return parse_qs(parsed.query, keep_blank_values=False)


def handle_mirror_get(handler: Any) -> None:
    srv = _srv()
    authorization = handler.headers.get("Authorization") or ""
    if not mirror_read_allowed(authorization=authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
        return

    qs = _query(handler)
    artifact = (qs.get("path") or [""])[0].strip()
    profile = (qs.get("profile") or [""])[0].strip() or None

    try:
        if artifact:
            body = download_remote_mirror_artifact(
                authorization=authorization,
                artifact_path=artifact,
                profile_id=profile,
            )
        else:
            artifacts = list_remote_mirror_artifacts(
                authorization=authorization,
                profile_id=profile,
            )
            local_state = read_mirror_upload_state(profile_id=profile)
            srv._send_json(
                handler,
                HTTPStatus.OK,
                {
                    "artifacts": artifacts,
                    "localUploadState": local_state,
                },
            )
            return
    except PermissionError as exc:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        return
    except ValueError as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        srv._api_error(handler, HTTPStatus.BAD_GATEWAY, "mirror_read_failed", exc)
        return

    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        srv._send_json(handler, HTTPStatus.OK, {"raw": body.decode("utf-8", errors="replace")})
        return
    srv._send_json(handler, HTTPStatus.OK, doc)


def handle_mirror_import_post(handler: Any) -> None:
    """POST /api/mirror/import — pull cloud mirror artifacts into the local profile."""
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return

    authorization = handler.headers.get("Authorization") or ""
    if not mirror_read_allowed(authorization=authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
        return

    from shared.supabase_auth import auth_enabled

    if auth_enabled() and not authorization:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return

    payload, err = srv._read_json_body(handler, max_bytes=4096)
    if err:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    body = payload if isinstance(payload, dict) else {}

    include_personal = body.get("includePersonal", True)
    if not isinstance(include_personal, bool):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "includePersonal must be boolean"})
        return

    paths_raw = body.get("paths")
    paths: list[str] | None = None
    if paths_raw is not None:
        if not isinstance(paths_raw, list) or not all(isinstance(item, str) for item in paths_raw):
            srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "paths must be an array of strings"})
            return
        paths = paths_raw

    try:
        result = import_remote_mirror_to_profile(
            authorization=authorization,
            paths=paths,
            include_personal=include_personal,
        )
    except PermissionError as exc:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        return
    except ValueError as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        srv._api_error(handler, HTTPStatus.BAD_GATEWAY, "mirror_import_failed", exc)
        return

    srv._send_json(handler, HTTPStatus.OK, result)
