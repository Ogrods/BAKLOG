"""Profile index CRUD and first-add migration (copy root -> profiles/default/)."""

from __future__ import annotations

import base64
import hmac
import os
import shutil
import sys
import time
from datetime import UTC, datetime
from hashlib import scrypt
from pathlib import Path
from typing import Any

from shared import profile_paths
from shared.profile_paths import (
    DEFAULT_PROFILE_ID,
    get_active_profile_id,
    is_legacy_layout,
    load_index,
    mutate_index,
    normalize_profile_id,
    profile_data_dir,
    unique_profile_id_for_doc,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# Server-side cap mirroring the maxlength on the create/rename inputs in index.html.
LABEL_MAX_LEN = 64


def _validate_label(label: str) -> str:
    """Normalize + length-check a profile label (server-side; HTML maxlength is cosmetic)."""
    label = (label or "").strip()
    if not label:
        raise ValueError("label is required")
    if len(label) > LABEL_MAX_LEN:
        raise ValueError(f"label must be {LABEL_MAX_LEN} characters or fewer")
    return label


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


def _copy_file_if_missing(src: Path, dst: Path) -> bool:
    if not src.is_file():
        return False
    if dst.exists():
        return False
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return True
    except OSError as exc:
        print(f"[profiles] copy failed {src} -> {dst}: {exc!r}", file=sys.stderr, flush=True)
        return False


def _copy_tree_if_missing(
    src: Path,
    dst: Path,
    *,
    skip_dir_names: frozenset[str] | None = None,
) -> int:
    """Copy files that are missing at dst. Returns count of files copied."""
    if not src.exists():
        return 0
    copied = 0
    if src.is_file():
        if _copy_file_if_missing(src, dst):
            copied += 1
        return copied
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        if skip_dir_names and child.is_dir() and child.name in skip_dir_names:
            continue
        target = dst / child.name
        if child.is_dir():
            copied += _copy_tree_if_missing(child, target, skip_dir_names=skip_dir_names)
        elif _copy_file_if_missing(child, target):
            copied += 1
    return copied


def _quarantine_profile_dir(profile_id: str, dest: Path) -> Path:
    """Move a profile tree aside so boot reconcile cannot re-adopt it."""
    profile_paths.PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    trash = profile_paths.PROFILES_DIR / f".trash-{profile_id}-{stamp}"
    try:
        dest.rename(trash)
        return trash
    except OSError:
        return dest


def _remove_profile_dir(dest: Path) -> None:
    if not dest.is_dir():
        return
    shutil.rmtree(dest, ignore_errors=True)
    if dest.is_dir():
        print(
            f"[profiles] WARN: profile dir still present after delete: {dest}",
            file=sys.stderr,
            flush=True,
        )


def finalize_default_profile_migration() -> None:
    """Complete root -> profiles/default/ when legacy layout still applies to default."""
    if is_legacy_layout(DEFAULT_PROFILE_ID):
        ensure_default_profile_dir()


def ensure_default_profile_dir() -> Path:
    """Copy repo-root data into profiles/default/ (resumable: copy-if-missing)."""
    dest = profile_data_dir(DEFAULT_PROFILE_ID)
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for pattern in (_MIGRATION_GLOB,):
        for src in profile_paths.ROOT.glob(pattern):
            if src.is_file() and _copy_file_if_missing(src, dest / src.name):
                copied += 1
    for name in _MIGRATION_FILES:
        src = profile_paths.ROOT / name
        if _copy_file_if_missing(src, dest / name):
            copied += 1
    data_src = profile_paths.ROOT / "data"
    if data_src.is_dir():
        copied += _copy_tree_if_missing(data_src, dest / "data")
    auth_src = profile_paths.ROOT / "cache" / "auth"
    if auth_src.is_dir():
        copied += _copy_auth_for_migration(auth_src, dest / "cache" / "auth")
    epic_src = profile_paths.ROOT / "cache" / "epic"
    if epic_src.is_dir():
        copied += _copy_tree_if_missing(epic_src, dest / "cache" / "epic")
    if copied:
        print(f"[profiles] migrated {copied} file(s) into profiles/default/", flush=True)
    marker = profile_paths.migration_complete_path(profile_paths.DEFAULT_PROFILE_ID)
    marker.parent.mkdir(parents=True, exist_ok=True)
    if not marker.is_file():
        marker.write_text(profile_paths._now_iso(), encoding="utf-8")
    return dest


def _copy_auth_for_migration(auth_src: Path, dest_auth: Path) -> int:
    """Copy encrypted secrets + shallow provider files; skip browser profile trees."""
    copied = 0
    dest_auth.mkdir(parents=True, exist_ok=True)
    for name in ("secrets.bin", ".master_key", ".mpw.salt"):
        if _copy_file_if_missing(auth_src / name, dest_auth / name):
            copied += 1
    profiles_src = auth_src / "profiles"
    if not profiles_src.is_dir():
        return copied
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
            if _copy_file_if_missing(item, target):
                copied += 1
    return copied


def create_profile(label: str) -> dict[str, Any]:
    """Add a new empty profile; migrates legacy root into profiles/default/ first."""
    label = _validate_label(label)
    if is_legacy_layout():
        ensure_default_profile_dir()
    profile_id: str
    with mutate_index() as doc:
        profile_id = unique_profile_id_for_doc(label, doc)
        profiles = doc.setdefault("profiles", [])
        if not isinstance(profiles, list):
            profiles = []
            doc["profiles"] = profiles
        profiles.append({"id": profile_id, "label": label, "created_at": _now_iso()})
    dest = profile_data_dir(profile_id)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "data").mkdir(parents=True, exist_ok=True)
        try:
            from auth.manager import seed_new_profile_auth_defaults

            seed_new_profile_auth_defaults(profile_id)
        except Exception:
            pass
    except Exception:
        with mutate_index() as doc:
            doc["profiles"] = [
                p
                for p in doc.get("profiles", [])
                if not (isinstance(p, dict) and p.get("id") == profile_id)
            ]
        _remove_profile_dir(dest)
        raise
    return {"id": profile_id, "label": label}


