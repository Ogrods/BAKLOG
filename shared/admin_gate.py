"""Decide whether BAKLOG_ADMIN may attach to the active data root."""

from __future__ import annotations

import os
from pathlib import Path


def _truthy(name: str, env: dict[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(name, "")).strip().lower() in ("1", "true", "yes")


def resolve_admin_enabled(
    data_root: Path,
    *,
    env: dict[str, str] | None = None,
    default_installed_dir: Path | None = None,
) -> tuple[bool, str | None]:
    """Return ``(enabled, stderr_warning_or_None)``.

    Admin is refused when ``BAKLOG_ADMIN=1`` but ``data_root`` is the default
    installed library folder, unless ``BAKLOG_ADMIN_ALLOW_INSTALLED=1``.
    """
    from shared.install_paths import default_frozen_data_dir

    if not _truthy("BAKLOG_ADMIN", env):
        return False, None
    installed = (default_installed_dir or default_frozen_data_dir()).resolve()
    root = Path(data_root).resolve()
    if root == installed and not _truthy("BAKLOG_ADMIN_ALLOW_INSTALLED", env):
        msg = (
            "[admin] BAKLOG_ADMIN=1 refused: data root is the default installed "
            f"library ({installed}). Use BAKLOG_DATA_DIR for a separate folder "
            "(e.g. BAKLOG-Dev), or set BAKLOG_ADMIN_ALLOW_INSTALLED=1 to override."
        )
        return False, msg
    return True, None
