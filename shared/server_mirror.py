"""Localhost HTTP handlers for GET /api/mirror and POST /api/mirror/{import,sync,clear}."""

from __future__ import annotations

import json
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from shared.cloud_mirror import (
    MirrorProfileMismatch,
    clear_remote_mirror_profile,
    download_remote_mirror_artifact,
    import_remote_mirror_to_profile,
    list_remote_mirror_artifacts,
    list_remote_mirror_profile_ids,
    mirror_read_allowed,
    mirror_upload_allowed,
    read_mirror_upload_state,
    sync_mirror_now,
)


def _srv():
    import server

    return server


def _query(handler):
    parsed = urlparse(handler.path)
    return parse_qs(parsed.query, keep_blank_values=False)


def handle_mirror_get(handler) -> None:
    srv = _srv()
    authorization = handler.headers.get("Authorization") or ""
    from shared.supabase_auth import auth_enabled

    if auth_enabled() and not authorization:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return
    if not mirror_read_allowed(authorization=authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
        return
    qs = _query(handler)
    artifact = (qs.get("path") or [""])[0].strip()
    profile_raw = (qs.get("profile") or [""])[0].strip()
    profile = None
    if profile_raw:
        from shared.profile_paths import normalize_profile_id

        try:
            profile = normalize_profile_id(profile_raw)
        except ValueError:
            srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "Invalid profile id"})
            return
    try:
        if artifact:
            body = download_remote_mirror_artifact(
                authorization=authorization, artifact_path=artifact, profile_id=profile
            )
        else:
            profiles = list_remote_mirror_profile_ids(authorization=authorization)
            list_profile = profile
            if list_profile is None:
                from shared.profile_paths import get_active_profile_id

                list_profile = get_active_profile_id()
            artifacts = list_remote_mirror_artifacts(
                authorization=authorization, profile_id=list_profile
            )
            # Local upload status is always for the active profile (never the ?profile= query).
            local_state = read_mirror_upload_state()
            srv._send_json(
                handler,
                HTTPStatus.OK,
                {
                    "artifacts": artifacts,
                    "profiles": profiles,
                    "profile": list_profile,
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


def handle_mirror_import_post(handler) -> None:
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return
    authorization = handler.headers.get("Authorization") or ""
    from shared.supabase_auth import auth_enabled

    if auth_enabled() and not authorization:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return
    if not mirror_read_allowed(authorization=authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
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
    allow_empty_catalogs = body.get("allowEmptyCatalogs", False)
    if not isinstance(allow_empty_catalogs, bool):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "allowEmptyCatalogs must be boolean"})
        return
    mode_raw = body.get("mode", "overwrite")
    if mode_raw is None:
        mode_raw = "overwrite"
    if not isinstance(mode_raw, str):
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": 'mode must be "overwrite" or "merge"'})
        return
    mode = mode_raw.strip().lower()
    if mode not in {"overwrite", "merge"}:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": 'mode must be "overwrite" or "merge"'})
        return
    paths_raw = body.get("paths")
    paths = None
    if paths_raw is not None:
        if not isinstance(paths_raw, list) or not all(isinstance(item, str) for item in paths_raw):
            srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "paths must be an array of strings"})
            return
        paths = paths_raw
    claimed_profile = body.get("profile")
    profile_id = str(claimed_profile).strip() if claimed_profile is not None else None
    source_raw = body.get("sourceProfile")
    source_profile_id = str(source_raw).strip() if source_raw is not None else None
    if source_raw is not None and not source_profile_id:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "sourceProfile must be a non-empty string"})
        return
    try:
        result = import_remote_mirror_to_profile(
            authorization=authorization,
            profile_id=profile_id,
            source_profile_id=source_profile_id,
            paths=paths,
            include_personal=include_personal,
            allow_empty_catalogs=allow_empty_catalogs,
            mode=mode,
        )
    except MirrorProfileMismatch as exc:
        srv._send_json(handler, HTTPStatus.CONFLICT, {"error": str(exc)})
        return
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


def handle_mirror_clear_post(handler) -> None:
    """POST /api/mirror/clear — delete remote Storage objects + snapshot rows for one profile."""
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return
    authorization = handler.headers.get("Authorization") or ""
    from shared.supabase_auth import auth_enabled

    if auth_enabled() and not authorization:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return
    if not mirror_read_allowed(authorization=authorization):
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Pro plan required"})
        return
    payload, err = srv._read_json_body(handler, max_bytes=4096)
    if err:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": err})
        return
    body = payload if isinstance(payload, dict) else {}
    claimed_profile = body.get("profile")
    profile_id = str(claimed_profile).strip() if claimed_profile is not None else None
    if claimed_profile is not None and not profile_id:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": "profile must be a non-empty string"})
        return
    try:
        result = clear_remote_mirror_profile(authorization=authorization, profile_id=profile_id)
    except PermissionError as exc:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": str(exc)})
        return
    except ValueError as exc:
        srv._send_json(handler, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        srv._api_error(handler, HTTPStatus.BAD_GATEWAY, "mirror_clear_failed", exc)
        return
    srv._send_json(handler, HTTPStatus.OK, result)


def handle_mirror_sync_post(handler) -> None:
    """POST /api/mirror/sync — upload allowlisted local artifacts now (no fetch debounce)."""
    srv = _srv()
    if handler._reject_if_csrf_strict():
        return
    if not srv._require_api_auth(handler):
        return
    authorization = handler.headers.get("Authorization") or ""
    from shared.supabase_auth import auth_enabled

    if auth_enabled() and not authorization:
        srv._send_json(handler, HTTPStatus.UNAUTHORIZED, {"error": "Sign in required"})
        return
    # Refresh JWT plan cache so mirror_upload_allowed sees Pro for this request.
    from shared.entitlement import current_plan

    current_plan(authorization or None)
    if not mirror_upload_allowed():
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": "Cloud sync is not available"})
        return
    try:
        result = sync_mirror_now(authorization=authorization or None)
    except PermissionError as exc:
        srv._send_json(handler, HTTPStatus.FORBIDDEN, {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        srv._api_error(handler, HTTPStatus.BAD_GATEWAY, "mirror_sync_failed", exc)
        return
    srv._send_json(handler, HTTPStatus.OK, result)