def set_active_profile(profile_id: str) -> dict[str, Any]:
    profile_id = normalize_profile_id(profile_id)
    with mutate_index() as doc:
        ids = {
            str(p["id"])
            for p in doc.get("profiles", [])
            if isinstance(p, dict) and p.get("id")
        }
        if profile_id not in ids:
            raise ValueError(f"unknown profile: {profile_id}")
        doc["active"] = profile_id
        label = profile_id
        for p in doc.get("profiles", []):
            if isinstance(p, dict) and p.get("id") == profile_id:
                label = str(p.get("label") or profile_id)
                break
    return {"active": profile_id, "label": label}


def rename_profile(profile_id: str, label: str) -> dict[str, Any]:
    profile_id = normalize_profile_id(profile_id)
    label = _validate_label(label)
    with mutate_index() as doc:
        found = False
        for p in doc.get("profiles", []):
            if isinstance(p, dict) and p.get("id") == profile_id:
                p["label"] = label
                found = True
                break
        if not found:
            raise ValueError(f"unknown profile: {profile_id}")
    return {"id": profile_id, "label": label}


def delete_profile(profile_id: str, current_pin: str | None = None) -> None:
    profile_id = normalize_profile_id(profile_id)
    with mutate_index() as doc:
        profiles = [p for p in doc.get("profiles", []) if isinstance(p, dict)]
        if len(profiles) <= 1:
            raise ValueError("cannot delete the last profile")
        if get_active_profile_id(doc=doc) == profile_id:
            raise ValueError("cannot delete the active profile — switch first")
        if profile_has_pin(profile_id, doc):
            limit_err = pin_rate_limit_error(profile_id)
            if limit_err:
                raise ValueError(limit_err)
            if not current_pin or not verify_profile_pin(profile_id, current_pin, doc):
                record_pin_failure(profile_id)
                raise ValueError("current PIN is incorrect")
        remaining = [p for p in profiles if p.get("id") != profile_id]
        if len(remaining) == len(profiles):
            raise ValueError(f"unknown profile: {profile_id}")
        doc["profiles"] = remaining
    clear_pin_failures(profile_id)
    dest = profile_data_dir(profile_id)
    if dest.is_dir():
        trash = _quarantine_profile_dir(profile_id, dest)
        _remove_profile_dir(trash)


PIN_MIN_LEN = 4
PIN_MAX_LEN = 32
_PIN_SCRYPT_N = 2**14
_PIN_SCRYPT_R = 8
_PIN_SCRYPT_P = 1
_PIN_MAX_ATTEMPTS = 5
_PIN_LOCK_SECONDS = 30

_pin_failures: dict[str, list[float]] = {}
_pin_lock_until: dict[str, float] = {}


