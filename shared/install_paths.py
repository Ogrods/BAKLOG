"""Resolve bundle (read-only) vs data (writable) roots for dev and PyInstaller builds."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BUILT_MANIFEST_CACHE: dict | None = None


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Read-only app assets (UI, manifest, packaged scripts)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    """Writable user data: profiles, games_*.json, cache, .env."""
    override = os.environ.get("BAKLOG_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return bundle_root()


def built_manifest_path() -> Path:
    return bundle_root() / "dist" / "manifest.json"


def _env_serve_built() -> bool:
    return os.environ.get("BAKLOG_SERVE_BUILT", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def serve_built_frontend() -> bool:
    """True when dist/manifest.json exists and built assets should be served."""
    if not built_manifest_path().is_file():
        return False
    return is_frozen() or _env_serve_built()


def load_built_manifest() -> dict:
    """Parsed dist/manifest.json; empty dict when not serving built frontend."""
    global _BUILT_MANIFEST_CACHE
    if not serve_built_frontend():
        return {}
    if _BUILT_MANIFEST_CACHE is None:
        try:
            _BUILT_MANIFEST_CACHE = json.loads(
                built_manifest_path().read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            _BUILT_MANIFEST_CACHE = {}
    return _BUILT_MANIFEST_CACHE


def built_immutable_assets() -> frozenset[str]:
    """Basenames/paths of hashed production assets (immutable cache)."""
    manifest = load_built_manifest()
    if not manifest:
        return frozenset()
    out: set[str] = set()
    for key, val in manifest.items():
        if key in ("builtAt", "version"):
            continue
        if key == "js/chunks" and isinstance(val, list):
            out.update(str(v) for v in val)
        elif isinstance(val, str) and val:
            out.add(val.replace("\\", "/"))
    return frozenset(out)


def static_root() -> Path:
    """HTTP static file root (index.html, js/, css/)."""
    return bundle_root()
