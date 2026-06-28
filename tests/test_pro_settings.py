import json
import threading
from functools import partial
from http import HTTPStatus
from http.server import ThreadingHTTPServer

import pytest

import server
from shared import profile_paths
from shared.pro_settings import DEFAULT_PRO_SETTINGS, read_pro_settings, write_pro_settings
from tests.test_server_supabase_auth import _get_json, _request

pytest_plugins = ["tests.test_server_supabase_auth"]


@pytest.fixture()
def local_server(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    server._refresh_personal_paths()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f"http://127.0.0.1:{port}", tmp_path)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def isolated_profile(tmp_path, monkeypatch):
    prof = tmp_path / "profiles"
    prof.mkdir(parents=True)
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}), encoding="utf-8"
    )
    (prof / "default" / "data").mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_PLAN", raising=False)


def test_defaults_when_missing(isolated_profile):
    assert read_pro_settings() == DEFAULT_PRO_SETTINGS


def test_write_and_read_cloud_mirror_toggle(isolated_profile):
    doc = write_pro_settings({"cloudMirrorEnabled": True})
    assert doc["cloudMirrorEnabled"] is True
    assert read_pro_settings()["cloudMirrorEnabled"] is True


def test_rejects_unknown_keys(isolated_profile):
    with pytest.raises(ValueError, match="unknown pro setting"):
        write_pro_settings({"notARealKey": True})


def test_pro_settings_put_requires_pro(local_server, monkeypatch):
    base, _tmp = local_server
    monkeypatch.setenv("BAKLOG_PLAN", "free")
    body = json.dumps({"cloudMirrorEnabled": True}).encode("utf-8")
    status, raw = _request(
        base,
        "/api/pro-settings",
        method="PUT",
        headers={"X-BAKLOG-Local": "1", "Content-Type": "application/json"},
        body=body,
    )
    data = json.loads(raw.decode("utf-8"))
    assert status == HTTPStatus.FORBIDDEN
    assert "Pro" in data.get("error", "")


def test_pro_settings_put_persists_for_local_pro(local_server, monkeypatch):
    base, _tmp = local_server
    monkeypatch.setenv("BAKLOG_PLAN", "pro")
    body = json.dumps({"cloudMirrorEnabled": True}).encode("utf-8")
    status, raw = _request(
        base,
        "/api/pro-settings",
        method="PUT",
        headers={"X-BAKLOG-Local": "1", "Content-Type": "application/json"},
        body=body,
    )
    assert status == HTTPStatus.OK
    data = json.loads(raw.decode("utf-8"))
    assert data["proSettings"]["cloudMirrorEnabled"] is True
    cfg_status, cfg = _get_json(base, "/api/config")
    assert cfg_status == HTTPStatus.OK
    assert cfg["proSettings"]["cloudMirrorEnabled"] is True
    assert cfg["capabilities"]["queue_bulk_refresh"]["enabled"] is True


def test_pro_settings_put_blocked_without_local_header(auth_server):
    base, _secret, _tmp = auth_server
    body = json.dumps({"cloudMirrorEnabled": True}).encode("utf-8")
    status, _raw = _request(
        base,
        "/api/pro-settings",
        method="PUT",
        headers={"Content-Type": "application/json", "Host": "public.example.com"},
        body=body,
    )
    assert status == HTTPStatus.FORBIDDEN
