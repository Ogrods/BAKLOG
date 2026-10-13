"""Where owner claim decisions live.

Owner decisions (``free_claims.approved.json``) are the source of truth for
what ships. They live in the private ``baklog-internal`` repo so CI and every
maintainer machine see the same state; the public repo's ``curated/`` copy is
only a fallback for clones without the sibling checkout.

Resolution order:

1. ``BAKLOG_FREE_CLAIMS_APPROVED`` env (CI checks out the internal repo and
   points here).
2. ``<repo parent>/baklog-internal/claims/free_claims.approved.json`` when it
   exists.
3. ``<repo>/curated/free_claims.approved.json``.
"""

from __future__ import annotations

import os
from pathlib import Path

APPROVED_ENV = "BAKLOG_FREE_CLAIMS_APPROVED"
AUTO_DECISIONS_ENV = "BAKLOG_CLAIMS_AUTO_DECISIONS"
INTERNAL_REPO_ENV = "BAKLOG_INTERNAL_REPO"
INTERNAL_DIRNAME = "baklog-internal"
CLAIMS_SUBDIR = "claims"
APPROVED_NAME = "free_claims.approved.json"
AUTO_DECISIONS_NAME = "auto_decisions.json"
CURATED_APPROVED = Path("curated") / APPROVED_NAME


def internal_repo_dir(repo_root: Path) -> Path | None:
    """Sibling private clone (``BAKLOG_INTERNAL_REPO`` overrides); None when absent."""
    env = os.environ.get(INTERNAL_REPO_ENV, "").strip()
    candidate = Path(env) if env else Path(repo_root).resolve().parent / INTERNAL_DIRNAME
    return candidate if candidate.is_dir() else None


def internal_claims_dir(repo_root: Path) -> Path | None:
    internal = internal_repo_dir(repo_root)
    if internal is None:
        return None
    claims = internal / CLAIMS_SUBDIR
    return claims if claims.is_dir() else None


def resolve_approved_path(repo_root: Path, default: Path | None = None) -> Path:
    env = os.environ.get(APPROVED_ENV, "").strip()
    if env:
        return Path(env)
    claims = internal_claims_dir(repo_root)
    if claims is not None:
        return claims / APPROVED_NAME
    return default if default is not None else Path(repo_root) / CURATED_APPROVED


def resolve_auto_decisions_path(repo_root: Path) -> Path | None:
    env = os.environ.get(AUTO_DECISIONS_ENV, "").strip()
    if env:
        return Path(env)
    claims = internal_claims_dir(repo_root)
    if claims is not None:
        return claims / AUTO_DECISIONS_NAME
    return None
