"""Profile-scoped Pro feature toggles (server-side prefs)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from shared.profile_paths import get_active_profile_id, personal_dir
from shared.safe_write import safe_write_text

DEFAULT_PRO_SETTINGS: dict[str, Any] = {
    "cloudMirrorEnabled": False,
}

ALLOWED_KEYS = frozenset(DEFAULT_PRO_SETTINGS.keys())


def pro_settings_path(*, profile_id: str | None = None) -> Path:
    pid = profile_id if profile_id is not None else get_active_profile_id()
    return personal_dir(profile_id=pid) / "pro_settings.json"


def read_pro_settings(*, profile_id: str | None = None) -> dict[str, Any]:
    """Load Pro toggles; missing file returns defaults."""
    out = dict(DEFAULT_PRO_SETTINGS)
    try:
        doc = json.loads(pro_settings_path(profile_id=profile_id).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return out
    if not isinstance(doc, dict):
        return out
    for key in ALLOWED_KEYS:
        if key in doc:
            out[key] = bool(doc[key]) if key == "cloudMirrorEnabled" else doc[key]
    return out


def write_pro_settings(
    updates: dict[str, Any],
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    """Merge allowed keys and persist atomically."""
    current = read_pro_settings(profile_id=profile_id)
    for key, value in updates.items():
        if key not in ALLOWED_KEYS:
            raise ValueError(f"unknown pro setting: {key!r}")
        if key == "cloudMirrorEnabled":
            current[key] = bool(value)
        else:
            current[key] = value
    path = pro_settings_path(profile_id=profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_write_text(path, json.dumps(current, indent=2) + "\n")
    return current