def _profile_entry(doc: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    for p in doc.get("profiles", []):
        if isinstance(p, dict) and p.get("id") == profile_id:
            return p
    return None


def profile_has_pin(profile_id: str, doc: dict[str, Any] | None = None) -> bool:
    doc = doc if doc is not None else load_index()
    p = _profile_entry(doc, profile_id)
    pin_meta = p.get("pin") if isinstance(p, dict) else None
    return bool(isinstance(pin_meta, dict) and pin_meta.get("hash") and pin_meta.get("salt"))


def profile_requires_pin(profile_id: str) -> bool:
    return profile_has_pin(profile_id)


def _hash_pin(pin: str, salt: bytes) -> bytes:
    return scrypt(
        pin.encode("utf-8"),
        salt=salt,
        n=_PIN_SCRYPT_N,
        r=_PIN_SCRYPT_R,
        p=_PIN_SCRYPT_P,
        dklen=32,
    )


def verify_profile_pin(profile_id: str, pin: str, doc: dict[str, Any] | None = None) -> bool:
    doc = doc if doc is not None else load_index()
    profile_id = normalize_profile_id(profile_id)
    if not profile_has_pin(profile_id, doc):
        return True
    p = _profile_entry(doc, profile_id)
    assert isinstance(p, dict)
    pin_meta = p.get("pin")
    assert isinstance(pin_meta, dict)
    try:
        salt = base64.b64decode(str(pin_meta.get("salt") or ""))
        expected = base64.b64decode(str(pin_meta.get("hash") or ""))
    except (ValueError, TypeError):
        return False
    actual = _hash_pin((pin or "").strip(), salt)
    return hmac.compare_digest(actual, expected)


def pin_rate_limit_error(profile_id: str) -> str | None:
    until = _pin_lock_until.get(profile_id, 0.0)
    if time.time() < until:
        return f"too many PIN attempts - try again in {_PIN_LOCK_SECONDS} seconds"
    return None


def record_pin_failure(profile_id: str) -> None:
    now = time.time()
    failures = _pin_failures.setdefault(profile_id, [])
    failures[:] = [t for t in failures if now - t < 300]
    failures.append(now)
    if len(failures) >= _PIN_MAX_ATTEMPTS:
        _pin_lock_until[profile_id] = now + _PIN_LOCK_SECONDS


def clear_pin_failures(profile_id: str) -> None:
    _pin_failures.pop(profile_id, None)
    _pin_lock_until.pop(profile_id, None)


def set_profile_pin(profile_id: str, pin: str, current_pin: str | None = None) -> None:
    profile_id = normalize_profile_id(profile_id)
    pin = (pin or "").strip()
    if len(pin) < PIN_MIN_LEN or len(pin) > PIN_MAX_LEN:
        raise ValueError(f"PIN must be {PIN_MIN_LEN}-{PIN_MAX_LEN} characters")
    with mutate_index() as doc:
        p = _profile_entry(doc, profile_id)
        if not isinstance(p, dict):
            raise ValueError(f"unknown profile: {profile_id}")
        if profile_has_pin(profile_id, doc):
            limit_err = pin_rate_limit_error(profile_id)
            if limit_err:
                raise ValueError(limit_err)
            if not current_pin or not verify_profile_pin(profile_id, current_pin, doc):
                record_pin_failure(profile_id)
                raise ValueError("current PIN is incorrect")
            clear_pin_failures(profile_id)
        salt = os.urandom(16)
        p["pin"] = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(_hash_pin(pin, salt)).decode("ascii"),
            "n": _PIN_SCRYPT_N,
        }


def clear_profile_pin(profile_id: str, current_pin: str) -> None:
    profile_id = normalize_profile_id(profile_id)
    with mutate_index() as doc:
        p = _profile_entry(doc, profile_id)
        if not isinstance(p, dict):
            raise ValueError(f"unknown profile: {profile_id}")
        if profile_has_pin(profile_id, doc):
            limit_err = pin_rate_limit_error(profile_id)
            if limit_err:
                raise ValueError(limit_err)
            if not verify_profile_pin(profile_id, current_pin, doc):
                record_pin_failure(profile_id)
                raise ValueError("current PIN is incorrect")
        p.pop("pin", None)
    clear_pin_failures(profile_id)


def _public_profile_row(p: dict[str, Any], doc: dict[str, Any]) -> dict[str, Any]:
    pid = str(p.get("id") or "")
    return {
        "id": pid,
        "label": p.get("label"),
        "created_at": p.get("created_at"),
        "hasPin": profile_has_pin(pid, doc) if pid else False,
    }


def profiles_status() -> dict[str, Any]:
    doc = load_index()
    active = get_active_profile_id(doc=doc)
    profiles = doc.get("profiles") if isinstance(doc.get("profiles"), list) else []
    active_entry = _profile_entry(doc, active)
    active_label = (
        str(active_entry.get("label") or active)
        if isinstance(active_entry, dict)
        else active
    )
    return {
        "active": active,
        "active_label": active_label,
        "legacy": is_legacy_layout(active),
        "profiles": [
            _public_profile_row(p, doc)
            for p in profiles
            if isinstance(p, dict) and p.get("id")
        ],
    }
