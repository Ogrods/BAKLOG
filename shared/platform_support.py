"""Tiny cross-platform guard helpers.

Some data sources are tied to one OS (e.g. Amazon Games reads a Windows-only
launcher database via DPAPI). These helpers let the server/registry mark a
provider or fetcher as platform-restricted without importing OS-specific
modules on unsupported platforms.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable


def current_platform() -> str:
    """The running interpreter's ``sys.platform`` (e.g. 'win32', 'darwin', 'linux')."""
    return sys.platform


def platform_supported(platforms: Iterable[str] | None) -> bool:
    """True when the current OS is allowed.

    An empty / ``None`` ``platforms`` means "all platforms" (the common case).
    """
    if not platforms:
        return True
    return sys.platform in tuple(platforms)
