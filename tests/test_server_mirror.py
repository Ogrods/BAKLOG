import json
import time
from http import HTTPStatus

import jwt
import pytest

from tests.test_server_supabase_auth import _get_json

pytest_plugins = ["tests.test_server_supabase_auth"]


def _post_json(base, path, body, *, auth=None):
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json", "X-BAKLOG-Local": "1"}
    if auth:
        headers["Authorization"] = auth
    req = urllib.request.Request(f"{base}{path}", data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return (resp.status, json.loads(resp.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return (exc.code, json.loads(raw))
        except json.JSONDecodeError:
            return (exc.code, {"error": raw})


def _pro_bearer(secret, sub="550e8400-e29b-41d4-a716-446655440000"):
    token = jwt.encode(
        {
            "sub": sub,
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"plan": "pro"},
        },
        secret,
        algorithm="HS256",
    )
    return f"Bearer {token}"


def test_mirror_get_forbidden_when_auth_disabled(local_server):
    base, _tmp = local_server
    status, data = _get_json(base, "/api/mirror")
    assert status == HTTPStatus.FORBIDDEN
    assert "Pro" in data.get("error", "")


def test_mirror_get_forbidden_for_free_user(auth_server):
    base, secret, _tmp = auth_server
    token = jwt.encode(
        {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"plan": "free"},
        },
        secret,
        algorithm="HS256",
    )
    status, data = _get_json(base, "/api/mirror", auth=f"Bearer {token}")
    assert status == HTTPStatus.FORBIDDEN


def test_mirror_get_lists_artifacts(auth_server, monkeypatch):
    base, secret, _tmp = auth_server
    sample = [{"path": "games_steam.json", "id": "1", "updated_at": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr("shared.server_mirror.list_remote_mirror_artifacts", lambda **kwargs: sample)
    status, data = _get_json(base, "/api/mirror", auth=_pro_bearer(secret))
    assert status == HTTPStatus.OK
    assert data["artifacts"] == sample
    assert "localUploadState" in data


def test_mirror_get_downloads_artifact(auth_server, monkeypatch):
    base, secret, _tmp = auth_server
    body = json.dumps({"games": []}).encode("utf-8")
    monkeypatch.setattr("shared.server_mirror.download_remote_mirror_artifact", lambda **kwargs: body)
    status, data = _get_json(base, "/api/mirror?path=games_steam.json", auth=_pro_bearer(secret))
    assert status == HTTPStatus.OK
    assert data == {"games": []}


def test_mirror_get_rejects_bad_artifact(auth_server, monkeypatch):
    base, secret, _tmp = auth_server

    def _raise(**kwargs):
        raise ValueError("artifact not allowed")

    monkeypatch.setattr("shared.server_mirror.download_remote_mirror_artifact", _raise)
    status, data = _get_json(base, "/api/mirror?path=cache/secrets.bin", auth=_pro_bearer(secret))
    assert status == HTTPStatus.BAD_REQUEST


def test_mirror_get_rejects_invalid_profile(auth_server):
    base, secret, _tmp = auth_server
    status, data = _get_json(base, "/api/mirror?profile=../evil", auth=_pro_bearer(secret))
    assert status == HTTPStatus.BAD_REQUEST
    assert "profile" in data.get("error", "").lower()


def test_mirror_import_post_success(auth_server, monkeypatch):
    base, secret, _tmp = auth_server
    monkeypatch.setattr(
        "shared.server_mirror.import_remote_mirror_to_profile",
        lambda **kwargs: {"ok": True, "imported": ["games_steam.json"], "count": 1, "personal": False},
    )
    status, data = _post_json(base, "/api/mirror/import", {}, auth=_pro_bearer(secret))
    assert status == HTTPStatus.OK
    assert data["count"] == 1


def test_mirror_import_post_forbidden_for_free(auth_server):
    base, secret, _tmp = auth_server
    token = jwt.encode(
        {
            "sub": "550e8400-e29b-41d4-a716-446655440000",
            "aud": "authenticated",
            "iss": "https://test.supabase.co/auth/v1",
            "exp": int(time.time()) + 3600,
            "app_metadata": {"plan": "free"},
        },
        secret,
        algorithm="HS256",
    )
    status, data = _post_json(base, "/api/mirror/import", {}, auth=f"Bearer {token}")
    assert status == HTTPStatus.FORBIDDEN


def test_mirror_import_post_blocked_without_csrf_or_bearer(auth_server):
    base, _secret, _tmp = auth_server
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{base}/api/mirror/import",
        data=b"{}",
        method="POST",
        headers={"Content-Type": "application/json", "Host": "public.example.com"},
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == HTTPStatus.FORBIDDEN


def test_mirror_import_post_allowed_with_bearer_only(auth_server, monkeypatch):
    base, secret, _tmp = auth_server
    monkeypatch.setattr(
        "shared.server_mirror.import_remote_mirror_to_profile",
        lambda **kwargs: {"ok": True, "imported": ["games_steam.json"], "count": 1, "personal": False},
    )
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{base}/api/mirror/import",
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": _pro_bearer(secret),
            "Host": "public.example.com",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status == HTTPStatus.OK
