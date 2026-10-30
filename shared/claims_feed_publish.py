"""Commit local free-claims feed onto the sticky refresh branch (admin Publish).

Admin Publish builds ``web/free-claims.json`` + ``curated/free_claims.fallback.json``
on disk. This module copies those bytes onto a temporary worktree based on
``origin/main``, force-pushes ``chore/claims-feed-refresh``, and opens/updates
the Refresh free-claims feed PR - without dispatching Claims ingest (which
would rebuild from scratch and race the sticky branch).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from shared.claims_paths import resolve_approved_path, resolve_auto_decisions_path
from shared.claims_sync import (
    DEFAULT_PUBLIC_REPO,
    GIT_TIMEOUT_SEC,
    PUBLIC_REPO_ENV,
    ClaimsSyncError,
    Runner,
    _check,
    _git,
)

FEED_WEB = Path("web") / "free-claims.json"
FEED_FALLBACK = Path("curated") / "free_claims.fallback.json"
FEED_PATHS = (FEED_WEB, FEED_FALLBACK)
STICKY_BRANCH = "chore/claims-feed-refresh"
FEED_COMMIT_MSG = "Refresh free-claims feed"
PR_TITLE = "Refresh free-claims feed"
MANUAL_INPUT = Path("free-claims.input.json")


def _public_repo_slug() -> str:
    return os.environ.get(PUBLIC_REPO_ENV, "").strip() or DEFAULT_PUBLIC_REPO


def _gh(runner: Runner, *args: str) -> subprocess.CompletedProcess:
    try:
        return runner(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ClaimsSyncError("GitHub CLI (gh) not found on PATH") from exc


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ClaimsSyncError(f"cannot read {path}: {exc}") from exc
    return doc if isinstance(doc, dict) else {}


def _show_origin_main_file(runner: Runner, repo: Path, rel: Path) -> bytes | None:
    """Blob for ``origin/main:<rel>``, or None when missing."""
    raw = runner(
        ["git", "-C", str(repo), "show", f"origin/main:{rel.as_posix()}"],
        capture_output=True,
        timeout=GIT_TIMEOUT_SEC,
        check=False,
    )
    if raw.returncode != 0:
        return None
    out = raw.stdout
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return str(out or "").encode()


def _fingerprint_changed(repo_root: Path, before_path: Path, after_path: Path, runner: Runner) -> bool:
    """True when claimable fingerprint differs (exit 3 from script = unchanged)."""
    script = Path(repo_root) / "scripts" / "claims_feed_fingerprint.py"
    if not script.is_file():
        # Tests / thin trees: fall back to raw JSON compare of items ids + claim_url.
        before = _read_json(before_path).get("items") or []
        after = _read_json(after_path).get("items") or []
        return before != after
    try:
        proc = runner(
            [sys.executable, str(script), "--before", str(before_path), "--after", str(after_path)],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SEC,
            check=False,
            cwd=str(repo_root),
        )
    except FileNotFoundError as exc:
        raise ClaimsSyncError(f"python not found for fingerprint: {exc}") from exc
    if proc.returncode == 3:
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit {proc.returncode}"
        raise ClaimsSyncError(f"claims_feed_fingerprint failed: {tail}")
    return True


def _added_ids_vetted(repo_root: Path, before_path: Path, after_path: Path, runner: Runner) -> bool:
    """Mirror Claims ingest verify-added (exit 0 = auto-merge OK, 3 = needs review)."""
    script = Path(repo_root) / "scripts" / "claims_autopilot.py"
    approved = resolve_approved_path(repo_root)
    decisions = resolve_auto_decisions_path(repo_root)
    if not script.is_file() or decisions is None or not approved.is_file():
        # Without autopilot artifacts, only allow auto-merge when no new ids.
        before_ids = {
            str(it.get("id"))
            for it in (_read_json(before_path).get("items") or [])
            if isinstance(it, dict)
        }
        after_ids = {
            str(it.get("id"))
            for it in (_read_json(after_path).get("items") or [])
            if isinstance(it, dict)
        }
        return not (after_ids - before_ids)
    cmd = [
        sys.executable,
        str(script),
        "verify-added",
        "--before",
        str(before_path),
        "--after",
        str(after_path),
        "--approved",
        str(approved),
        "--decisions",
        str(decisions),
    ]
    manual = Path(repo_root) / MANUAL_INPUT
    if manual.is_file():
        cmd.extend(["--manual", str(manual)])
    proc = runner(
        cmd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_SEC,
        check=False,
        cwd=str(repo_root),
    )
    if proc.returncode == 0:
        return True
    if proc.returncode == 3:
        return False
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else f"exit {proc.returncode}"
    raise ClaimsSyncError(f"claims_autopilot verify-added failed: {tail}")


def _pr_body(*, auto_merge: bool) -> str:
    lines = [
        "## Summary",
        "",
        "Admin Publish refreshed the free-claims feed from the local build.",
    ]
    if auto_merge:
        lines.append(
            "Every added claim is owner- or autopilot-approved, so squash auto-merge is on."
        )
    else:
        lines.append(
            "Some added claims are not vetted yet, or a published claim's link moved to a "
            "new domain, so this PR needs a human merge."
        )
    lines.extend(
        [
            "",
            "Merge publishes to baklog.app via the normal web deploy.",
        ]
    )
    return "\n".join(lines) + "\n"


def _close_stale_sticky_pr(runner: Runner, repo_slug: str) -> None:
    listed = _gh(
        runner,
        "pr",
        "list",
        "--repo",
        repo_slug,
        "--head",
        STICKY_BRANCH,
        "--state",
        "open",
        "--json",
        "number",
        "--jq",
        ".[0].number // empty",
    )
    _check(listed, "gh pr list")
    number = (listed.stdout or "").strip()
    if not number:
        return
    closed = _gh(
        runner,
        "pr",
        "close",
        number,
        "--repo",
        repo_slug,
        "--delete-branch",
        "--comment",
        "Closed by admin Publish: the local feed now matches main.",
    )
    _check(closed, "gh pr close")


def _open_or_update_sticky_pr(
    runner: Runner,
    repo_slug: str,
    *,
    auto_merge: bool,
    body: str,
) -> str:
    """Create or edit the sticky PR; toggle auto-merge. Returns PR URL."""
    fd, body_name = tempfile.mkstemp(prefix="baklog-feed-pr-", suffix=".md")
    os.close(fd)
    body_file = Path(body_name)
    try:
        body_file.write_text(body, encoding="utf-8")
        listed = _gh(
            runner,
            "pr",
            "list",
            "--repo",
            repo_slug,
            "--head",
            STICKY_BRANCH,
            "--state",
            "open",
            "--json",
            "number,url",
            "--jq",
            ".[0] // empty",
        )
        _check(listed, "gh pr list")
        raw = (listed.stdout or "").strip()
        pr_number = ""
        pr_url = ""
        if raw and raw != "null":
            try:
                row = json.loads(raw)
            except ValueError:
                row = {}
            if isinstance(row, dict):
                pr_number = str(row.get("number") or "").strip()
                pr_url = str(row.get("url") or "").strip()
        if pr_number:
            edited = _gh(
                runner,
                "pr",
                "edit",
                pr_number,
                "--repo",
                repo_slug,
                "--body-file",
                str(body_file),
            )
            _check(edited, "gh pr edit")
        else:
            created = _gh(
                runner,
                "pr",
                "create",
                "--repo",
                repo_slug,
                "--base",
                "main",
                "--head",
                STICKY_BRANCH,
                "--title",
                PR_TITLE,
                "--body-file",
                str(body_file),
            )
            _check(created, "gh pr create")
            pr_url = (created.stdout or "").strip()
            listed2 = _gh(
                runner,
                "pr",
                "list",
                "--repo",
                repo_slug,
                "--head",
                STICKY_BRANCH,
                "--state",
                "open",
                "--json",
                "number,url",
                "--jq",
                ".[0] // empty",
            )
            _check(listed2, "gh pr list")
            raw2 = (listed2.stdout or "").strip()
            if raw2 and raw2 != "null":
                try:
                    row2 = json.loads(raw2)
                except ValueError:
                    row2 = {}
                if isinstance(row2, dict):
                    pr_number = str(row2.get("number") or "").strip()
                    pr_url = str(row2.get("url") or pr_url).strip()
            if not pr_number:
                raise ClaimsSyncError(
                    "PR create reported success but no open PR found for "
                    f"{STICKY_BRANCH}"
                )

        if auto_merge:
            merge = _gh(
                runner,
                "pr",
                "merge",
                pr_number,
                "--repo",
                repo_slug,
                "--squash",
                "--auto",
            )
            # Auto-merge can fail if checks are required and pending; surface that.
            _check(merge, "gh pr merge --auto")
        else:
            view = _gh(
                runner,
                "pr",
                "view",
                pr_number,
                "--repo",
                repo_slug,
                "--json",
                "autoMergeRequest",
                "--jq",
                ".autoMergeRequest != null",
            )
            if view.returncode == 0 and (view.stdout or "").strip() == "true":
                disabled = _gh(
                    runner,
                    "pr",
                    "merge",
                    pr_number,
                    "--repo",
                    repo_slug,
                    "--disable-auto",
                )
                _check(disabled, "gh pr merge --disable-auto")

        if not pr_url:
            pr_url = f"https://github.com/{repo_slug}/pull/{pr_number}"
        return pr_url
    finally:
        body_file.unlink(missing_ok=True)


def _configure_worktree_identity(runner: Runner, worktree: Path) -> None:
    for key, val in (
        ("user.email", "41898282+github-actions[bot]@users.noreply.github.com"),
        ("user.name", "github-actions[bot]"),
    ):
        _check(_git(runner, worktree, "config", key, val), f"git config {key}")


def publish_public_feed(
    repo_root: Path,
    *,
    runner: Runner = subprocess.run,
    push: bool = True,
) -> dict:
    """Push local built feed files to the sticky refresh branch + PR.

    Returns ``{"changed": bool, "sha": str|None, "pr_url": str|None,
    "url": str|None, "auto_merge": bool, "pushed": bool}``. ``url`` mirrors
    ``pr_url`` for admin toast compatibility with the old ingest dispatch.
    """
    root = Path(repo_root).resolve()
    for rel in FEED_PATHS:
        path = root / rel
        if not path.is_file():
            raise ClaimsSyncError(f"missing local feed file: {rel.as_posix()}")

    repo_slug = _public_repo_slug()
    if push:
        _check(_git(runner, root, "fetch", "-q", "origin", "main"), "git fetch origin main")

    before_dir = Path(tempfile.mkdtemp(prefix="baklog-feed-before-"))
    worktree: Path | None = None
    try:
        before_web = before_dir / "before-web.json"
        main_blob = _show_origin_main_file(runner, root, FEED_WEB) if push else None
        if main_blob is None:
            before_web.write_text('{"items":[]}\n', encoding="utf-8")
        else:
            before_web.write_bytes(main_blob)

        after_web = root / FEED_WEB
        fingerprint_differs = _fingerprint_changed(root, before_web, after_web, runner)
        if not fingerprint_differs:
            if push:
                _close_stale_sticky_pr(runner, repo_slug)
            return {
                "changed": False,
                "sha": None,
                "pr_url": None,
                "url": None,
                "auto_merge": False,
                "pushed": False,
            }

        auto_merge = _added_ids_vetted(root, before_web, after_web, runner)

        wt_parent = Path(tempfile.mkdtemp(prefix="baklog-feed-wt-"))
        worktree = wt_parent / "tree"
        # Detached worktree from origin/main so the maintainer worktree is untouched.
        _check(
            _git(runner, root, "worktree", "add", "--detach", str(worktree), "origin/main"),
            "git worktree add",
        )
        _configure_worktree_identity(runner, worktree)
        _check(
            _git(runner, worktree, "checkout", "-B", STICKY_BRANCH),
            "git checkout sticky branch",
        )

        for rel in FEED_PATHS:
            dest = worktree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / rel, dest)

        _check(
            _git(runner, worktree, "add", "--", *[p.as_posix() for p in FEED_PATHS]),
            "git add feed",
        )
        staged = _git(
            runner,
            worktree,
            "diff",
            "--cached",
            "--quiet",
            "--",
            *[p.as_posix() for p in FEED_PATHS],
        )
        if staged.returncode not in (0, 1):
            _check(staged, "git diff --cached")
        if staged.returncode == 0:
            # Fingerprint said change but files match tip (e.g. race) - treat as noop.
            if push:
                _close_stale_sticky_pr(runner, repo_slug)
            return {
                "changed": False,
                "sha": None,
                "pr_url": None,
                "url": None,
                "auto_merge": False,
                "pushed": False,
            }

        _check(
            _git(runner, worktree, "commit", "-q", "-m", FEED_COMMIT_MSG),
            "git commit",
        )
        head = _git(runner, worktree, "rev-parse", "--short", "HEAD")
        _check(head, "git rev-parse")
        sha = head.stdout.strip()

        pr_url = None
        pushed = False
        if push:
            _check(
                _git(
                    runner,
                    worktree,
                    "push",
                    "-u",
                    "origin",
                    f"HEAD:{STICKY_BRANCH}",
                    "--force",
                ),
                "git push sticky branch",
            )
            pushed = True
            pr_url = _open_or_update_sticky_pr(
                runner,
                repo_slug,
                auto_merge=auto_merge,
                body=_pr_body(auto_merge=auto_merge),
            )

        return {
            "changed": True,
            "sha": sha,
            "pr_url": pr_url,
            "url": pr_url,
            "auto_merge": auto_merge,
            "pushed": pushed,
        }
    finally:
        shutil.rmtree(before_dir, ignore_errors=True)
        if worktree is not None:
            remove = _git(runner, root, "worktree", "remove", "--force", str(worktree))
            if remove.returncode != 0:
                # Best-effort: prune leftovers so the next Publish is not blocked.
                _git(runner, root, "worktree", "prune")
            parent = worktree.parent
            shutil.rmtree(parent, ignore_errors=True)
            # Drop the local sticky branch name created by checkout -B in the worktree.
            _git(runner, root, "branch", "-D", STICKY_BRANCH)
