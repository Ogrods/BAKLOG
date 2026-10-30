"""Admin Publish: commit local feed onto sticky refresh branch."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from shared.claims_feed_publish import FEED_FALLBACK, FEED_WEB, STICKY_BRANCH, publish_public_feed
from shared.claims_sync import ClaimsSyncError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _feed(items: list[dict], generated_at: str = "2026-10-29T12:00:00+00:00") -> str:
    return json.dumps({"generated_at": generated_at, "items": items}, indent=2) + "\n"


def _write_feed(repo: Path, items: list[dict], generated_at: str = "2026-10-29T12:00:00+00:00") -> None:
    for rel in (FEED_WEB, FEED_FALLBACK):
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_feed(items, generated_at), encoding="utf-8")


@pytest.fixture()
def public_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "steam-backlog"
    _git(tmp_path, "clone", "-q", str(origin), str(repo))
    for key, val in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(repo, "config", key, val)
    _git(repo, "checkout", "-q", "-b", "main")
    # Minimal scripts so fingerprint + verify-added can run when present; tests
    # also exercise the no-scripts fallback by deleting them in some cases.
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "claims_feed_fingerprint.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "import json\n"
        "bef=json.loads(Path(sys.argv[sys.argv.index('--before')+1]).read_text(encoding='utf-8'))\n"
        "aft=json.loads(Path(sys.argv[sys.argv.index('--after')+1]).read_text(encoding='utf-8'))\n"
        "bi={str(i.get('id')):i for i in (bef.get('items') or [])}\n"
        "ai={str(i.get('id')):i for i in (aft.get('items') or [])}\n"
        "changed=bi!=ai\n"
        "raise SystemExit(0 if changed else 3)\n",
        encoding="utf-8",
    )
    _write_feed(repo, [{"id": "a", "title": "A", "claim_url": "https://example.com/a"}])
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "seed feed")
    _git(repo, "push", "-q", "-u", "origin", "main")
    monkeypatch.setenv("BAKLOG_PUBLIC_REPO", "o/BAKLOG")
    return repo, origin


def _gh_recorder(
    calls: list[list[str]],
    *,
    pr_number: str = "42",
    merge_auto_fail: bool = False,
):
    def runner(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            calls.append(cmd)
            sub = cmd[1:3]
            out = ""
            if sub == ["pr", "list"]:
                # --jq selects; emulate empty then object after create.
                jq = ""
                if "--jq" in cmd:
                    jq = cmd[cmd.index("--jq") + 1]
                created = any(c[1:3] == ["pr", "create"] for c in calls[:-1])
                if "number,url" in cmd or "number,url" in " ".join(cmd):
                    if created or any(c[1:3] == ["pr", "edit"] for c in calls):
                        out = json.dumps(
                            {
                                "number": int(pr_number),
                                "url": f"https://github.com/o/BAKLOG/pull/{pr_number}",
                            }
                        )
                    else:
                        out = ""
                elif "number // empty" in jq or jq.endswith("number // empty"):
                    out = pr_number if created else ""
                else:
                    out = ""
            elif sub == ["pr", "create"]:
                out = f"https://github.com/o/BAKLOG/pull/{pr_number}\n"
            elif sub == ["pr", "view"]:
                out = "false\n"
            elif sub == ["pr", "merge"] and "--auto" in cmd and merge_auto_fail:
                return subprocess.CompletedProcess(
                    cmd, 1, "", "GraphQL: Pull request is in a non-mergeable state"
                )
            return subprocess.CompletedProcess(cmd, 0, out, "")
        return subprocess.run(cmd, **kwargs)

    return runner


def test_publish_pushes_sticky_branch_and_opens_pr(public_clone) -> None:
    repo, origin = public_clone
    _write_feed(
        repo,
        [
            {"id": "a", "title": "A", "claim_url": "https://example.com/a"},
            {"id": "b", "title": "B", "claim_url": "https://example.com/b"},
        ],
        generated_at="2026-10-29T13:00:00+00:00",
    )
    calls: list[list[str]] = []
    result = publish_public_feed(repo, runner=_gh_recorder(calls))
    assert result["changed"] is True
    assert result["pushed"] is True
    assert result["pr_url"].endswith("/pull/42")
    assert result["url"] == result["pr_url"]
    # Sticky tip on origin has both feed files.
    files = _git(origin, "ls-tree", "-r", "--name-only", STICKY_BRANCH).splitlines()
    assert FEED_WEB.as_posix() in files
    assert FEED_FALLBACK.as_posix() in files
    assert any(c[1:3] == ["pr", "create"] for c in calls)
    # Worktree cleaned up - no leftover sticky checkout in repo.
    assert STICKY_BRANCH not in _git(repo, "branch", "--list", STICKY_BRANCH)


def test_publish_noop_when_fingerprint_unchanged(public_clone) -> None:
    repo, _origin = public_clone
    # Same items, newer stamp only - stub fingerprint treats dict inequality;
    # rewrite identical bytes so bi==ai.
    items = [{"id": "a", "title": "A", "claim_url": "https://example.com/a"}]
    _write_feed(repo, items, generated_at="2026-10-29T12:00:00+00:00")
    calls: list[list[str]] = []
    result = publish_public_feed(repo, runner=_gh_recorder(calls))
    assert result["changed"] is False
    assert result["pushed"] is False
    assert result["pr_url"] is None
    # Stale close attempted (list then maybe close) - at least a pr list happened.
    assert any(c[1:3] == ["pr", "list"] for c in calls)
    assert not any(c[1:3] == ["pr", "create"] for c in calls)


def test_publish_missing_local_feed_raises(tmp_path: Path) -> None:
    with pytest.raises(ClaimsSyncError, match="missing local feed"):
        publish_public_feed(tmp_path, push=False)


def test_publish_without_gh_cli(public_clone) -> None:
    repo, _ = public_clone
    _write_feed(
        repo,
        [{"id": "z", "title": "Z", "claim_url": "https://example.com/z"}],
        generated_at="2026-10-29T14:00:00+00:00",
    )

    def runner(cmd, **kwargs):
        if cmd and cmd[0] == "gh":
            raise FileNotFoundError("gh")
        return subprocess.run(cmd, **kwargs)

    with pytest.raises(ClaimsSyncError, match="gh"):
        publish_public_feed(repo, runner=runner)


def test_publish_soft_fails_auto_merge_after_push(public_clone) -> None:
    """Sticky push + PR create succeed even when gh pr merge --auto fails."""
    repo, origin = public_clone
    # Same ids, changed claim_url → fingerprint change, no new ids → auto_merge True.
    _write_feed(
        repo,
        [{"id": "a", "title": "A", "claim_url": "https://example.com/a-new"}],
        generated_at="2026-10-30T12:00:00+00:00",
    )
    calls: list[list[str]] = []
    result = publish_public_feed(
        repo, runner=_gh_recorder(calls, merge_auto_fail=True)
    )
    assert result["changed"] is True
    assert result["pushed"] is True
    assert result["pr_url"].endswith("/pull/42")
    assert result["auto_merge"] is False
    assert result.get("warning") and "merge --auto" in result["warning"]
    assert any(c[1:3] == ["pr", "merge"] and "--auto" in c for c in calls)
    files = _git(origin, "ls-tree", "-r", "--name-only", STICKY_BRANCH).splitlines()
    assert FEED_WEB.as_posix() in files
