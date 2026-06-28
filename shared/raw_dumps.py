"""Gate optional *_raw.json debug dumps behind BAKLOG_RAW_DUMPS."""

from __future__ import annotations

import os
from pathlib import Path


def raw_dumps_enabled() -> bool:
    """True when operator explicitly opts in to writing debug raw JSON dumps."""
    return os.environ.get("BAKLOG_RAW_DUMPS", "").strip().lower() in ("1", "true", "yes", "on")


def profile_raw_dump_path(filename: str) -> Path:
    """Profile-scoped path for optional ``*_raw.json`` debug artifacts."""
    from shared.profile_paths import profile_cache_dir

    return profile_cache_dir() / filename
