"""Verify Supabase access tokens for the BAKLOG dev server."""

from __future__ import annotations

import os
from typing import Any

import jwt
from jwt.exceptions import InvalidTokenError

_AUDIENCE = "authenticated"
_HS256_ALGORITHMS = ("HS256",)
_JWKS_ALGORITHMS = ("ES256", "RS256")
_JWT_REQUIRED_CLAIMS = ("exp", "sub", "iss")
_cached_jwks_client: jwt.PyJWKClient | None = None


def auth_disabled() -> bool:
    return os.environ.get("BAKLOG_AUTH_DISABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def local_profiles_enabled() -> bool:
    """Allow local Work/Play profile switching even when Supabase auth is on."""
    return os.environ.get("BAKLOG_LOCAL_PROFILES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _jwt_secret() -> str:
    return os.environ.get("BAKLOG_SUPABASE_JWT_SECRET", "").strip()


def _supabase_url() -> str:
    return os.environ.get("BAKLOG_SUPABASE_URL", "").strip().rstrip("/")


def _anon_key() -> str:
    return os.environ.get("BAKLOG_SUPABASE_ANON_KEY", "").strip()


def _jwt_issuer() -> str | None:
    url = _supabase_url()
    return f"{url}/auth/v1" if url else None


def auth_enabled() -> bool:
    if auth_disabled():
        return False
    return bool(_supabase_url() and _anon_key())


def public_auth_config() -> dict[str, Any]:
    """Values safe to expose to the browser via GET /api/config."""
    return {
        "supabaseUrl": _supabase_url(),
        "supabaseAnonKey": _anon_key(),
        "authRequired": auth_enabled(),
        "localProfiles": local_profiles_enabled(),
    }


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _get_jwks_client() -> jwt.PyJWKClient | None:
    global _cached_jwks_client
    url = _supabase_url()
    if not url:
        return None
    if _cached_jwks_client is None:
        try:
            _cached_jwks_client = jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json")
        except Exception:
            return None
    return _cached_jwks_client


def _decode_hs256(raw: str) -> dict[str, Any] | None:
    secret = _jwt_secret()
    if not secret:
        return None
    try:
        issuer = _jwt_issuer()
        payload = jwt.decode(
            raw,
            secret,
            algorithms=list(_HS256_ALGORITHMS),
            audience=_AUDIENCE,
            issuer=issuer,
            options={"require": list(_JWT_REQUIRED_CLAIMS)},
        )
    except InvalidTokenError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _decode_jwks(raw: str) -> dict[str, Any] | None:
    client = _get_jwks_client()
    if client is None:
        return None
    try:
        signing_key = client.get_signing_key_from_jwt(raw)
        issuer = _jwt_issuer()
        payload = jwt.decode(
            raw,
            signing_key.key,
            algorithms=list(_JWKS_ALGORITHMS),
            audience=_AUDIENCE,
            issuer=issuer,
            options={"require": list(_JWT_REQUIRED_CLAIMS)},
        )
    except InvalidTokenError:
        return None
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _decode_access_token(raw: str) -> dict[str, Any] | None:
    """Verify JWT via legacy HS256 secret and/or project JWKS (ES256/RS256)."""
    payload = _decode_hs256(raw)
    if payload is not None:
        return payload
    return _decode_jwks(raw)


def verify_bearer_token(authorization: str | None) -> str | None:
    """Return Supabase user id (JWT ``sub``) or None when invalid."""
    user = verify_bearer_user(authorization)
    return user["id"] if user else None


def verify_bearer_user(authorization: str | None) -> dict[str, str] | None:
    """Return ``{"id", "email"}`` for a valid token, else None."""
    if not auth_enabled():
        return None
    raw = _parse_bearer(authorization)
    if not raw:
        return None
    payload = _decode_access_token(raw)
    if not payload:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        return None
    email = payload.get("email")
    return {
        "id": sub.strip(),
        "email": email.strip() if isinstance(email, str) else "",
    }


def reset_jwks_client_for_tests() -> None:
    """Clear cached JWKS client (tests only)."""
    global _cached_jwks_client
    _cached_jwks_client = None
