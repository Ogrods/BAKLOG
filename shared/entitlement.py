"""Resolve the current BAKLOG plan (free vs pro).

Enforcement is deliberately pragmatic for an MIT-licensed, local-first app:

- When Supabase auth is enabled, the plan comes from a SIGNED JWT claim
  (``shared.supabase_auth.verify_bearer_plan``), so it cannot be forged without
  a valid session — real deterrence.
- In pure-local mode (no Supabase), a local ``license.json`` is honored. That
  file is trivially editable by anyone with the source (MIT) — honor-system, by
  design. No DRM / anti-tamper.
- ``BAKLOG_PLAN`` env var overrides both, for dev/testing.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from shared.install_paths import data_root

PLAN_FREE = "free"
PLAN_PRO = "pro"

# Strings (env or license file) that count as the paid tier.
_PRO_ALIASES = ("pro", "paid", "premium")


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


def current_plan(authorization: str | None = None) -> str:
    """Resolve the effective plan.

    Order: ``BAKLOG_PLAN`` env override, signed Supabase JWT claim (when an
    Authorization header is supplied), then the local license file. Defaults to
    ``free``.
    """
    env = _env_plan()
    if env is not None:
        return env

    if authorization:
        try:
            from shared.supabase_auth import verify_bearer_plan

            claim = verify_bearer_plan(authorization)
        except Exception:  # noqa: BLE001 - entitlement must never crash a request
            claim = None
        if claim in _PRO_ALIASES:
            return PLAN_PRO

    if _local_license_plan() == PLAN_PRO:
        return PLAN_PRO

    return PLAN_FREE


def is_pro(authorization: str | None = None) -> bool:
    return current_plan(authorization) == PLAN_PRO
