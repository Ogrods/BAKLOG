"""Map Supabase user ids to BAKLOG profile directories."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.profile_paths import (
    get_active_profile_id,
    is_valid_profile_id,
    load_index,
    mutate_index,
    normalize_profile_id,
    profile_data_dir,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def profile_id_for_user(user_id: str) -> str:
    """Supabase ``sub`` is a UUID; use it as the profile id."""
    uid = (user_id or "").strip().lower()
    if not is_valid_profile_id(uid):
        raise ValueError(f"invalid Supabase user id for profile: {user_id!r}")
    return normalize_profile_id(uid)


def _index_has_profile(pid: str) -> bool:
    doc = load_index()
    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        return False
    return any(isinstance(p, dict) and p.get("id") == pid for p in profiles)


def _find_profile_entry(profile_id: str) -> dict[str, Any] | None:
    doc = load_index()
    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        return None
    for p in profiles:
        if isinstance(p, dict) and p.get("id") == profile_id:
            return p
    return None


def _activate_account_profile(pid: str) -> None:
    """Point index.active at the signed-in account profile.

    Account-auth mode (Supabase on, BAKLOG_LOCAL_PROFILES off) pins request
    data to the user id via set_request_profile_id, but the Pro background
    scheduler still reads profiles/index.json. Leaving active on an empty
    leftover ``default`` makes Steam refresh fail every stagger window while
    the UI only shows the email profile.
    """
    from shared.supabase_auth import local_profiles_enabled

    if local_profiles_enabled():
        return
    with mutate_index() as doc:
        if doc.get("active") == pid:
            return
        doc["active"] = pid


def ensure_profile_for_user(user_id: str, email: str | None = None) -> str:
    """Create ``profiles/<user_id>/`` and index entry on first login."""
    pid = profile_id_for_user(user_id)
    dest = profile_data_dir(pid)
    if dest.is_dir() and (dest / "data").is_dir() and _index_has_profile(pid):
        _activate_account_profile(pid)
        return pid

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(parents=True, exist_ok=True)

    with mutate_index() as doc:
        profiles: list[dict[str, Any]] = doc.get("profiles")  # type: ignore[assignment]
        if not isinstance(profiles, list):
            profiles = []
            doc["profiles"] = profiles
        if not any(isinstance(p, dict) and p.get("id") == pid for p in profiles):
            label = (email or "").strip() or f"Account {pid[:8]}"
            profiles.append(
                {
                    "id": pid,
                    "label": label,
                    "created_at": _now_iso(),
                    "owner_user_id": pid,
                }
            )
    _activate_account_profile(pid)
    return pid


def _claim_profile_owner(profile_id: str, user_id: str) -> None:
    """Stamp owner_user_id on a legacy unowned local profile (first authenticated use)."""
    owner = (user_id or "").strip().lower()
    if not owner:
        return
    with mutate_index() as doc:
        profiles = doc.get("profiles")
        if not isinstance(profiles, list):
            return
        for p in profiles:
            if isinstance(p, dict) and p.get("id") == profile_id:
                if p.get("owner_user_id"):
                    return
                p["owner_user_id"] = owner
                return


def profile_accessible_to_user(profile_id: str, user_id: str) -> bool:
    """Whether ``user_id`` may read/write ``profile_id`` when local profiles coexist with auth."""
    account_pid = profile_id_for_user(user_id)
    pid = normalize_profile_id(profile_id)
    if pid == account_pid:
        return True
    entry = _find_profile_entry(pid)
    if entry is None:
        return False
    owner = str(entry.get("owner_user_id") or "").strip().lower()
    if owner:
        return owner == account_pid
    # Unowned UUID folder that is not this account → treat as another account's library.
    if pid != account_pid and len(pid) >= 32 and "-" in pid:
        return False
    # Legacy Work/Play/default: claim for this user on first authenticated touch.
    _claim_profile_owner(pid, account_pid)
    return True


def resolve_request_profile_for_user(user_id: str, account_pid: str | None = None) -> str:
    """Pick the profile to pin for this request.

    Account-auth (local profiles off): always the account profile.
    Local profiles on: active from index when owned/allowed; else fall back to account.
    """
    from shared.supabase_auth import local_profiles_enabled

    account = account_pid or profile_id_for_user(user_id)
    if not local_profiles_enabled():
        return account
    active = get_active_profile_id()
    if profile_accessible_to_user(active, user_id):
        return normalize_profile_id(active)
    return account
