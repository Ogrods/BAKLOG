"""Profile switch is blocked while a browser sign-in session is active."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from shared import profile_paths
from shared.profiles import create_profile


@pytest.fixture()
def switch_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setattr(server, "ROOT", tmp_path)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(tmp_path)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post_json(base: str, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={
            "Content-Type": "application/json",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        method="POST",
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


def test_profile_switch_returns_409_during_auth(switch_server, monkeypatch: pytest.MonkeyPatch) -> None:
    base = switch_server
    create_profile("Work")
    monkeypatch.setattr("auth.manager.has_active_sessions", lambda: True)

    status, body = _post_json(base, "/api/profiles/active", {"id": "work"})

    assert status == 409
    assert "sign-in" in str(body.get("error", "")).lower()
