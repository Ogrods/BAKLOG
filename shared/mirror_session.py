import time

_SESSION_TTL_SEC = 60 * 60
_LAST_MIRROR_SESSION = None


def note_authenticated_mirror_session(authorization):
    global _LAST_MIRROR_SESSION
    if not authorization:
        return
    try:
        from shared.supabase_auth import auth_enabled, verify_bearer_user
    except Exception:
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


def get_mirror_session():
    if _LAST_MIRROR_SESSION is None:
        return None
    ts, user_id, token = _LAST_MIRROR_SESSION
    if time.time() - ts > _SESSION_TTL_SEC:
        return None
    if not user_id or not token:
        return None
    return (user_id, token)


def clear_mirror_session():
    global _LAST_MIRROR_SESSION
    _LAST_MIRROR_SESSION = None


def clear_mirror_session_for_tests():
    clear_mirror_session()
