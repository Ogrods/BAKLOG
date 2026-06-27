"""HTTP handlers for /api/update/* POST routes (keeps server.py lean)."""

from __future__ import annotations

import threading
from http import HTTPStatus
from typing import Any, Callable

from shared.install_paths import data_root
from shared.update_manager import get_update_manager
from shared.update_messages import enrich_update_api_payload
from shared.update_snooze import write_dismissed_version


def handle_update_post(
    path: str,
    *,
    current_version: Callable[[], str],
    has_in_flight_runs: Callable[[], bool],
    read_json_body: Callable[[], tuple[dict[str, Any] | None, str | None]],
    send_json: Callable[[HTTPStatus, dict[str, Any]], None],
    trigger_shutdown: Callable[[], None],
) -> None:
    mgr = get_update_manager(
        current_version=current_version,
        has_in_flight_runs=has_in_flight_runs,
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
