"""HTTP handlers for /api/update/* POST routes (keeps server.py lean)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

from shared.install_paths import data_root
from shared.update_manager import get_update_manager
from shared.update_messages import enrich_update_api_payload
from shared.update_snooze import write_dismissed_version


def _mgr(
    *,
    current_version: Callable[[], str],
    has_in_flight_runs: Callable[[], bool],
    has_active_sessions: Callable[[], bool] | None = None,
):
    return get_update_manager(
        current_version=current_version,
        has_in_flight_runs=has_in_flight_runs,
        has_active_sessions=has_active_sessions,
    )


def handle_update_post(
    path: str,
    *,
    current_version: Callable[[], str],
    has_in_flight_runs: Callable[[], bool],
    has_active_sessions: Callable[[], bool] | None = None,
    read_json_body: Callable[[], tuple[dict[str, Any] | None, str | None]],
    send_json: Callable[[HTTPStatus, dict[str, Any]], None],
    trigger_shutdown: Callable[[], None],
) -> None:
    mgr = _mgr(
        current_version=current_version,
        has_in_flight_runs=has_in_flight_runs,
        has_active_sessions=has_active_sessions,
    )
    if path == "/api/update/download":
        payload = enrich_update_api_payload(mgr.start_download())
        status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST
        send_json(status, payload)
        return
    if path == "/api/update/cancel":
        send_json(HTTPStatus.OK, mgr.cancel_download())
        return
    if path == "/api/update/apply":
        payload = enrich_update_api_payload(mgr.apply_ready_update())
        status = HTTPStatus.OK if payload.get("ok") else HTTPStatus.BAD_REQUEST
        send_json(status, payload)
        if payload.get("ok") and payload.get("applying"):
            threading.Thread(
                target=trigger_shutdown,
                name="update-apply-shutdown",
                daemon=True,
            ).start()
        return
    if path == "/api/update/discard-ready":
        send_json(HTTPStatus.OK, mgr.discard_ready_update())
        return
    if path == "/api/update/dismiss":
        body, _err = read_json_body()
        version = str(body.get("version", "")).strip() if isinstance(body, dict) else ""
        if not version:
            send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "version required"})
            return
        write_dismissed_version(data_root(), version)
        send_json(HTTPStatus.OK, {"ok": True, "dismissed_version": version})
        return
    send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})


def handle_update_support_get(
    path: str,
    *,
    current_version: Callable[[], str],
    has_in_flight_runs: Callable[[], bool],
    has_active_sessions: Callable[[], bool] | None = None,
    send_json: Callable[[HTTPStatus, dict[str, Any]], None],
) -> bool:
    """Return True if *path* was handled."""
    from shared.server_support import build_update_check_payload

    mgr = _mgr(
        current_version=current_version,
        has_in_flight_runs=has_in_flight_runs,
        has_active_sessions=has_active_sessions,
    )
    if path == "/api/update/apply-result":
        send_json(HTTPStatus.OK, {"ok": True, "result": mgr.apply_result_dict()})
        return True
    if path == "/api/update-check":
        send_json(
            HTTPStatus.OK,
            build_update_check_payload(
                current_version(),
                fetchers_in_flight=has_in_flight_runs(),
            ),
        )
        return True
    if path == "/api/update/status":
        send_json(HTTPStatus.OK, mgr.status_dict())
        return True
    return False
