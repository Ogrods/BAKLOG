"""Process-local bearer cache for background mirror uploads."""

from __future__ import annotations

import time

_SESSION_TTL_SEC = 60 * 60
# (noted_at, user_id, token)
_LAST_MIRROR_SESSION: tuple[float, str, str] | None = None


def note_authenticated_mirror_session(authorization: str | None, *, user_id: str | None = None) -> None:
    """Cache a verified bearer for background uploads (keyed to one account)."""
    global _LAST_MIRROR_SESSION
    if not authorization:
        return
    try:
        from shared.supabase_auth import auth_enabled, verify_bearer_user
    except Exception:
        return
    if not auth_enabled():
        return
    resolved_user_id = (user_id or "").strip()
    if not resolved_user_id:
        user = verify_bearer_user(authorization)
        if not user:
            return
        resolved_user_id = str(user.get("id") or "").strip()
    if not resolved_user_id:
        return
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return
    token = parts[1].strip()
    if not token:
        return
    _LAST_MIRROR_SESSION = (time.time(), resolved_user_id, token)


def get_mirror_session(*, expect_user_id: str | None = None) -> tuple[str, str] | None:
    """Return ``(user_id, token)`` or None when expired / mismatched."""
    if _LAST_MIRROR_SESSION is None:
        return None
    ts, user_id, token = _LAST_MIRROR_SESSION
    if time.time() - ts > _SESSION_TTL_SEC:
        return None
    if not user_id or not token:
        return None
    if expect_user_id is not None and user_id != expect_user_id:
        return None
    return (user_id, token)


def clear_mirror_session() -> None:
    global _LAST_MIRROR_SESSION
    _LAST_MIRROR_SESSION = None


def clear_mirror_session_for_tests() -> None:
    clear_mirror_session()
