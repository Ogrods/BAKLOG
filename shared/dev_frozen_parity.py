"""
BAKLOG_DEV_FROZEN_PARITY=1 mode — make dev behave like a frozen PyInstaller build.

Usage:
    $env:BAKLOG_DEV_FROZEN_PARITY="1"; .venv\Scripts\python.exe server.py

Effects:
    - is_frozen() returns True (patched via sys.frozen)
    - Frontend serves from built dist/ (BAKLOG_SERVE_BUILT=1 implied)
    - Data root redirected to a temp dir under %LOCALAPPDATA%\BAKLOG-Data\dev-parity
    - Profile paths resolve through the temp data root

Call this module early in server.py startup, before any path resolution that
depends on is_frozen(), data_root(), or serve_built_frontend().
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _is_parity_enabled() -> bool:
    return os.environ.get("BAKLOG_DEV_FROZEN_PARITY", "").strip().lower() in (
        "1", "true", "yes",
    )


def apply_frozen_parity_patches() -> bool:
    """Apply monkeypatches when BAKLOG_DEV_FROZEN_PARITY=1.

    Returns True when parity mode is active, False otherwise.
    Should be called before ``shared.install_paths`` functions are first used.
    """
    if not _is_parity_enabled():
        return False

    # Patch sys.frozen so is_frozen() → True
    if not getattr(sys, "frozen", False):
        sys.frozen = True  # type: ignore[attr-defined]

    # Imply BAKLOG_SERVE_BUILT=1 so serve_built_frontend() → True (if dist/ exists)
    if not os.environ.get("BAKLOG_SERVE_BUILT", "").strip():
        os.environ["BAKLOG_SERVE_BUILT"] = "1"

    # Redirect data root to a temp dir so we don't clobber real user data
    parity_root = os.environ.get("BAKLOG_PARITY_DATA_DIR", "").strip()
    if not parity_root:
        localappdata = os.environ.get("LOCALAPPDATA", "")
        if localappdata:
            parity_root = str(Path(localappdata) / "BAKLOG-Data" / "dev-parity")
        else:
            parity_root = str(Path.home() / "AppData" / "Local" / "BAKLOG-Data" / "dev-parity")
    os.environ.setdefault("BAKLOG_DATA_DIR", parity_root)

    print(
        f"[dev_frozen_parity] BAKLOG_DEV_FROZEN_PARITY=1 active",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"  data root → {parity_root}",
        file=sys.stderr,
        flush=True,
    )
    return True
