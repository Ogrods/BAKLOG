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


def ensure_profile_for_user(user_id: str, email: str | None = None) -> str:
    """Create ``profiles/<user_id>/`` and index entry on first login."""
    pid = profile_id_for_user(user_id)
    dest = profile_data_dir(pid)
    if dest.is_dir() and (dest / "data").is_dir() and _index_has_profile(pid):
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
    return pid
