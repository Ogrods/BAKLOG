"""Profile delete refuses while fetchers are in-flight for that profile."""

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


class _FakeManager:
    def __init__(self, *, blocked: str | None = None) -> None:
        self.blocked = blocked

    def has_runs_for_profile(self, profile_id: str) -> bool:
        return profile_id == self.blocked

    def rebind_profile_paths(self) -> None:
        pass


@pytest.fixture()
def profile_delete_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setattr(server, "ROOT", tmp_path)
    monkeypatch.delenv("BAKLOG_PROFILE", raising=False)

    fake = _FakeManager()
    monkeypatch.setattr(server, "MANAGER", fake)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(tmp_path)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", fake
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _delete_profile(base: str, profile_id: str) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{base}/api/profiles/{profile_id}",
        method="DELETE",
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


def test_delete_profile_blocked_when_runs_in_flight(profile_delete_server) -> None:
    base, fake = profile_delete_server
    create_profile("Work")
    fake.blocked = "work"
    work_dir = profile_paths.profile_data_dir("work")

    status, body = _delete_profile(base, "work")

    assert status == 409
    assert "fetch running or queued" in body.get("error", "")
    assert work_dir.is_dir()


def test_delete_profile_ok_when_no_runs(profile_delete_server) -> None:
    base, fake = profile_delete_server
    create_profile("Work")
    fake.blocked = None
    work_dir = profile_paths.profile_data_dir("work")
    assert work_dir.is_dir()

    status, body = _delete_profile(base, "work")

    assert status == 200
    assert body.get("ok") is True
    assert not work_dir.is_dir()
