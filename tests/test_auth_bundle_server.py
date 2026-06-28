import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

import server
from auth.manager import mark_connected
from auth.secrets import set_master_password_override


@pytest.fixture()
def auth_bundle_server(tmp_path, monkeypatch):
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir(parents=True)
    profiles_root = auth_dir / "profiles"
    profiles_root.mkdir(parents=True)
    secrets_file = auth_dir / "secrets.bin"
    monkeypatch.setattr("auth.secrets.AUTH_DIR", auth_dir)
    monkeypatch.setattr("auth.secrets.SECRETS_FILE", secrets_file)
    monkeypatch.setattr("auth.secrets.MASTER_KEY_FILE", auth_dir / ".master_key")
    import auth.secrets as secrets_mod

    secrets_mod._cache = None
    set_master_password_override("test-passphrase-for-unit-tests")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        set_master_password_override(None)
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _post_json(base, path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json", server._BAKLOG_LOCAL_HEADER: "1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            headers = dict(resp.headers)
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype:
                return (resp.status, json.loads(raw.decode("utf-8")), headers)
            return (resp.status, raw, headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = {"error": payload.decode("utf-8", errors="replace")}
        return (exc.code, parsed, dict(exc.headers))


def _post_bytes(base, path, body):
    req = urllib.request.Request(
        f"{base}{path}",
        data=body,
        headers={"Content-Type": "application/octet-stream", server._BAKLOG_LOCAL_HEADER: "1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return (resp.status, json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"error": payload}
        return (exc.code, parsed)


def _post_json_origin_only(base, path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base}{path}", data=data, headers={"Content-Type": "application/json", "Origin": base}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            headers = dict(resp.headers)
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype:
                return (resp.status, json.loads(raw.decode("utf-8")), headers)
            return (resp.status, raw, headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            parsed = {"error": payload.decode("utf-8", errors="replace")}
        return (exc.code, parsed, dict(exc.headers))


def test_export_short_passphrase_400(auth_bundle_server):
    status, body, _ = _post_json(auth_bundle_server, "/api/auth/secrets/export", {"passphrase": "short"})
    assert status == 400
    assert body["code"] == "invalid_passphrase"


def test_export_content_disposition(auth_bundle_server):
    mark_connected("steam", {"STEAM_API_KEY": "abc", "STEAM_ID": "76561198000000000"})
    status, body, headers = _post_json(
        auth_bundle_server, "/api/auth/secrets/export", {"passphrase": "server-test-pass"}
    )
    assert status == 200
    assert isinstance(body, bytes)
    assert body[:8] == b"BAKLOGSB"
    cd = headers.get("Content-disposition") or headers.get("Content-Disposition") or ""
    assert "baklog-secrets-" in cd
    assert cd.endswith('.bundle"')


def test_import_bad_passphrase_403(auth_bundle_server):
    mark_connected("steam", {"STEAM_API_KEY": "abc", "STEAM_ID": "76561198000000000"})
    _, blob, _ = _post_json(auth_bundle_server, "/api/auth/secrets/export", {"passphrase": "correct-passphrase"})
    assert isinstance(blob, bytes)
    import base64

    status, body, _headers = _post_json(
        auth_bundle_server,
        "/api/auth/secrets/import",
        {"passphrase": "wrong-passphrase-here", "blob": base64.b64encode(blob).decode("ascii")},
    )
    assert status == 403
    assert body["code"] == "bad_passphrase"


def test_secrets_export_blocked_without_local_header(auth_bundle_server):
    status, body, _ = _post_json_origin_only(
        auth_bundle_server, "/api/auth/secrets/export", {"passphrase": "server-test-pass"}
    )
    assert status == 403
    assert "cross-origin" in str(body.get("error", "")).lower()


def test_secrets_import_blocked_without_local_header(auth_bundle_server):
    status, body, _ = _post_json_origin_only(
        auth_bundle_server, "/api/auth/secrets/import", {"passphrase": "server-test-pass", "blob": ""}
    )
    assert status == 403
    assert "cross-origin" in str(body.get("error", "")).lower()


def test_master_password_blocked_without_local_header(auth_bundle_server):
    status, body, _ = _post_json_origin_only(
        auth_bundle_server, "/api/auth/master-password", {"password": "new-test-passphrase-for-unit-tests"}
    )
    assert status == 403
    assert "cross-origin" in str(body.get("error", "")).lower()
