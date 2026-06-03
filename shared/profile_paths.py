"""Resolve data paths for the active local profile (legacy root vs profiles/<id>/)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILES_DIR = ROOT / "profiles"
INDEX_FILE = PROFILES_DIR / "index.json"
DEFAULT_PROFILE_ID = "default"
_ENV_OVERRIDE = "BAKLOG_PROFILE"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_index() -> dict[str, Any]:
    return {
        "active": DEFAULT_PROFILE_ID,
        "profiles": [
            {"id": DEFAULT_PROFILE_ID, "label": "Default", "created_at": _now_iso()},
        ],
    }


def load_index() -> dict[str, Any]:
    if not INDEX_FILE.exists():
        return _empty_index()
    try:
        doc = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_index()
    if not isinstance(doc, dict):
        return _empty_index()
    doc.setdefault("active", DEFAULT_PROFILE_ID)
    profiles = doc.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        doc["profiles"] = _empty_index()["profiles"]
    return doc


def save_index(doc: dict[str, Any]) -> None:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX_FILE)


def get_active_profile_id() -> str:
    override = os.environ.get(_ENV_OVERRIDE, "").strip()
    if override:
        return override
    return str(load_index().get("active") or DEFAULT_PROFILE_ID)


def profile_data_dir(profile_id: str) -> Path:
    return PROFILES_DIR / profile_id


def is_legacy_layout(profile_id: str | None = None) -> bool:
    """True when this profile's data lives at repo root (pre-migration installs)."""
    pid = profile_id if profile_id is not None else get_active_profile_id()
    if pid != DEFAULT_PROFILE_ID:
        return False
    return not profile_data_dir(DEFAULT_PROFILE_ID).is_dir()


def profile_root(profile_id: str | None = None) -> Path:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    if is_legacy_layout(pid):
        return ROOT
    return profile_data_dir(pid)


def catalog_path(filename: str, *, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / filename


def itad_path(*, profile_id: str | None = None) -> Path:
    return catalog_path("itad_prices.json", profile_id=profile_id)


def personal_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "data"


def personal_path(*, profile_id: str | None = None) -> Path:
    return personal_dir(profile_id=profile_id) / "personal.json"


def personal_backup_dir(*, profile_id: str | None = None) -> Path:
    return personal_dir(profile_id=profile_id) / "personal_backups"


def auth_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache" / "auth"


def epic_cache_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache" / "epic"


def runs_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache" / "runs"


def resolve_catalog_path(path: Path, *, profile_id: str | None = None) -> Path:
    """Map a relative games_*.json / itad path to the active profile root."""
    if path.is_absolute():
        return path
    name = path.name
    if name.startswith("games_") and name.endswith(".json"):
        return catalog_path(name, profile_id=profile_id)
    if name == "itad_prices.json":
        return itad_path(profile_id=profile_id)
    return profile_root(profile_id) / path


def slug_from_label(label: str) -> str:
    base = _SLUG_RE.sub("-", label.strip().lower()).strip("-")
    return base or "profile"


def list_profiles() -> list[dict[str, Any]]:
    doc = load_index()
    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        return []
    return [dict(p) for p in profiles if isinstance(p, dict) and p.get("id")]


def profile_label(profile_id: str) -> str:
    for p in list_profiles():
        if p.get("id") == profile_id:
            return str(p.get("label") or profile_id)
    return profile_id


def unique_profile_id(label: str) -> str:
    base = slug_from_label(label)
    existing = {p["id"] for p in list_profiles()}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"
