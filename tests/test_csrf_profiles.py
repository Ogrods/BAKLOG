"""Strict CSRF on profile mutation routes."""

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


@pytest.fixture()
def csrf_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post_origin_only(base: str, path: str, body: dict) -> tuple[int, dict]:
    """Simulate a cross-site POST that passes loose CSRF via Origin but not strict header."""
    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": "http://127.0.0.1:8765",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def test_profile_create_rejects_origin_without_local_header(csrf_server: str) -> None:
    status, body = _post_origin_only(csrf_server, "/api/profiles", {"label": "Work"})
    assert status == 403
    assert "cross-origin" in body.get("error", "").lower()


def test_profile_switch_accepts_local_header(csrf_server: str) -> None:
    req = urllib.request.Request(
        f"{csrf_server}/api/profiles/active",
        data=json.dumps({"id": "default"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
