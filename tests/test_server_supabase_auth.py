"""API auth gate on server.Handler when Supabase env is set."""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import jwt
import pytest

import server
from shared import account_profiles, profile_paths, supabase_auth
from shared.server_epic_oauth import epic_oauth_states
from shared.server_stream_tickets import STREAM_TICKET_MAX_USES


def _bearer(secret: str, sub: str = "a1b2c3d4-e5f6-7890-abcd-ef1234567890") -> str:
    payload = {
        "sub": sub,
        "aud": "authenticated",
        "iss": "https://test.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return f"Bearer {token}"


@pytest.fixture()
def auth_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-test")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", "unit-test-secret")
    monkeypatch.delenv("BAKLOG_AUTH_DISABLED", raising=False)
    supabase_auth.reset_jwks_client_for_tests()
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", "unit-test-secret", tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


@pytest.fixture()
def local_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Auth disabled — legacy static serving."""
    prof = tmp_path / "profiles"
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("BAKLOG_AUTH_DISABLED", raising=False)
    server._refresh_personal_paths()

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", tmp_path
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _request(
    base: str,
    path: str,
    *,
    method: str = "GET",
    auth: str | None = None,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    hdrs = dict(headers or {})
    if auth:
        hdrs["Authorization"] = auth
    req = urllib.request.Request(f"{base}{path}", headers=hdrs, method=method, data=body)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _stream_open_status(base: str, path: str) -> int:
    """GET /api/stream/* and return status without reading the SSE body."""
    import http.client
    from urllib.parse import urlparse

    parsed = urlparse(f"{base}{path}")
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=3)
    try:
        conn.request("GET", parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        return conn.getresponse().status
    finally:
        conn.close()


def _get_json(base: str, path: str, *, auth: str | None = None) -> tuple[int, dict]:
    status, raw = _request(base, path, auth=auth)
    try:
        return status, json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return status, {"error": raw.decode("utf-8", errors="replace")}


def test_auth_session_returns_profile(auth_server) -> None:
    base, secret, tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    status, data = _get_json(base, "/api/auth/session", auth=_bearer(secret, sub=sub))
    assert status == 200
    assert data["ok"] is True
    assert data["profile"] == sub.lower()
    assert data["email"] == ""


def test_auth_session_requires_bearer(auth_server) -> None:
    base, _secret, _tmp = auth_server
    status, data = _get_json(base, "/api/auth/session")
    assert status == 401
    assert "sign in" in data.get("error", "").lower()


def test_config_public_without_auth(auth_server) -> None:
    base, _secret, _tmp = auth_server
    status, data = _get_json(base, "/api/config")
    assert status == 200
    assert data["authRequired"] is True
    assert data["supabaseAnonKey"] == "anon-test"
    assert data.get("localProfiles") is False


def test_local_profiles_coexist_with_auth(auth_server, monkeypatch: pytest.MonkeyPatch) -> None:
    base, secret, _tmp = auth_server
    monkeypatch.setenv("BAKLOG_LOCAL_PROFILES", "1")
    status, data = _get_json(base, "/api/config")
    assert status == 200
    assert data["localProfiles"] is True

    status, data = _get_json(base, "/api/profiles", auth=_bearer(secret))
    assert status == 200
    assert isinstance(data.get("profiles"), list)
    assert len(data["profiles"]) >= 1

    body = json.dumps({"label": "Work"}).encode("utf-8")
    import urllib.request

    req = urllib.request.Request(
        f"{base}/api/profiles",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": _bearer(secret),
            server._BAKLOG_LOCAL_HEADER: "1",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 201


def test_personal_requires_bearer(auth_server) -> None:
    base, secret, _tmp = auth_server
    status, data = _get_json(base, "/api/personal")
    assert status == 401
    assert "sign in" in data.get("error", "").lower()

    status, data = _get_json(base, "/api/personal", auth=_bearer(secret))
    assert status == 200


def test_static_catalog_requires_bearer_when_auth_on(auth_server) -> None:
    base, secret, tmp = auth_server
    uid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    prof_dir = tmp / "profiles" / uid
    prof_dir.mkdir(parents=True)
    (prof_dir / "games_steam.json").write_text(
        json.dumps({"game_count": 1, "games": [{"id": "1", "name": "Portal"}]}),
        encoding="utf-8",
    )

    status, _ = _request(base, "/games_steam.json")
    assert status == 401

    status, raw = _request(base, "/games_steam.json", auth=_bearer(secret, sub=uid))
    assert status == 200
    data = json.loads(raw.decode("utf-8"))
    assert data["games"][0]["name"] == "Portal"


def test_static_catalog_public_when_auth_off(local_server) -> None:
    base, tmp = local_server
    (tmp / "games_steam.json").write_text(
        json.dumps({"game_count": 0, "games": []}),
        encoding="utf-8",
    )
    status, _ = _request(base, "/games_steam.json")
    assert status == 200


def test_app_shell_public_with_auth_on(auth_server) -> None:
    base, _secret, _tmp = auth_server
    status, _ = _request(base, "/")
    assert status == 200
    status, _ = _request(base, "/index.html")
    assert status == 200


def test_sensitive_paths_denied_always(auth_server, local_server) -> None:
    for base in (auth_server[0], local_server[0]):
        for path in ("/.env", "/cache/auth/secrets.bin", "/data/personal.json"):
            status, _ = _request(base, path)
            assert status == 404, path


def test_head_gated_like_get(auth_server) -> None:
    base, secret, _tmp = auth_server
    status, _ = _request(base, "/games_steam.json", method="HEAD")
    assert status == 401
    status, _ = _request(base, "/games_steam.json", method="HEAD", auth=_bearer(secret))
    assert status in (200, 404)


def test_csrf_bearer_allows_put_personal(auth_server) -> None:
    base, secret, _tmp = auth_server
    body = json.dumps({"profile": "a1b2c3d4-e5f6-7890-abcd-ef1234567890", "entries": {}}).encode("utf-8")
    status, _ = _request(
        base,
        "/api/personal",
        method="PUT",
        auth=_bearer(secret),
        headers={
            "Content-Type": "application/json",
            "Host": "public.example.com",
        },
        body=body,
    )
    assert status == 200


def test_csrf_without_bearer_blocked_when_exposed(auth_server) -> None:
    base, _secret, _tmp = auth_server
    body = json.dumps({"entries": {}}).encode("utf-8")
    status, raw = _request(
        base,
        "/api/personal",
        method="PUT",
        headers={
            "Content-Type": "application/json",
            "Host": "public.example.com",
        },
        body=body,
    )
    assert status == 403


def test_per_user_isolation(auth_server) -> None:
    base, secret, tmp = auth_server
    uid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    for uid, name in ((uid_a, "GameA"), (uid_b, "GameB")):
        d = tmp / "profiles" / uid
        d.mkdir(parents=True)
        (d / "games_steam.json").write_text(
            json.dumps({"game_count": 1, "games": [{"id": "1", "name": name}]}),
            encoding="utf-8",
        )

    status, raw = _request(base, "/games_steam.json", auth=_bearer(secret, sub=uid_a))
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["games"][0]["name"] == "GameA"

    status, raw = _request(base, "/games_steam.json", auth=_bearer(secret, sub=uid_b))
    assert status == 200
    assert json.loads(raw.decode("utf-8"))["games"][0]["name"] == "GameB"


def test_ensure_profile_concurrent_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prof = tmp_path / "profiles"
    prof.mkdir(parents=True)
    monkeypatch.setattr(profile_paths, "ROOT", tmp_path)
    monkeypatch.setattr(profile_paths, "PROFILES_DIR", prof)
    monkeypatch.setattr(profile_paths, "INDEX_FILE", prof / "index.json")
    uid = "550e8400-e29b-41d4-a716-446655440000"

    def _once() -> str:
        return account_profiles.ensure_profile_for_user(uid, "a@example.com")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_once) for _ in range(8)]
        pids = [f.result() for f in as_completed(futs)]

    assert len(set(pids)) == 1
    doc = profile_paths.load_index()
    matches = [p for p in doc.get("profiles", []) if p.get("id") == uid]
    assert len(matches) == 1


def test_stream_ticket_mint_and_sse_access(auth_server) -> None:
    base, secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(sub, "a@example.com")
    status, raw = _request(
        base,
        "/api/auth/stream-ticket",
        method="POST",
        auth=_bearer(secret, sub=sub),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    ticket = json.loads(raw.decode("utf-8"))["ticket"]
    assert ticket

    status, _ = _request(base, "/api/stream/abc123?ticket=" + ticket)
    assert status != 401

    status, _ = _request(base, "/api/stream/abc123")
    assert status == 401


def test_stream_ticket_limited_reuse(auth_server) -> None:
    base, secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    profile_id = sub.lower()
    account_profiles.ensure_profile_for_user(sub, "a@example.com")
    run_id = "ticket-reuse-terminal"
    summary = {
        "id": run_id,
        "status": "done",
        "exit_code": 0,
        "started_at": "2026-01-01T00:00:00Z",
        "ended_at": "2026-01-01T00:00:01Z",
        "profile_id": profile_id,
    }
    with server.MANAGER._lock:
        server.MANAGER._history.appendleft(summary)
    status, raw = _request(
        base,
        "/api/auth/stream-ticket",
        method="POST",
        auth=_bearer(secret, sub=sub),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    ticket = json.loads(raw.decode("utf-8"))["ticket"]
    max_uses = STREAM_TICKET_MAX_USES
    for _ in range(max_uses):
        status_ok = _stream_open_status(base, f"/api/stream/{run_id}?ticket={ticket}")
        assert status_ok == 200
    status_exhausted = _stream_open_status(base, f"/api/stream/{run_id}?ticket={ticket}")
    assert status_exhausted == 401


def test_stream_ticket_not_consumed_on_unknown_run(auth_server) -> None:
    base, secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(sub, "a@example.com")
    status, raw = _request(
        base,
        "/api/auth/stream-ticket",
        method="POST",
        auth=_bearer(secret, sub=sub),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    ticket = json.loads(raw.decode("utf-8"))["ticket"]
    status404, _ = _request(base, f"/api/stream/missing-run?ticket={ticket}")
    assert status404 == 404
    status_ok, _ = _request(base, f"/api/stream/abc?ticket={ticket}")
    assert status_ok != 401


def test_epic_callback_without_bearer(auth_server) -> None:
    base, _secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(sub, "a@example.com")
    state = "epic-test-state-01"
    server._register_epic_oauth_state(state, profile_id=sub)
    status, _ = _request(base, f"/oauth/epic/callback?state={state}")
    assert status != 401
    assert status == 400


def test_epic_callback_requires_state_when_auth_on(auth_server) -> None:
    base, _secret, _tmp = auth_server
    status, _ = _request(base, "/oauth/epic/callback")
    assert status == 400


def test_epic_callback_rejects_unknown_state(auth_server) -> None:
    base, _secret, _tmp = auth_server
    status, _ = _request(base, "/oauth/epic/callback?state=bogus&code=abc123def456")
    assert status == 400


def test_epic_oauth_url_endpoint_registers_state(auth_server) -> None:
    base, secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(sub, "a@example.com")
    status, raw = _request(
        base,
        "/api/auth/epic/oauth-url",
        method="POST",
        auth=_bearer(secret, sub=sub),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    data = json.loads(raw.decode("utf-8"))
    assert "epicgames.com/id/login" in data["url"]
    assert "oauth%2Fepic%2Fcallback" in data["url"] or "callback" in data["url"]
    assert data["state"]
    assert data["state"] in epic_oauth_states


def test_epic_oauth_url_unknown_provider(auth_server) -> None:
    base, secret, _tmp = auth_server
    status, _ = _request(
        base,
        "/api/auth/steam/oauth-url",
        method="POST",
        auth=_bearer(secret),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 404


def test_epic_callback_success_binds_profile(auth_server, monkeypatch: pytest.MonkeyPatch) -> None:
    base, secret, _tmp = auth_server
    sub = "550e8400-e29b-41d4-a716-446655440000"
    account_profiles.ensure_profile_for_user(sub, "a@example.com")

    captured: dict[str, str] = {}

    class _FakeEpic:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def login(self) -> None:
            return None

    def _fake_mark_connected(provider: str, _creds: dict) -> None:
        captured["provider"] = provider
        captured["profile"] = profile_paths.get_active_profile_id()

    monkeypatch.setattr("clients.epic_client.EpicClient", _FakeEpic)
    monkeypatch.setattr("auth.manager.mark_connected", _fake_mark_connected)

    status, raw = _request(
        base,
        "/api/auth/epic/oauth-url",
        method="POST",
        auth=_bearer(secret, sub=sub),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    state = json.loads(raw.decode("utf-8"))["state"]

    status, _ = _request(base, f"/oauth/epic/callback?state={state}&code=abcdef0123456789")
    assert status == 200
    assert captured["provider"] == "epic"
    assert captured["profile"] == sub


def test_build_epic_oauth_login_url_shape() -> None:
    from clients.epic_client import CLIENT_ID, build_epic_oauth_login_url

    url = build_epic_oauth_login_url("http://127.0.0.1:8765/oauth/epic/callback", "st8")
    assert url.startswith("https://www.epicgames.com/id/login?")
    assert "redirectUrl=" in url
    assert CLIENT_ID in url
    assert "st8" in url


def test_epic_callback_requires_state_even_when_auth_off(local_server) -> None:
    """CSRF defense: a server-minted state is mandatory regardless of auth mode."""
    base, _tmp = local_server
    # Missing state — previously accepted when auth was disabled, now rejected.
    status, _ = _request(base, "/oauth/epic/callback?code=abc123def456")
    assert status == 400
    # Present but unknown/forged state — rejected.
    status2, _ = _request(base, "/oauth/epic/callback?state=forged&code=abc123def456")
    assert status2 == 400


def test_epic_callback_consumes_valid_state_when_auth_off(local_server) -> None:
    base, _tmp = local_server
    state = "epic-local-state-01"
    server._register_epic_oauth_state(state, profile_id="default")
    assert state in epic_oauth_states
    # A valid minted state is accepted (single-use) even with auth disabled; the
    # missing code yields 400 but the state is consumed, proving the valid path ran.
    status, _ = _request(base, f"/oauth/epic/callback?state={state}")
    assert status == 400
    assert state not in epic_oauth_states


def test_secrets_export_corrupt_returns_400(auth_server, monkeypatch: pytest.MonkeyPatch) -> None:
    base, secret, _tmp = auth_server
    from auth.secrets import SecretsCorruptError

    def _boom(*_a: object, **_k: object) -> bytes:
        raise SecretsCorruptError("corrupt store")

    monkeypatch.setattr("auth.bundle.export_bundle", _boom)
    body = json.dumps({"passphrase": "long-enough-passphrase"}).encode("utf-8")
    status, raw = _request(
        base,
        "/api/auth/secrets/export",
        method="POST",
        auth=_bearer(secret),
        headers={"Content-Type": "application/json"},
        body=body,
    )
    assert status == 400
    payload = json.loads(raw.decode("utf-8"))
    assert payload.get("code") == "secrets_corrupt"


def test_run_cancel_denied_cross_profile(auth_server) -> None:
    base, secret, _tmp = auth_server
    uid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    account_profiles.ensure_profile_for_user(uid_a, "a@test.com")
    account_profiles.ensure_profile_for_user(uid_b, "b@test.com")
    key = next(iter(server.FETCHERS))
    run = server.Run(key, profile_id=uid_a)
    with server.MANAGER._lock:
        server.MANAGER._runs_by_id[run.id] = run
    status, raw = _request(
        base,
        f"/api/run/{run.id}/cancel",
        method="POST",
        auth=_bearer(secret, sub=uid_b),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 404
    assert "unknown run" in json.loads(raw.decode("utf-8")).get("error", "")


def test_cancel_all_scoped_to_active_profile(auth_server) -> None:
    base, secret, _tmp = auth_server
    uid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    account_profiles.ensure_profile_for_user(uid_a, "a@test.com")
    account_profiles.ensure_profile_for_user(uid_b, "b@test.com")
    key = next(iter(server.FETCHERS))
    run_a = server.Run(key, profile_id=uid_a)
    run_b = server.Run(key, profile_id=uid_b)
    with server.MANAGER._lock:
        server.MANAGER._runs_by_id[run_a.id] = run_a
        server.MANAGER._runs_by_id[run_b.id] = run_b
        run_a.status = "running"
        run_b.status = "running"
        server.MANAGER._pending.extend([run_a, run_b])
        server.MANAGER._active = run_a
    status, raw = _request(
        base,
        "/api/runs/cancel",
        method="POST",
        auth=_bearer(secret, sub=uid_a),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    cancelled = json.loads(raw.decode("utf-8")).get("cancelled") or []
    cancelled_ids = {c.get("id") for c in cancelled}
    assert run_a.id in cancelled_ids
    assert run_b.id not in cancelled_ids


def test_force_reset_scoped_to_active_profile(auth_server) -> None:
    base, secret, _tmp = auth_server
    uid_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    uid_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    account_profiles.ensure_profile_for_user(uid_a, "a@test.com")
    account_profiles.ensure_profile_for_user(uid_b, "b@test.com")
    key = next(iter(server.FETCHERS))
    run_a = server.Run(key, profile_id=uid_a)
    run_b = server.Run(key, profile_id=uid_b)
    with server.MANAGER._lock:
        server.MANAGER._runs_by_id[run_a.id] = run_a
        server.MANAGER._runs_by_id[run_b.id] = run_b
        run_a.status = "running"
        run_b.status = "running"
        server.MANAGER._pending.extend([run_a, run_b])
        server.MANAGER._active = run_a
    status, raw = _request(
        base,
        "/api/runs/cancel?force=1",
        method="POST",
        auth=_bearer(secret, sub=uid_a),
        headers={"Content-Type": "application/json"},
        body=b"{}",
    )
    assert status == 200
    payload = json.loads(raw.decode("utf-8"))
    assert payload.get("force") is True
    cancelled = payload.get("cancelled") or []
    cancelled_ids = {c.get("id") for c in cancelled}
    assert run_a.id in cancelled_ids
    assert run_b.id not in cancelled_ids
