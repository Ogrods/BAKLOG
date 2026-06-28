import json
import os
import sys
import time
from pathlib import Path

from shared.install_paths import data_root

PLAN_FREE = "free"
PLAN_PRO = "pro"
_PRO_ALIASES = ("pro", "paid", "premium")
_LAST_AUTH_PLAN = None
_AUTH_PLAN_TTL_SEC = 24 * 60 * 60
_LICENSE_REFRESH_AT = 0.0
_LICENSE_REFRESH_INTERVAL_SEC = 60 * 60


def _env_plan():
    raw = os.environ.get("BAKLOG_PLAN", "").strip().lower()
    if raw in _PRO_ALIASES:
        return PLAN_PRO
    if raw == PLAN_FREE:
        return PLAN_FREE
    return None


def license_path():
    override = os.environ.get("BAKLOG_LICENSE_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return data_root() / "license.json"


def read_license_document():
    try:
        doc = json.loads(license_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def write_license_document(doc):
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _local_license_plan():
    doc = read_license_document()
    if not doc:
        return None
    plan = doc.get("plan")
    if isinstance(plan, str) and plan.strip().lower() in _PRO_ALIASES:
        return PLAN_PRO
    return None


def maybe_refresh_local_license(*, force=False):
    global _LICENSE_REFRESH_AT
    if _auth_enabled():
        return
    try:
        from shared.polar_license import polar_configured, validate_license_key
    except Exception:
        return
    if not polar_configured():
        return
    doc = read_license_document()
    if not doc:
        return
    stored_key = doc.get("key")
    if not isinstance(stored_key, str) or not stored_key.strip():
        return
    now = time.time()
    if not force and now - _LICENSE_REFRESH_AT < _LICENSE_REFRESH_INTERVAL_SEC:
        return
    _LICENSE_REFRESH_AT = now
    result = validate_license_key(stored_key)
    if result.get("ok"):
        write_license_document(
            {
                **doc,
                "plan": PLAN_PRO,
                "key": stored_key.strip(),
                "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        return
    write_license_document(
        {
            "plan": PLAN_FREE,
            "key": stored_key.strip(),
            "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )


def activate_local_license_key(key):
    if _auth_enabled():
        return (False, "License keys are for local-only installs. Sign in to use account Pro.")
    try:
        from shared.polar_license import polar_configured, validate_license_key
    except Exception as exc:
        return (False, f"License activation unavailable ({exc})")
    if not polar_configured():
        return (False, "License activation isn't available right now. Try again later or contact support.")
    cleaned = (key or "").strip()
    if not cleaned:
        return (False, "Enter your license key.")
    result = validate_license_key(cleaned)
    if not result.get("ok"):
        return (False, result.get("error") or "Invalid or expired license key.")
    write_license_document(
        {"plan": PLAN_PRO, "key": cleaned, "validated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    )
    global _LICENSE_REFRESH_AT
    _LICENSE_REFRESH_AT = time.time()
    return (True, "BAKLOG Pro activated on this machine.")


def _auth_enabled():
    try:
        from shared.supabase_auth import auth_enabled

        return auth_enabled()
    except Exception:
        return False


def _verify_jwt_plan(authorization):
    try:
        from shared.supabase_auth import verify_bearer_plan

        return verify_bearer_plan(authorization)
    except Exception as exc:
        if os.environ.get("BAKLOG_DEBUG"):
            print(f"[entitlement] JWT plan verify failed: {exc!r}", file=sys.stderr)
        return None


def note_authenticated_plan(plan):
    global _LAST_AUTH_PLAN
    norm = PLAN_PRO if plan in _PRO_ALIASES else PLAN_FREE
    _LAST_AUTH_PLAN = (time.time(), norm)


def clear_authenticated_plan_cache():
    global _LAST_AUTH_PLAN
    _LAST_AUTH_PLAN = None


def clear_background_auth_caches():
    clear_authenticated_plan_cache()
    try:
        from shared.mirror_session import clear_mirror_session

        clear_mirror_session()
    except Exception:
        pass


def current_plan(authorization=None):
    if _auth_enabled():
        if authorization:
            claim = _verify_jwt_plan(authorization)
            if claim is not None:
                plan = PLAN_PRO if claim in _PRO_ALIASES else PLAN_FREE
                try:
                    from shared.comp_pro import is_comp_pro_email
                    from shared.supabase_auth import verify_bearer_user

                    user = verify_bearer_user(authorization)
                    email = (user or {}).get("email") or ""
                    if email and is_comp_pro_email(email):
                        plan = PLAN_PRO
                except Exception:
                    pass
                note_authenticated_plan(plan)
                try:
                    from shared.mirror_session import note_authenticated_mirror_session

                    note_authenticated_mirror_session(authorization)
                except Exception:
                    pass
                return plan
        return PLAN_FREE
    env = _env_plan()
    if env is not None:
        return env
    maybe_refresh_local_license()
    if _local_license_plan() == PLAN_PRO:
        return PLAN_PRO
    return PLAN_FREE


def is_pro(authorization=None):
    return current_plan(authorization) == PLAN_PRO


def is_pro_background():
    if _auth_enabled():
        if _LAST_AUTH_PLAN is not None:
            ts, plan = _LAST_AUTH_PLAN
            if time.time() - ts <= _AUTH_PLAN_TTL_SEC:
                return plan == PLAN_PRO
        return False
    env = _env_plan()
    if env is not None:
        return env == PLAN_PRO
    return _local_license_plan() == PLAN_PRO
