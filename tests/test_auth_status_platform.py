"""Cross-platform guard tests for platform-restricted providers (Amazon).

These run on every OS in CI (Ubuntu + macOS). The key guarantee: on a
non-Windows host, GET /api/auth/status must not import amazon_client (which
raises ImportError off Windows) and Amazon must report as 'unavailable'.
"""
from __future__ import annotations

import json
import sys
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
from auth import manager
from shared import profile_paths
from shared.platform_support import platform_supported


def test_platform_supported_semantics():
    assert platform_supported(()) is True  # empty = all platforms
    assert platform_supported(None) is True
    assert platform_supported((sys.platform,)) is True
    assert platform_supported(("definitely-not-this-os",)) is False


def test_amazon_state_unavailable_off_platform(monkeypatch: pytest.MonkeyPatch):
    """When the OS isn't supported, _provider_state must short-circuit to
    'unavailable' without importing the Windows-only amazon_client."""
    sys.modules.pop("amazon_client", None)
    monkeypatch.setattr(manager, "platform_supported", lambda platforms: False)

    assert manager._provider_state("amazon") == "unavailable"
    assert "amazon_client" not in sys.modules, "amazon_client must not be imported off-platform"


def test_get_status_amazon_carries_platform_metadata():
    rows = {r["key"]: r for r in manager.get_status()}
    amazon = rows["amazon"]
    assert amazon["platforms"] == ["win32"]
    assert amazon["available"] == platform_supported(("win32",))
    # A normal provider has no platform restriction and is always available.
    assert rows["steam"]["available"] is True
    assert rows["steam"]["platforms"] == []


@pytest.fixture()
def auth_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    server._refresh_personal_paths()

    handler = partial(server.Handler, directory=str(server.ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_auth_status_endpoint_ok_and_reports_platform(auth_server: str):
    req = urllib.request.Request(f"{auth_server}/api/auth/status", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        payload = json.loads(resp.read().decode("utf-8"))

    assert status == 200
    assert payload["server_platform"] == sys.platform
    amazon = next(p for p in payload["providers"] if p["key"] == "amazon")
    assert amazon["platforms"] == ["win32"]
    if sys.platform != "win32":
        assert amazon["status"] == "unavailable"
        assert amazon["available"] is False


def test_amazon_fetcher_blocked_off_windows(auth_server: str):
    """POST /api/run/amazon must be refused on non-Windows with a 400."""
    if sys.platform == "win32":
        pytest.skip("Amazon fetcher is allowed on Windows")
    req = urllib.request.Request(f"{auth_server}/api/run/amazon", data=b"", method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = json.loads(exc.read().decode("utf-8"))
        assert "win32" in body.get("error", "")
    assert status == 400
