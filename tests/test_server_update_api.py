"""HTTP security tests for in-app update API routes."""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import pytest

import server
from shared import profile_paths


@pytest.fixture()
def update_api_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()

    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    monkeypatch.setattr(server, "MANAGER", server.RunManager(runs_dir=runs_dir))

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.MANAGER.shutdown()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post(
    base: str,
    path: str,
    *,
    origin: str | None = None,
    local_header: bool = False,
) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if local_header:
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    req = urllib.request.Request(
        f"{base}{path}",
        method="POST",
        headers=headers,
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return exc.code, parsed


def _get(base: str, path: str) -> tuple[int, dict]:
    import urllib.request

    with urllib.request.urlopen(f"{base}{path}", timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_update_download_cross_origin_blocked(update_api_server: str) -> None:
    status, body = _post(update_api_server, "/api/update/download", origin="https://evil.example")
    assert status == 403
    assert "cross-origin" in body.get("error", "").lower()


def test_update_download_requires_local_header(update_api_server: str) -> None:
    status, body = _post(update_api_server, "/api/update/download", origin=update_api_server)
    assert status == 403


def test_update_download_blocked_when_not_frozen(update_api_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.update_manager.is_frozen", lambda: False)
    status, body = _post(update_api_server, "/api/update/download", local_header=True)
    assert status == 400
    assert body.get("ok") is False


def test_update_status_is_public_read(update_api_server: str) -> None:
    status, body = _get(update_api_server, "/api/update/status")
    assert status == 200
    assert body.get("phase") == "idle"


def test_update_check_includes_download_metadata(
    update_api_server: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_release = {
        "tag_name": "v9.9.9",
        "html_url": "https://github.com/Ogrods/BAKLOG/releases/tag/v9.9.9",
        "assets": [
            {
                "name": "BAKLOG-win64.zip",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v9.9.9/BAKLOG-win64.zip",
            },
            {
                "name": "BAKLOG-win64.sha256",
                "browser_download_url": "https://github.com/Ogrods/BAKLOG/releases/download/v9.9.9/BAKLOG-win64.sha256",
            },
        ],
    }
    with patch("shared.server_support.fetch_latest_github_release", return_value=fake_release):
        with patch("shared.update_release._fetch_text_asset", return_value="a" * 64 + "  BAKLOG-win64.zip"):
            status, body = _get(update_api_server, "/api/update-check")
    assert status == 200
    assert body.get("download_url", "").endswith("BAKLOG-win64.zip")
    assert body.get("sha256") == "a" * 64
