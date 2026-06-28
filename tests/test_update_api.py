from http import HTTPStatus
from unittest.mock import MagicMock

from shared.update_api import handle_update_post


def test_handle_update_post_download_humanizes_error(monkeypatch):
    mgr = MagicMock()
    mgr.start_download.return_value = {"ok": False, "error": "Wait for running fetchers to finish before updating"}
    monkeypatch.setattr("shared.update_api.get_update_manager", lambda **_: mgr)
    sent = []
    handle_update_post(
        "/api/update/download",
        current_version=lambda: "0.8.25",
        has_in_flight_runs=lambda: True,
        read_json_body=lambda: ({}, None),
        send_json=lambda status, payload: sent.append((status, payload)),
        trigger_shutdown=lambda: None,
    )
    assert sent[0][0] == HTTPStatus.BAD_REQUEST
    assert sent[0][1]["error_code"] == "fetchers_running"
    assert "Fetcher health" in sent[0][1]["error"]


def test_handle_update_post_dismiss_requires_version(monkeypatch):
    sent = []
    handle_update_post(
        "/api/update/dismiss",
        current_version=lambda: "0.8.25",
        has_in_flight_runs=lambda: False,
        read_json_body=lambda: ({}, None),
        send_json=lambda status, payload: sent.append((status, payload)),
        trigger_shutdown=lambda: None,
    )
    assert sent[0][0] == HTTPStatus.BAD_REQUEST
