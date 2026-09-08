"""Pro capability registry for GET /api/config.

``cloud_sync_mirror`` is live for Pro accounts that opt in on Connections.
"""

from __future__ import annotations

from typing import Any, Literal

from shared.entitlement import PLAN_PRO
from shared.supabase_auth import auth_enabled

CapabilityStatus = Literal["live", "soon", "off"]

CAPABILITY_REGISTRY: tuple[dict[str, Any], ...] = (
    {"id": "no_ads", "status": "live", "requires_plan": True, "requires_auth": False, "requires_opt_in": False},
    {
        "id": "queue_bulk_refresh",
        "status": "live",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
    {
        "id": "scheduled_stale_refresh",
        "status": "live",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
    {
        "id": "silent_connection_probe",
        "status": "live",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
    {
        "id": "bonus_claimables",
        "status": "live",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
    {
        "id": "deep_achievement_sync",
        "status": "live",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
    {
        "id": "cloud_sync_mirror",
        "status": "live",
        "requires_plan": True,
        "requires_auth": True,
        "requires_opt_in": True,
        "opt_in_key": "cloudMirrorEnabled",
    },
    {
        "id": "deal_watchlist_alerts",
        "status": "soon",
        "requires_plan": True,
        "requires_auth": True,
        "requires_opt_in": False,
    },
    {
        "id": "remote_access_tunnel",
        "status": "soon",
        "requires_plan": False,
        "requires_auth": True,
        "requires_opt_in": False,
    },
    {
        "id": "extended_palettes",
        "status": "soon",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
)

CAPABILITY_IDS = frozenset(spec["id"] for spec in CAPABILITY_REGISTRY)


def _spec_by_id(capability_id: str) -> dict[str, Any] | None:
    for spec in CAPABILITY_REGISTRY:
        if spec["id"] == capability_id:
            return dict(spec)
    return None


def resolve_capability(spec: dict[str, Any], *, plan: str, pro_settings: dict[str, Any]) -> dict[str, Any]:
    status = spec.get("status", "soon")
    if status == "off":
        return {"status": "off", "enabled": False}
    if status != "live":
        return {"status": status, "enabled": False}
    if spec.get("requires_plan", True) and plan != PLAN_PRO:
        return {"status": status, "enabled": False}
    if spec.get("requires_auth") and not auth_enabled():
        return {"status": status, "enabled": False}
    if spec.get("requires_opt_in"):
        key = spec.get("opt_in_key") or ""
        if not pro_settings.get(key):
            return {"status": status, "enabled": False}
    return {"status": status, "enabled": True}


def resolve_capabilities(*, plan: str, pro_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = pro_settings if isinstance(pro_settings, dict) else {}
    out: dict[str, Any] = {}
    for spec in CAPABILITY_REGISTRY:
        out[spec["id"]] = resolve_capability(spec, plan=plan, pro_settings=settings)
    return out


def capability_enabled(capability_id: str, *, plan: str, pro_settings: dict[str, Any] | None = None) -> bool:
    spec = _spec_by_id(capability_id)
    if spec is None:
        return False
    resolved = resolve_capability(spec, plan=plan, pro_settings=pro_settings or {})
    return bool(resolved.get("enabled"))


def capability_registry_status(capability_id: str) -> CapabilityStatus:
    """Registry status for a capability id, ignoring plan and opt-in."""
    spec = _spec_by_id(capability_id)
    if spec is None:
        return "off"
    status = spec.get("status", "soon")
    if status in ("live", "soon", "off"):
        return status  # type: ignore[return-value]
    return "soon"
