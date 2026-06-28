from typing import Any, Literal, TypedDict

from shared.entitlement import PLAN_PRO
from shared.supabase_auth import auth_enabled

CapabilityStatus = Literal["live", "coming"]


class CapabilitySpec(TypedDict, total=False):
    id: "Any"
    status: "Any"
    requires_plan: "Any"
    requires_auth: "Any"
    requires_opt_in: "Any"
    opt_in_key: "Any"


CAPABILITY_REGISTRY = (
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
        "status": "coming",
        "requires_plan": True,
        "requires_auth": True,
        "requires_opt_in": False,
    },
    {
        "id": "remote_access_tunnel",
        "status": "coming",
        "requires_plan": False,
        "requires_auth": True,
        "requires_opt_in": False,
    },
    {
        "id": "extended_palettes",
        "status": "coming",
        "requires_plan": True,
        "requires_auth": False,
        "requires_opt_in": False,
    },
)
CAPABILITY_IDS = frozenset(spec["id"] for spec in CAPABILITY_REGISTRY)
LIVE_CAPABILITY_IDS = frozenset(spec["id"] for spec in CAPABILITY_REGISTRY if spec.get("status") == "live")
COMING_CAPABILITY_IDS = frozenset(spec["id"] for spec in CAPABILITY_REGISTRY if spec.get("status") == "coming")


def _spec_by_id(capability_id):
    for spec in CAPABILITY_REGISTRY:
        if spec["id"] == capability_id:
            return spec
    return None


def resolve_capability(spec, *, plan, pro_settings):
    status = spec.get("status", "coming")
    enabled = False
    if status != "live":
        return {"status": status, "enabled": False}
    if spec.get("requires_plan", True) and plan != PLAN_PRO:
        return {"status": status, "enabled": False}
    if spec.get("requires_auth") and (not auth_enabled()):
        return {"status": status, "enabled": False}
    if spec.get("requires_opt_in"):
        key = spec.get("opt_in_key") or ""
        if not pro_settings.get(key):
            return {"status": status, "enabled": False}
    enabled = True
    return {"status": status, "enabled": enabled}


def resolve_capabilities(*, plan, pro_settings=None):
    settings = pro_settings if isinstance(pro_settings, dict) else {}
    out = {}
    for spec in CAPABILITY_REGISTRY:
        cap_id = spec["id"]
        out[cap_id] = resolve_capability(spec, plan=plan, pro_settings=settings)
    return out


def capability_enabled(capability_id, *, plan, pro_settings=None):
    spec = _spec_by_id(capability_id)
    if spec is None:
        return False
    resolved = resolve_capability(spec, plan=plan, pro_settings=pro_settings or {})
    return bool(resolved.get("enabled"))
