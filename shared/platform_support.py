from __future__ import annotations
import sys
from collections.abc import Iterable

def current_platform() -> str:
    return sys.platform

def platform_supported(platforms: Iterable[str] | None) -> bool:
    if not platforms:
        return True
    return sys.platform in tuple(platforms)