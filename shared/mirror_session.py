"""Process-scoped Supabase session cache for background cloud mirror uploads.

The mirror flush worker has no HTTP request context; it reuses the last
verified bearer token seen on an authenticated API call (same TTL pattern as
``note_authenticated_plan`` in shared/entitlement.py).
"""

from __future__ import annotations

import time

_SESSION_TTL_SEC = 24 * 60 * 60
_LAST_MIRROR_SESSION: tuple[float, str, str] | None = None  # epoch, user_id, bearer


def note_authenticated_mirror_session(authorization: str | None) -> None:
    """Record user id + bearer after a verified JWT (best-effort)."""
    global _LAST_MIRROR_SESSION
    if not authorization:
        return
    try:
        from shared.supabase_auth import auth_enabled, verify_bearer_user
    except Exception:  # noqa: BLE001
        return
    if not auth_enabled():
        return
    user = verify_bearer_user(authorization)
    if not user:
        return
    user_id = str(user.get("id") or "").strip()
    if not user_id:
        return
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return
    token = parts[1].strip()
    if not token:
        return
    _LAST_MIRROR_SESSION = (time.time(), user_id, token)


def get_mirror_session() -> tuple[str, str] | None:
    """Return ``(user_id, bearer_token)`` when a fresh cached session exists."""
    if _LAST_MIRROR_SESSION is None:
        return None
    ts, user_id, token = _LAST_MIRROR_SESSION
    if time.time() - ts > _SESSION_TTL_SEC:
        return None
    if not user_id or not token:
        return None
    return user_id, token


def clear_mirror_session_for_tests() -> None:
    global _LAST_MIRROR_SESSION
    _LAST_MIRROR_SESSION = None
