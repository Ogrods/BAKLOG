"""Shared path/env helpers for frozen bundle smoke scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def frozen_server_path(bundle_dir: Path) -> Path:
    from shared.update_platform import server_binary_name

    return bundle_dir / server_binary_name()


def frozen_tray_path(bundle_dir: Path) -> Path | None:
    from shared.update_platform import tray_binary_name

    name = tray_binary_name()
    if not name:
        return None
    return bundle_dir / name


def smoke_home_env(temp_home: Path) -> tuple[dict[str, str], Path]:
    """Build env overrides and expected default frozen data dir under *temp_home*.

    Mirrors ``shared.install_paths.default_frozen_data_dir`` for the current OS
    without requiring ``sys.frozen``.
    """
    env = {**os.environ, "BAKLOG_NO_BROWSER": "1"}
    env.pop("BAKLOG_DATA_DIR", None)
    env.pop("BAKLOG_PORTABLE", None)
    if sys.platform == "win32":
        env["LOCALAPPDATA"] = str(temp_home)
        data_dir = temp_home / "BAKLOG-Data"
    elif sys.platform == "darwin":
        env["HOME"] = str(temp_home)
        data_dir = temp_home / "Library" / "Application Support" / "BAKLOG"
    else:
        # linux / other POSIX: XDG_DATA_HOME/baklog
        xdg = temp_home / ".local" / "share"
        env["HOME"] = str(temp_home)
        env["XDG_DATA_HOME"] = str(xdg)
        data_dir = xdg / "baklog"
    return env, data_dir
