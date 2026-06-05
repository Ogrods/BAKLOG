"""Resolve bundle (read-only) vs data (writable) roots for dev and PyInstaller builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


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


def static_root() -> Path:
    """HTTP static file root (index.html, js/, css/)."""
    return bundle_root()
