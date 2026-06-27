"""Tests for GET /api/mirror."""

from __future__ import annotations

import json
import time
from http import HTTPStatus

import jwt

from tests.test_server_supabase_auth import _get_json

pytest_plugins = ["tests.test_server_supabase_auth"]


def _pro_bearer(secret: str, sub: str = "550e8400-e29b-41d4-a716-446655440000") -> str:
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

    monkeypatch.setattr(
        "shared.server_mirror.list_remote_mirror_artifacts",
        lambda **kwargs: sample,
    )
    status, data = _get_json(base, "/api/mirror", auth=_pro_bearer(secret))
    assert status == HTTPStatus.OK
    assert data["artifacts"] == sample
    assert "localUploadState" in data


def test_mirror_get_downloads_artifact(auth_server, monkeypatch):
    base, secret, _tmp = auth_server
    body = json.dumps({"games": []}).encode("utf-8")

    monkeypatch.setattr(
        "shared.server_mirror.download_remote_mirror_artifact",
        lambda **kwargs: body,
    )
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
