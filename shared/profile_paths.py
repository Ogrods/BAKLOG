"""Resolve data paths for the active local profile (legacy root vs profiles/<id>/)."""

from __future__ import annotations

import contextvars
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_request_profile_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_request_profile_id",
    default=None,
)


def set_request_profile_id(profile_id: str | None) -> None:
    """Pin active profile for the current HTTP request (Supabase auth)."""
    _request_profile_id.set(profile_id)


def clear_request_profile_id() -> None:
    _request_profile_id.set(None)

from shared.install_paths import data_root

ROOT = data_root()
PROFILES_DIR = ROOT / "profiles"
INDEX_FILE = PROFILES_DIR / "index.json"
DEFAULT_PROFILE_ID = "default"
MIGRATION_COMPLETE_MARKER = ".migration_complete"
_ENV_OVERRIDE = "BAKLOG_PROFILE"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
    active = doc.get("active")
    if active is not None and not is_valid_profile_id(str(active)):
        raise ValueError(f"invalid active profile in index: {active!r}")
    profiles = doc.get("profiles")
    if isinstance(profiles, list):
        for p in profiles:
            if isinstance(p, dict) and p.get("id") is not None:
                normalize_profile_id(str(p["id"]))
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, INDEX_FILE)


def is_valid_profile_id(profile_id: str) -> bool:
    pid = (profile_id or "").strip()
    if not pid or pid in (".", ".."):
        return False
    if not _PROFILE_ID_RE.match(pid):
        return False
    try:
        resolved = (PROFILES_DIR / pid).resolve()
        base = PROFILES_DIR.resolve()
        return resolved == base or str(resolved).startswith(str(base) + os.sep)
    except (OSError, RuntimeError):
        return False


def normalize_profile_id(profile_id: str) -> str:
    """Validate profile id; raise ValueError when unsafe or malformed."""
    pid = (profile_id or "").strip()
    if not is_valid_profile_id(pid):
        raise ValueError(f"invalid profile id: {profile_id!r}")
    return pid


def get_active_profile_id() -> str:
    ctx = _request_profile_id.get()
    if ctx is not None:
        return ctx
    override = os.environ.get(_ENV_OVERRIDE, "").strip()
    if override:
        if is_valid_profile_id(override):
            return override
        import sys

        print(
            f"WARN: ignoring invalid {_ENV_OVERRIDE}={override!r}; using index active",
            file=sys.stderr,
            flush=True,
        )
    active = str(load_index().get("active") or DEFAULT_PROFILE_ID)
    if is_valid_profile_id(active):
        return active
    return DEFAULT_PROFILE_ID


def profile_data_dir(profile_id: str) -> Path:
    pid = normalize_profile_id(profile_id)
    return PROFILES_DIR / pid


def migration_complete_path(profile_id: str = DEFAULT_PROFILE_ID) -> Path:
    return profile_data_dir(profile_id) / MIGRATION_COMPLETE_MARKER


def is_legacy_layout(profile_id: str | None = None) -> bool:
    """True when default profile data still lives at repo root (not fully migrated)."""
    pid = profile_id if profile_id is not None else get_active_profile_id()
    if pid != DEFAULT_PROFILE_ID:
        return False
    dest = profile_data_dir(DEFAULT_PROFILE_ID)
    if not dest.is_dir():
        return True
    return not migration_complete_path(DEFAULT_PROFILE_ID).is_file()


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


def profile_cache_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache"


def epic_cache_dir(*, profile_id: str | None = None) -> Path:
    return profile_cache_dir(profile_id=profile_id) / "epic"


def runs_dir(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache" / "runs"


def fx_rates_path(*, profile_id: str | None = None) -> Path:
    return profile_root(profile_id) / "cache" / "fx_rates.json"


# Enrichment / FX cache files the dashboard loads via GET /cache/<name>.
PROFILE_CACHE_JSON_FILES = frozenset({
    "hltb_map.json",
    "steam_review_map.json",
    "cross_store_images_meta.json",
    "steam_tags_meta.json",
    "fx_rates.json",
})


def cache_json_path(filename: str, *, profile_id: str | None = None) -> Path:
    """Path to a profile-scoped cache JSON file (enrichment meta, FX rates)."""
    if filename not in PROFILE_CACHE_JSON_FILES:
        raise ValueError(f"unknown profile cache file: {filename!r}")
    return profile_root(profile_id) / "cache" / filename


def games_backup_root(*, profile_id: str | None = None) -> Path:
    return personal_dir(profile_id=profile_id) / "games_backups"


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
