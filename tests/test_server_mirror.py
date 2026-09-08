"""HTTP handlers for /api/mirror and /api/mirror/import."""

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
from shared.cloud_mirror import MirrorProfileMismatch


@pytest.fixture()
def mirror_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    (prof).mkdir()
    (prof / "index.json").write_text(
        json.dumps({"active": "default", "profiles": [{"id": "default", "label": "Default"}]}),
        encoding="utf-8",
    )
    (prof / "default" / "data").mkdir(parents=True)
    (prof / "default" / ".migration_complete").write_text("1\n", encoding="utf-8")
    server._refresh_personal_paths()
    monkeypatch.setattr("shared.supabase_auth.auth_enabled", lambda: True)
    monkeypatch.setattr(server, "_bind_request_user", lambda _h: {"id": "u", "email": "a@b.c"})
    monkeypatch.setattr("shared.server_mirror.mirror_read_allowed", lambda **_: False)

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


def test_get_mirror_forbidden_without_pro(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.supabase_auth.verify_bearer_user", lambda *_: {"id": "u", "email": "a@b.c"})
    status, data = _request(mirror_server, "/api/mirror", headers={"Authorization": "Bearer tok"})
    assert status == 403
    assert data.get("error") == "Pro plan required"


def test_import_requires_local_header(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_read_allowed", lambda **_: True)
    status, _ = _request(
        mirror_server,
        "/api/mirror/import",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer tok"},
        body=b"{}",
    )
    assert status == 403


def test_import_profile_mismatch_409(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_read_allowed", lambda **_: True)
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )

    def _boom(**kwargs):
        raise MirrorProfileMismatch("profile mismatch (active='default', claimed='other')")

    monkeypatch.setattr("shared.server_mirror.import_remote_mirror_to_profile", _boom)
    status, data = _request(
        mirror_server,
        "/api/mirror/import",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=json.dumps({"profile": "other"}).encode(),
    )
    assert status == 409, data
    assert "profile mismatch" in str(data.get("error") or "")


def test_get_mirror_unauthorized_on_permission_error(
    mirror_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_read_allowed", lambda **_: True)
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )

    def _boom(**kwargs):
        raise PermissionError("invalid session")

    monkeypatch.setattr("shared.server_mirror.list_remote_mirror_artifacts", _boom)
    status, data = _request(
        mirror_server,
        "/api/mirror",
        headers={"Authorization": "Bearer tok"},
    )
    assert status == 401, data
    assert "invalid session" in str(data.get("error") or "")


def test_import_unauthorized_on_permission_error(
    mirror_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_read_allowed", lambda **_: True)
    monkeypatch.setattr(
        "shared.supabase_auth.verify_bearer_user",
        lambda *_a, **_k: {"id": "u", "email": "a@b.c"},
    )

    def _boom(**kwargs):
        raise PermissionError("missing bearer token")

    monkeypatch.setattr("shared.server_mirror.import_remote_mirror_to_profile", _boom)
    status, data = _request(
        mirror_server,
        "/api/mirror/import",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=b"{}",
    )
    assert status == 401, data
    assert "bearer" in str(data.get("error") or "").lower()


def test_sync_requires_local_header(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_upload_allowed", lambda **_: True)
    status, _ = _request(
        mirror_server,
        "/api/mirror/sync",
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer tok"},
        body=b"{}",
    )
    assert status == 403


def test_sync_forbidden_when_not_allowed(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_upload_allowed", lambda **_: False)
    monkeypatch.setattr("shared.entitlement.current_plan", lambda *_a, **_k: "pro")
    status, data = _request(
        mirror_server,
        "/api/mirror/sync",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=b"{}",
    )
    assert status == 403
    assert "cloud sync" in str(data.get("error") or "").lower()


def test_sync_ok_calls_sync_mirror_now(mirror_server: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shared.server_mirror.mirror_upload_allowed", lambda **_: True)
    monkeypatch.setattr("shared.entitlement.current_plan", lambda *_a, **_k: "pro")
    monkeypatch.setattr(
        "shared.server_mirror.sync_mirror_now",
        lambda **_: {
            "ok": True,
            "scheduled": ["games_steam.json"],
            "uploaded": {"games_steam.json": "ok"},
            "errors": [],
            "localUploadState": {"artifacts": {}, "last_upload_at": None},
        },
    )
    status, data = _request(
        mirror_server,
        "/api/mirror/sync",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer tok",
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        body=b"{}",
    )
    assert status == 200, data
    assert data.get("ok") is True
    assert data.get("uploaded", {}).get("games_steam.json") == "ok"
