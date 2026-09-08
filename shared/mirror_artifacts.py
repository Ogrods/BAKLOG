"""Single allowlist for Pro cloud-mirror artifacts (upload + import + hosted API).

Keep the source string in sync with ``js/mirror-artifacts.js`` (AGENTS.md rule 6).
Catalog filenames must stay compatible with ``shared/server_catalog_import._ALLOWED_CATALOG_RE``.
``free_claims.json`` is intentionally excluded (public feed, not per-user).
"""

from __future__ import annotations

import re
from pathlib import Path

# Shared with js/mirror-artifacts.js — do not diverge.
ALLOWED_ARTIFACT_RE_SOURCE = (
    r"^(games_[a-z0-9_]+\.json|itad_prices\.json|data/personal\.json)$"
)

ALLOWED_ARTIFACT_RE = re.compile(ALLOWED_ARTIFACT_RE_SOURCE)

# Paths that must never leave the machine even if they match a broader pattern later.
_DENIED_PREFIXES = ("cache/", "auth/", ".git/")


def is_denied_relative(rel_posix: str) -> bool:
    lower = str(rel_posix or "").replace("\\", "/").lower().lstrip("/")
    if ".." in lower.split("/"):
        return True
    if lower.startswith("/") or (len(lower) >= 2 and lower[1] == ":"):
        return True
    for prefix in _DENIED_PREFIXES:
        if lower.startswith(prefix) or f"/{prefix}" in f"/{lower}":
            return True
    if lower.endswith("secrets.bin") or "/secrets.bin" in lower:
        return True
    return False


def is_allowed_relative(rel_posix: str) -> bool:
    rel = str(rel_posix or "").replace("\\", "/").lstrip("/")
    if not rel or is_denied_relative(rel):
        return False
    return bool(ALLOWED_ARTIFACT_RE.match(rel))


def mirrorable_relative_path(path: Path, *, profile_root: Path) -> str | None:
    """Return allowlisted posix-relative path under profile_root, or None."""
    try:
        rel = path.resolve().relative_to(profile_root.resolve())
    except (OSError, ValueError):
        return None
    rel_posix = rel.as_posix()
    if is_denied_relative(rel_posix):
        return None
    if is_allowed_relative(rel_posix):
        return rel_posix
    return None
