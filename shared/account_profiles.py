from datetime import UTC, datetime

from shared.profile_paths import is_valid_profile_id, load_index, mutate_index, normalize_profile_id, profile_data_dir


def _now_iso():
    return datetime.now(UTC).isoformat()


def profile_id_for_user(user_id):
    uid = (user_id or "").strip().lower()
    if not is_valid_profile_id(uid):
        raise ValueError(f"invalid Supabase user id for profile: {user_id!r}")
    return normalize_profile_id(uid)


def _index_has_profile(pid):
    doc = load_index()
    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        return False
    return any(isinstance(p, dict) and p.get("id") == pid for p in profiles)


def ensure_profile_for_user(user_id, email=None):
    pid = profile_id_for_user(user_id)
    dest = profile_data_dir(pid)
    if dest.is_dir() and (dest / "data").is_dir() and _index_has_profile(pid):
        return pid
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(parents=True, exist_ok=True)
    with mutate_index() as doc:
        profiles = doc.get("profiles")
        if not isinstance(profiles, list):
            profiles = []
            doc["profiles"] = profiles
        if not any(isinstance(p, dict) and p.get("id") == pid for p in profiles):
            label = (email or "").strip() or f"Account {pid[:8]}"
            profiles.append({"id": pid, "label": label, "created_at": _now_iso()})
    return pid
