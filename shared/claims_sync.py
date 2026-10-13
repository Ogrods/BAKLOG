"""Commit + push owner claim decisions in the private baklog-internal clone.

Admin "Save and sync" calls this so CI (which checks out baklog-internal)
sees the same approvals as the maintainer's machine. Only ``claims/`` is
staged; nothing else in the private clone is touched.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from shared.claims_paths import (
    CLAIMS_SUBDIR,
    CURATED_SCRAPE,
    SCRAPE_NAME,
    internal_repo_dir,
    resolve_scrape_path,
)

Runner = Callable[..., subprocess.CompletedProcess]

GIT_TIMEOUT_SEC = 60


class ClaimsSyncError(RuntimeError):
    pass


def _git(runner: Runner, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return runner(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SEC,
        check=False,
    )


def _check(proc: subprocess.CompletedProcess, what: str) -> None:
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        raise ClaimsSyncError(f"{what} failed: {tail}")


def _pull_rebase(runner: Runner, internal: Path) -> None:
    pull = _git(runner, internal, "pull", "-q", "--rebase", "--autostash")
    if pull.returncode != 0:
        _git(runner, internal, "rebase", "--abort")
        _check(pull, "git pull --rebase")


def _share_newer_local_scrape(repo_root: Path, internal: Path) -> bool:
    """Copy the local scrape into ``claims/`` when it is newer than CI's."""
    local = Path(repo_root) / CURATED_SCRAPE
    shared = internal / CLAIMS_SUBDIR / SCRAPE_NAME
    if not local.is_file() or resolve_scrape_path(repo_root, local) != local:
        return False
    data = local.read_bytes()
    if shared.is_file() and shared.read_bytes() == data:
        return False
    tmp = shared.with_name(shared.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, shared)
    return True


def sync_claims_decisions(
    repo_root: Path,
    *,
    message: str = "claims: owner decisions from admin",
    runner: Runner = subprocess.run,
    push: bool = True,
) -> dict:
    """Stage ``claims/``, commit if changed, rebase on origin, push.

    Returns ``{"changed": bool, "sha": str, "pushed": bool}``. Raises
    ``ClaimsSyncError`` when the clone is missing or git fails; a rebase
    conflict is aborted so the clone is never left mid-rebase.
    """
    internal = internal_repo_dir(repo_root)
    if internal is None or not (internal / CLAIMS_SUBDIR).is_dir():
        raise ClaimsSyncError("baklog-internal/claims not found next to this repo")

    if push:
        # Pull before touching the scrape: CI commits it every run, so copying ours
        # onto a stale base would conflict on rebase.
        _pull_rebase(runner, internal)
    _share_newer_local_scrape(repo_root, internal)
    _check(_git(runner, internal, "add", "--", CLAIMS_SUBDIR), "git add")
    staged = _git(runner, internal, "diff", "--cached", "--quiet", "--", CLAIMS_SUBDIR)
    changed = staged.returncode == 1
    if staged.returncode not in (0, 1):
        _check(staged, "git diff")
    if changed:
        _check(
            _git(runner, internal, "commit", "-q", "-m", message, "--", CLAIMS_SUBDIR),
            "git commit",
        )

    pushed = False
    if push:
        _pull_rebase(runner, internal)
        # Push even when unchanged: an earlier sync may have committed but failed to push.
        _check(_git(runner, internal, "push", "-q"), "git push")
        pushed = True

    head = _git(runner, internal, "rev-parse", "--short", "HEAD")
    _check(head, "git rev-parse")
    return {"changed": changed, "sha": head.stdout.strip(), "pushed": pushed}


INGEST_WORKFLOW = "claims-ingest.yml"
PUBLIC_REPO_ENV = "BAKLOG_PUBLIC_REPO"
DEFAULT_PUBLIC_REPO = "Ogrods/BAKLOG"


def dispatch_claims_ingest(*, runner: Runner = subprocess.run) -> dict:
    """Start the public repo's Claims ingest run with the maintainer's ``gh`` login.

    That run rebuilds the feed from the synced decisions and opens (and, when
    every added id is vetted, auto-merges) the feed PR. Returns
    ``{"workflow": str, "url": str}``; raises ``ClaimsSyncError`` on failure.
    """
    repo = os.environ.get(PUBLIC_REPO_ENV, "").strip() or DEFAULT_PUBLIC_REPO
    try:
        proc = runner(
            ["gh", "workflow", "run", INGEST_WORKFLOW, "-R", repo],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaimsSyncError("GitHub CLI (gh) not found on PATH") from exc
    _check(proc, "gh workflow run")
    return {
        "workflow": INGEST_WORKFLOW,
        "url": f"https://github.com/{repo}/actions/workflows/{INGEST_WORKFLOW}",
    }
