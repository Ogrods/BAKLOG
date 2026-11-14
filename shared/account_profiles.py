"""Map Supabase user ids to BAKLOG profile directories."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.profile_paths import (
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
            profiles.append({"id": pid, "label": label, "created_at": _now_iso()})
    _activate_account_profile(pid)
    return pid
