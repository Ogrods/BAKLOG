"""Resolve the current BAKLOG plan (free vs pro).

Enforcement is deliberately pragmatic for an MIT-licensed, local-first app. The
resolution matrix is:

| Supabase auth | bearer present | ``BAKLOG_PLAN`` | result |
|---------------|----------------|-----------------|--------|
| enabled       | valid JWT      | any             | signed ``plan`` claim |
| enabled       | missing/invalid| any             | ``free`` (env + license NOT consulted) |
| disabled      | n/a            | set             | env value (wins over license) |
| disabled      | n/a            | unset           | local ``license.json`` (honor system) |

- When Supabase auth is enabled, the plan comes ONLY from a SIGNED JWT claim
  (``shared.supabase_auth.verify_bearer_plan``), so it cannot be forged without
  a valid session. Both ``BAKLOG_PLAN`` and the editable ``license.json`` are
  local-only overrides, intentionally ignored in this mode so neither can be
  used to bypass the hosted entitlement moat.
- In pure-local mode (no Supabase), ``BAKLOG_PLAN`` (dev override) is honored
  first, then a local ``license.json``. That file is trivially editable by
  anyone with the source (MIT) — honor-system, by design. No DRM / anti-tamper.

Background work (the pro scheduler) has no per-request bearer, so authenticated
plan resolutions are cached process-side via :func:`note_authenticated_plan`
and read back by :func:`is_pro_background`.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from shared.install_paths import data_root

PLAN_FREE = "free"
PLAN_PRO = "pro"

# Strings (env or license file) that count as the paid tier.
_PRO_ALIASES = ("pro", "paid", "premium")

# Last plan resolved from a verified JWT this process, for request-less
# background work (the scheduler). ``(epoch_seconds, plan)``.
_LAST_AUTH_PLAN: tuple[float, str] | None = None
_AUTH_PLAN_TTL_SEC = 24 * 60 * 60


def _env_plan() -> str | None:
    raw = os.environ.get("BAKLOG_PLAN", "").strip().lower()
    if raw in _PRO_ALIASES:
        return PLAN_PRO
    if raw == PLAN_FREE:
        return PLAN_FREE
    return None


def license_path() -> Path:
    """Machine-local license file (pure-local mode). Override with BAKLOG_LICENSE_FILE."""
    override = os.environ.get("BAKLOG_LICENSE_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return data_root() / "license.json"


def _local_license_plan() -> str | None:
    try:
        doc = json.loads(license_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    plan = doc.get("plan")
    if isinstance(plan, str) and plan.strip().lower() in _PRO_ALIASES:
        return PLAN_PRO
    return None


def _auth_enabled() -> bool:
    """True when Supabase hosted auth is configured (lazy import, never raises)."""
    try:
        from shared.supabase_auth import auth_enabled

        return auth_enabled()
    except Exception:  # noqa: BLE001 - entitlement must never crash a request
        return False


def _verify_jwt_plan(authorization: str | None) -> str | None:
    """Return the signed plan claim for a bearer, or None on any failure.

    ``verify_bearer_plan`` already swallows invalid-token errors; the guard here
    only catches setup failures (e.g. ``jwt`` not installed) so entitlement
    resolution never crashes a request. Failures are logged under BAKLOG_DEBUG.
    """
    try:
        from shared.supabase_auth import verify_bearer_plan

        return verify_bearer_plan(authorization)
    except Exception as exc:  # noqa: BLE001 - entitlement must never crash a request
        if os.environ.get("BAKLOG_DEBUG"):
            print(f"[entitlement] JWT plan verify failed: {exc!r}", file=sys.stderr)
        return None


def note_authenticated_plan(plan: str) -> None:
    """Record a plan resolved from a verified JWT, for request-less background work."""
    global _LAST_AUTH_PLAN
    norm = PLAN_PRO if plan in _PRO_ALIASES else PLAN_FREE
    _LAST_AUTH_PLAN = (time.time(), norm)


def current_plan(authorization: str | None = None) -> str:
    """Resolve the effective plan. See module docstring for the resolution matrix."""
    if _auth_enabled():
        # Hosted auth: ONLY the signed JWT claim counts. Both BAKLOG_PLAN and
        # license.json are local-only overrides, deliberately ignored here so
        # neither can bypass the hosted entitlement moat. A missing/invalid
        # bearer resolves to free.
        if authorization:
            claim = _verify_jwt_plan(authorization)
            if claim is not None:
                plan = PLAN_PRO if claim in _PRO_ALIASES else PLAN_FREE
                note_authenticated_plan(plan)
                return plan
        return PLAN_FREE

    # Pure-local honor system: BAKLOG_PLAN dev override, then editable
    # license.json (MIT, no anti-tamper).
    env = _env_plan()
    if env is not None:
        return env
    if _local_license_plan() == PLAN_PRO:
        return PLAN_PRO

    return PLAN_FREE


def is_pro(authorization: str | None = None) -> bool:
    return current_plan(authorization) == PLAN_PRO


def is_pro_background() -> bool:
    """Best-effort pro check for server-side background work (no request context).

    Under hosted auth uses the last JWT-verified plan seen this process (within
    a TTL); in pure-local mode honors ``BAKLOG_PLAN`` then ``license.json``.
    Local overrides are ignored under hosted auth (same as ``current_plan``).
    """
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
