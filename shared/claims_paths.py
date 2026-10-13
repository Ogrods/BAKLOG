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

import json
import os
from datetime import UTC, datetime
from pathlib import Path

APPROVED_ENV = "BAKLOG_FREE_CLAIMS_APPROVED"
AUTO_DECISIONS_ENV = "BAKLOG_CLAIMS_AUTO_DECISIONS"
INTERNAL_REPO_ENV = "BAKLOG_INTERNAL_REPO"
INTERNAL_DIRNAME = "baklog-internal"
CLAIMS_SUBDIR = "claims"
APPROVED_NAME = "free_claims.approved.json"
AUTO_DECISIONS_NAME = "auto_decisions.json"
CURATED_APPROVED = Path("curated") / APPROVED_NAME
SCRAPE_NAME = "free_claims.auto.json"
CURATED_SCRAPE = Path("curated") / SCRAPE_NAME


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


def _scrape_stamp(path: Path) -> datetime | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    raw = str(doc.get("fetched_at") or "") if isinstance(doc, dict) else ""
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        stamp = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def resolve_scrape_path(repo_root: Path, local: Path | None = None) -> Path:
    """Newer of the local scrape and the private repo's CI scrape (by ``fetched_at``).

    CI pushes its scrape to ``baklog-internal/claims``; digest approvals can name
    rows only that scrape has, so admin must not judge them against a stale local one.
    """
    local = local if local is not None else Path(repo_root) / CURATED_SCRAPE
    claims = internal_claims_dir(repo_root)
    shared_scrape = claims / SCRAPE_NAME if claims is not None else None
    if shared_scrape is None or not shared_scrape.is_file():
        return local
    if not local.is_file():
        return shared_scrape
    local_at, shared_at = _scrape_stamp(local), _scrape_stamp(shared_scrape)
    if shared_at is not None and (local_at is None or shared_at > local_at):
        return shared_scrape
    return local


def resolve_auto_decisions_path(repo_root: Path) -> Path | None:
    env = os.environ.get(AUTO_DECISIONS_ENV, "").strip()
    if env:
        return Path(env)
    claims = internal_claims_dir(repo_root)
    if claims is not None:
        return claims / AUTO_DECISIONS_NAME
    return None
