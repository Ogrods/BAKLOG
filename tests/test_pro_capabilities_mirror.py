"""Capability registry status and pro-settings gate for cloud_sync_mirror."""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import server
from shared import profile_paths
from shared.pro_capabilities import capability_registry_status


@pytest.fixture()
def pro_settings_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    prof.mkdir()
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}),
        encoding="utf-8",
    )
    (prof / "default" / "data").mkdir(parents=True)
    (prof / "default" / ".migration_complete").write_text("1\n", encoding="utf-8")
    server._refresh_personal_paths()
    monkeypatch.setattr("shared.supabase_auth.auth_enabled", lambda: True)
    monkeypatch.setattr(server, "_bind_request_user", lambda _h: {"id": "u", "email": "a@b.c"})
    monkeypatch.setattr("shared.server_pro_settings.is_pro", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )

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


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, Any]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{base}{path}",
        method=method,
        headers=headers or {},
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, {"error": raw}


def test_capability_registry_status_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKLOG_CAP_CLOUD_MIRROR", raising=False)
    assert capability_registry_status("cloud_sync_mirror") == "soon"
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "live")
    assert capability_registry_status("cloud_sync_mirror") == "live"
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "off")
    assert capability_registry_status("cloud_sync_mirror") == "off"


def test_pro_settings_enable_forbidden_when_soon(
    pro_settings_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "soon")
    status, data = _request(
        pro_settings_server,
        "/api/pro/settings",
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=json.dumps({"cloudMirrorEnabled": True}).encode(),
    )
    assert status == 403, data
    assert "not available" in str(data.get("error") or "").lower()


def test_pro_settings_enable_ok_when_live(
    pro_settings_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BAKLOG_CAP_CLOUD_MIRROR", "live")
    status, data = _request(
        pro_settings_server,
        "/api/pro/settings",
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=json.dumps({"cloudMirrorEnabled": True}).encode(),
    )
    assert status == 200, data
    assert data.get("proSettings", {}).get("cloudMirrorEnabled") is True
