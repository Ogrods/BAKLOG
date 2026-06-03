"""Profile index CRUD and first-add migration (copy root -> profiles/default/)."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shared import profile_paths
from shared.profile_paths import (
    DEFAULT_PROFILE_ID,
    is_legacy_layout,
    list_profiles,
    load_index,
    profile_data_dir,
    profile_label,
    save_index,
    unique_profile_id,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# Root artifacts copied into profiles/default/ on first multi-profile add.
_MIGRATION_GLOB = "games_*.json"
_MIGRATION_FILES = ("itad_prices.json",)
# Browser profile trees we skip when seeding profiles/default/ (cookies DBs still copy).
_AUTH_SKIP_DIR_NAMES = frozenset(
    {
        "Extensions",
        "Cache",
        "Code Cache",
        "GPUCache",
        "Service Worker",
        "IndexedDB",
        "blob_storage",
        "Default",
    }
)
_MAX_AUTH_FILE_REL_LEN = 180


def _copy_tree(src: Path, dst: Path, *, skip_dir_names: frozenset[str] | None = None) -> None:
    if not src.exists():
        return
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if skip_dir_names and child.is_dir() and child.name in skip_dir_names:
            continue
        target = dst / child.name
        if child.is_dir():
            _copy_tree(child, target, skip_dir_names=skip_dir_names)
        else:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, target)
            except OSError:
                pass


def ensure_default_profile_dir() -> Path:
    """One-time copy of repo-root data into profiles/default/ (idempotent)."""
    dest = profile_data_dir(DEFAULT_PROFILE_ID)
    if dest.is_dir():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    for pattern in (_MIGRATION_GLOB,):
        for src in profile_paths.ROOT.glob(pattern):
            if src.is_file():
                shutil.copy2(src, dest / src.name)
    for name in _MIGRATION_FILES:
        src = profile_paths.ROOT / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    data_src = profile_paths.ROOT / "data"
    if data_src.is_dir():
        _copy_tree(data_src, dest / "data")
    auth_src = profile_paths.ROOT / "cache" / "auth"
    if auth_src.is_dir():
        _copy_auth_for_migration(auth_src, dest / "cache" / "auth")
    epic_src = profile_paths.ROOT / "cache" / "epic"
    if epic_src.is_dir():
        _copy_tree(epic_src, dest / "cache" / "epic")
    return dest


def _copy_auth_for_migration(auth_src: Path, dest_auth: Path) -> None:
    """Copy encrypted secrets + shallow provider files; skip browser profile trees."""
    dest_auth.mkdir(parents=True, exist_ok=True)
    for name in ("secrets.bin", ".master_key", ".mpw.salt"):
        src = auth_src / name
        if src.is_file():
            shutil.copy2(src, dest_auth / name)
    profiles_src = auth_src / "profiles"
    if not profiles_src.is_dir():
        return
    for provider in profiles_src.iterdir():
        if not provider.is_dir():
            continue
        for item in provider.rglob("*"):
            if not item.is_file():
                continue
            rel = item.relative_to(provider)
            if len(str(rel)) > _MAX_AUTH_FILE_REL_LEN:
                continue
            if any(part in _AUTH_SKIP_DIR_NAMES for part in rel.parts):
                continue
            target = dest_auth / "profiles" / provider.name / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
            except OSError:
                pass


def create_profile(label: str) -> dict[str, Any]:
    """Add a new empty profile; migrates legacy root into profiles/default/ first."""
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required")
    if is_legacy_layout():
        ensure_default_profile_dir()
    profile_id = unique_profile_id(label)
    dest = profile_data_dir(profile_id)
    if dest.exists():
        raise ValueError(f"profile directory already exists: {profile_id}")
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "data").mkdir(parents=True, exist_ok=True)
    doc = load_index()
    profiles = doc.setdefault("profiles", [])
    if not isinstance(profiles, list):
        profiles = []
        doc["profiles"] = profiles
    profiles.append({"id": profile_id, "label": label, "created_at": _now_iso()})
    save_index(doc)
    return {"id": profile_id, "label": label}


def set_active_profile(profile_id: str) -> dict[str, Any]:
    ids = {p["id"] for p in list_profiles()}
    if profile_id not in ids:
        raise ValueError(f"unknown profile: {profile_id}")
    doc = load_index()
    doc["active"] = profile_id
    save_index(doc)
    return {"active": profile_id, "label": profile_label(profile_id)}


def rename_profile(profile_id: str, label: str) -> dict[str, Any]:
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required")
    doc = load_index()
    found = False
    for p in doc.get("profiles", []):
        if isinstance(p, dict) and p.get("id") == profile_id:
            p["label"] = label
            found = True
            break
    if not found:
        raise ValueError(f"unknown profile: {profile_id}")
    save_index(doc)
    return {"id": profile_id, "label": label}


def delete_profile(profile_id: str) -> None:
    if profile_id == DEFAULT_PROFILE_ID and is_legacy_layout():
        raise ValueError("cannot delete default profile while using legacy layout")
    doc = load_index()
    profiles = [p for p in doc.get("profiles", []) if isinstance(p, dict)]
    if len(profiles) <= 1:
        raise ValueError("cannot delete the last profile")
    if doc.get("active") == profile_id:
        raise ValueError("cannot delete the active profile — switch first")
    remaining = [p for p in profiles if p.get("id") != profile_id]
    if len(remaining) == len(profiles):
        raise ValueError(f"unknown profile: {profile_id}")
    doc["profiles"] = remaining
    save_index(doc)
    dest = profile_data_dir(profile_id)
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)


def profiles_status() -> dict[str, Any]:
    active = load_index().get("active") or DEFAULT_PROFILE_ID
    return {
        "active": active,
        "active_label": profile_label(active),
        "legacy": is_legacy_layout(active),
        "profiles": list_profiles(),
    }
