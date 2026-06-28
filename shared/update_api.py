import threading
from http import HTTPStatus

from shared.install_paths import data_root
from shared.update_manager import get_update_manager
from shared.update_messages import enrich_update_api_payload
from shared.update_snooze import write_dismissed_version


def _mgr(*, current_version, has_in_flight_runs, has_active_sessions=None):
    return get_update_manager(
        current_version=current_version, has_in_flight_runs=has_in_flight_runs, has_active_sessions=has_active_sessions
    )


def handle_update_post(
    path, *, current_version, has_in_flight_runs, has_active_sessions=None, read_json_body, send_json, trigger_shutdown
):
    mgr = _mgr(
        current_version=current_version, has_in_flight_runs=has_in_flight_runs, has_active_sessions=has_active_sessions
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
            threading.Thread(target=trigger_shutdown, name="update-apply-shutdown", daemon=True).start()
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


def handle_update_support_get(path, *, current_version, has_in_flight_runs, has_active_sessions=None, send_json):
    from shared.server_support import build_update_check_payload

    mgr = _mgr(
        current_version=current_version, has_in_flight_runs=has_in_flight_runs, has_active_sessions=has_active_sessions
    )
    if path == "/api/update/apply-result":
        send_json(HTTPStatus.OK, {"ok": True, "result": mgr.apply_result_dict()})
        return True
    if path == "/api/update-check":
        sign_in_active = has_active_sessions() if has_active_sessions else False
        send_json(
            HTTPStatus.OK,
            build_update_check_payload(
                current_version(), fetchers_in_flight=has_in_flight_runs(), sign_in_active=sign_in_active
            ),
        )
        return True
    if path == "/api/update/status":
        send_json(HTTPStatus.OK, mgr.status_dict())
        return True
    return False
