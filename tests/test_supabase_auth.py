"""Tests for Supabase JWT verification."""
from __future__ import annotations

import time

import jwt
import pytest

from shared import supabase_auth


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BAKLOG_AUTH_DISABLED", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_URL", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)


def _token(
    secret: str,
    *,
    sub: str = "550e8400-e29b-41d4-a716-446655440000",
    exp_delta: int = 3600,
    aud: str = "authenticated",
    iss: str = "https://x.supabase.co/auth/v1",
) -> str:
    payload = {
        "sub": sub,
        "aud": aud,
        "iss": iss,
        "exp": int(time.time()) + exp_delta,
        "email": "invitee@example.com",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_auth_disabled_without_config() -> None:
    assert supabase_auth.auth_enabled() is False
    assert supabase_auth.verify_bearer_token(None) is None


def test_auth_disabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", "secret")
    monkeypatch.setenv("BAKLOG_AUTH_DISABLED", "1")
    assert supabase_auth.auth_enabled() is False


def test_verify_valid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-jwt-secret"
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", secret)
    assert supabase_auth.auth_enabled() is True
    raw = _token(secret)
    user = supabase_auth.verify_bearer_user(f"Bearer {raw}")
    assert user is not None
    assert user["id"] == "550e8400-e29b-41d4-a716-446655440000"
    assert user["email"] == "invitee@example.com"


def test_verify_rejects_wrong_issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-jwt-secret"
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", secret)
    raw = _token(secret, iss="https://evil.example/auth/v1")
    assert supabase_auth.verify_bearer_token(f"Bearer {raw}") is None


def test_verify_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "test-jwt-secret"
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", secret)
    raw = _token(secret, exp_delta=-60)
    assert supabase_auth.verify_bearer_token(f"Bearer {raw}") is None


def test_public_config_masks_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("BAKLOG_SUPABASE_JWT_SECRET", "secret")
    cfg = supabase_auth.public_auth_config()
    assert cfg["authRequired"] is True
    assert cfg["supabaseUrl"] == "https://x.supabase.co"
    assert cfg["supabaseAnonKey"] == "anon-key"
    assert cfg["authConfirmRedirectUrl"] == "https://baklog.app/auth/confirmed"
    assert cfg["authResetRedirectUrl"] == "https://baklog.app/auth/reset"
    assert "secret" not in cfg.values()


def test_public_config_auth_redirect_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("BAKLOG_AUTH_CONFIRM_REDIRECT_URL", "https://staging.example/confirm")
    monkeypatch.setenv("BAKLOG_AUTH_RESET_REDIRECT_URL", "https://staging.example/reset")
    cfg = supabase_auth.public_auth_config()
    assert cfg["authConfirmRedirectUrl"] == "https://staging.example/confirm"
    assert cfg["authResetRedirectUrl"] == "https://staging.example/reset"


def test_decode_jwks_es256(monkeypatch: pytest.MonkeyPatch) -> None:
    """JWKS path is wired; invalid token still rejects."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    class _FakeKey:
        key = pem

    class _FakeClient:
        def get_signing_key_from_jwt(self, _raw: str) -> _FakeKey:
            return _FakeKey()

    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    supabase_auth.reset_jwks_client_for_tests()
    monkeypatch.setattr(supabase_auth, "_get_jwks_client", lambda: _FakeClient())

    payload = {
        "sub": "550e8400-e29b-41d4-a716-446655440000",
        "aud": "authenticated",
        "iss": "https://x.supabase.co/auth/v1",
        "exp": int(time.time()) + 3600,
    }
    raw = jwt.encode(payload, private_key, algorithm="ES256")
    user = supabase_auth.verify_bearer_user(f"Bearer {raw}")
    assert user is not None
    assert user["id"] == payload["sub"]


def test_auth_enabled_without_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAKLOG_SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("BAKLOG_SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.delenv("BAKLOG_SUPABASE_JWT_SECRET", raising=False)
    assert supabase_auth.auth_enabled() is True
