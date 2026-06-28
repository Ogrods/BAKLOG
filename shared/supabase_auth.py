import os

import jwt
from jwt.exceptions import InvalidTokenError

_AUDIENCE = "authenticated"
_HS256_ALGORITHMS = ("HS256",)
_JWKS_ALGORITHMS = ("ES256", "RS256")
_JWT_REQUIRED_CLAIMS = ("exp", "sub", "iss")
_cached_jwks_client = None


def auth_disabled():
    return os.environ.get("BAKLOG_AUTH_DISABLED", "").strip().lower() in ("1", "true", "yes", "on")


def local_profiles_enabled():
    return os.environ.get("BAKLOG_LOCAL_PROFILES", "").strip().lower() in ("1", "true", "yes", "on")


def _jwt_secret():
    return os.environ.get("BAKLOG_SUPABASE_JWT_SECRET", "").strip()


def _supabase_url():
    return os.environ.get("BAKLOG_SUPABASE_URL", "").strip().rstrip("/")


def _anon_key():
    return os.environ.get("BAKLOG_SUPABASE_ANON_KEY", "").strip()


def _jwt_issuer():
    url = _supabase_url()
    return f"{url}/auth/v1" if url else None


def auth_enabled():
    if auth_disabled():
        return False
    return bool(_supabase_url() and _anon_key())


def public_auth_config():
    return {
        "supabaseUrl": _supabase_url(),
        "supabaseAnonKey": _anon_key(),
        "authRequired": auth_enabled(),
        "localProfiles": local_profiles_enabled(),
        "authConfirmRedirectUrl": os.environ.get(
            "BAKLOG_AUTH_CONFIRM_REDIRECT_URL", "https://baklog.app/auth/confirmed"
        ).strip(),
        "authResetRedirectUrl": os.environ.get(
            "BAKLOG_AUTH_RESET_REDIRECT_URL", "https://baklog.app/auth/reset"
        ).strip(),
    }


def _parse_bearer(authorization):
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _jwks_url():
    url = _supabase_url()
    return f"{url}/auth/v1/.well-known/jwks.json" if url else None


def _get_jwks_client():
    global _cached_jwks_client
    jwks_url = _jwks_url()
    if not jwks_url:
        return None
    if _cached_jwks_client is None:
        try:
            _cached_jwks_client = jwt.PyJWKClient(jwks_url)
        except Exception:
            return None
    return _cached_jwks_client


def warmup_jwks_client():
    if not auth_enabled() or _jwt_secret():
        return
    jwks_url = _jwks_url()
    if not jwks_url:
        return
    try:
        import urllib.request

        with urllib.request.urlopen(jwks_url, timeout=10) as resp:
            resp.read()
        _get_jwks_client()
    except Exception:
        pass


def _decode_hs256(raw):
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


def _decode_jwks(raw):
    import time

    global _cached_jwks_client
    for attempt in range(3):
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
            _cached_jwks_client = None
            if attempt < 2:
                time.sleep(0.35 * (attempt + 1))
                continue
            return None
        if not isinstance(payload, dict):
            return None
        return payload
    return None


def _decode_access_token(raw):
    payload = _decode_hs256(raw)
    if payload is not None:
        return payload
    return _decode_jwks(raw)


def verify_bearer_token(authorization):
    user = verify_bearer_user(authorization)
    return user["id"] if user else None


def verify_bearer_user(authorization):
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
    return {"id": sub.strip(), "email": email.strip() if isinstance(email, str) else ""}


def _extract_plan(payload):
    candidates = [payload.get("plan")]
    app_meta = payload.get("app_metadata")
    if isinstance(app_meta, dict):
        candidates.append(app_meta.get("plan"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return None


def verify_bearer_plan(authorization):
    if not auth_enabled():
        return None
    raw = _parse_bearer(authorization)
    if not raw:
        return None
    payload = _decode_access_token(raw)
    if not payload:
        return None
    return _extract_plan(payload)


def reset_jwks_client_for_tests():
    global _cached_jwks_client
    _cached_jwks_client = None
