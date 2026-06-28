import json
import sys
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

import server
from auth import manager
from shared import profile_paths
from shared.platform_support import platform_supported


def test_platform_supported_semantics():
    assert platform_supported(()) is True
    assert platform_supported(None) is True
    assert platform_supported((sys.platform,)) is True
    assert platform_supported(("definitely-not-this-os",)) is False


def test_amazon_state_unavailable_off_platform(monkeypatch):
    sys.modules.pop("clients.amazon_client", None)
    monkeypatch.setattr(manager, "platform_supported", lambda platforms: False)
    assert manager._provider_state("amazon") == "unavailable"
    assert "amazon_client" not in sys.modules, "amazon_client must not be imported off-platform"


def test_get_status_amazon_carries_platform_metadata():
    rows = {r["key"]: r for r in manager.get_status()}
    amazon = rows["amazon"]
    assert amazon["platforms"] == ["win32"]
    assert amazon["available"] == platform_supported(("win32",))
    assert rows["steam"]["available"] is True
    assert rows["steam"]["platforms"] == []


@pytest.fixture()
def auth_server(tmp_path, monkeypatch):
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


def test_auth_status_endpoint_ok_and_reports_platform(auth_server):
    req = urllib.request.Request(f"{auth_server}/api/auth/status", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
        payload = json.loads(resp.read().decode("utf-8"))
    assert status == 200
    assert payload["server_platform"] == sys.platform
    amazon = next((p for p in payload["providers"] if p["key"] == "amazon"))
    assert amazon["platforms"] == ["win32"]
    if sys.platform != "win32":
        assert amazon["status"] == "unavailable"
        assert amazon["available"] is False


def test_amazon_fetcher_allowed_off_windows(auth_server):
    if sys.platform == "win32":
        pytest.skip("covered by launcher path on Windows")
    req = urllib.request.Request(
        f"{auth_server}/api/run/amazon", data=b"", method="POST", headers={server._BAKLOG_LOCAL_HEADER: "1"}
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        status = resp.status
    assert status in (200, 202, 204)


def test_amazon_web_provider_available_everywhere():
    rows = {r["key"]: r for r in manager.get_status()}
    web = rows["amazon_web"]
    assert web["platforms"] == []
    assert web["available"] is True
    assert web["kind"] == "browser"


def test_amazon_local_data_absent_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AMAZON_GAMES_SQL_DIR", raising=False)
    sys.modules.pop("clients.amazon_client", None)
    assert manager._local_data_present("amazon", {}) is False
    assert "amazon_client" not in sys.modules


def test_amazon_fetcher_available_for_web_on_all_platforms(auth_server):
    assert server.FETCHERS["amazon"].get("platforms") == []
    req = urllib.request.Request(f"{auth_server}/api/fetchers", method="GET")
    with urllib.request.urlopen(req, timeout=5) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    amazon = next((f for f in payload["fetchers"] if f["key"] == "amazon"))
    assert amazon["available"] is True
    assert amazon["platforms"] == []


def test_gog_galaxy_local_data_absent_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("GOG_GALAXY_DB", raising=False)
    assert manager._local_data_present("gog_galaxy", {}) is False
