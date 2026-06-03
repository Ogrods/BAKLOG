"""Switching active profile cancels in-flight fetchers before rebinding paths."""

from __future__ import annotations

import json
import threading
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from shared import profile_paths
from shared.profiles import create_profile


class _FakeManager:
    """Records the ordering of cancel_all vs rebind so we can assert switch safety
    without launching a real (slow, flaky-on-Windows) fetcher subprocess."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def cancel_all(self) -> list[dict]:
        self.calls.append("cancel_all")
        return [{"id": "stub", "key": "demo", "status": "cancelled"}]

    def rebind_profile_paths(self) -> None:
        self.calls.append("rebind")


@pytest.fixture()
def switch_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setattr(server, "ROOT", tmp_path)

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


def _post_json(base: str, path: str, body: dict) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_profile_switch_cancels_runs_before_rebind(switch_server) -> None:
    base, fake = switch_server
    create_profile("Work")

    status, body = _post_json(base, "/api/profiles/active", {"id": "work"})

    assert status == 200
    assert body.get("active") == "work"
    # cancel_all must run before paths rebind so a still-running fetcher can't
    # write into the newly-activated profile's run files.
    assert fake.calls == ["cancel_all", "rebind"]
