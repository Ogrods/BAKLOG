"""Admin "Save and sync": commit + push claims/ in the private clone."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from shared import claims_paths
from shared.claims_sync import ClaimsSyncError, sync_claims_decisions

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def internal_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "steam-backlog"
    repo.mkdir()
    internal = tmp_path / "baklog-internal"
    _git(tmp_path, "clone", "-q", str(origin), str(internal))
    for key, val in (("user.email", "t@example.invalid"), ("user.name", "t")):
        _git(internal, "config", key, val)
    _git(internal, "checkout", "-q", "-b", "main")
    (internal / "claims").mkdir()
    (internal / "claims" / "free_claims.approved.json").write_text('{"ids": []}\n', encoding="utf-8")
    (internal / "notes.txt").write_text("private\n", encoding="utf-8")
    _git(internal, "add", ".")
    _git(internal, "commit", "-q", "-m", "seed")
    _git(internal, "push", "-q", "-u", "origin", "main")
    monkeypatch.delenv(claims_paths.INTERNAL_REPO_ENV, raising=False)
    return repo, internal, origin


def test_sync_commits_and_pushes_only_claims(internal_clone) -> None:
    repo, internal, origin = internal_clone
    (internal / "claims" / "free_claims.approved.json").write_text(
        '{"ids": ["epic-a"]}\n', encoding="utf-8"
    )
    (internal / "notes.txt").write_text("edited but not staged\n", encoding="utf-8")
    result = sync_claims_decisions(repo, message="claims: test")
    assert result["changed"] is True
    assert result["pushed"] is True
    assert result["sha"] == _git(origin, "rev-parse", "--short", "main")
    files = _git(origin, "show", "--name-only", "--format=", "main").splitlines()
    assert files == ["claims/free_claims.approved.json"]
    assert "notes.txt" in _git(internal, "status", "--short")


def test_sync_noop_when_unchanged(internal_clone) -> None:
    repo, _, origin = internal_clone
    before = _git(origin, "rev-parse", "--short", "main")
    result = sync_claims_decisions(repo)
    assert result["changed"] is False
    assert result["sha"] == before


def test_sync_rebases_over_remote_change(internal_clone, tmp_path: Path) -> None:
    repo, internal, origin = internal_clone
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(origin), str(other))
    for key, val in (("user.email", "ci@example.invalid"), ("user.name", "ci")):
        _git(other, "config", key, val)
    (other / "claims" / "auto_decisions.json").write_text('{"approve": []}\n', encoding="utf-8")
    _git(other, "add", ".")
    _git(other, "commit", "-q", "-m", "ci autopilot")
    _git(other, "push", "-q")
    (internal / "claims" / "free_claims.approved.json").write_text(
        '{"ids": ["epic-b"]}\n', encoding="utf-8"
    )
    result = sync_claims_decisions(repo)
    assert result["pushed"] is True
    log = _git(origin, "log", "--format=%s", "main").splitlines()
    assert log[:2] == ["claims: owner decisions from admin", "ci autopilot"]


def test_sync_missing_clone_raises(tmp_path: Path) -> None:
    with pytest.raises(ClaimsSyncError, match="not found"):
        sync_claims_decisions(tmp_path)


def test_sync_aborts_rebase_on_pull_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "baklog-internal" / "claims").mkdir(parents=True)
    repo = tmp_path / "steam-backlog"
    repo.mkdir()
    monkeypatch.delenv(claims_paths.INTERNAL_REPO_ENV, raising=False)
    calls: list[list[str]] = []

    def fake(cmd, **kwargs):
        calls.append(cmd[3:])
        sub = cmd[3]
        if sub == "diff":
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if sub == "pull":
            return subprocess.CompletedProcess(cmd, 1, "", "CONFLICT (content)")
        return subprocess.CompletedProcess(cmd, 0, "abc123\n", "")

    with pytest.raises(ClaimsSyncError, match="CONFLICT"):
        sync_claims_decisions(repo, runner=fake)
    subs = [c[0] for c in calls]
    assert subs == ["add", "diff", "commit", "pull", "rebase"]
    assert calls[-1] == ["rebase", "--abort"]
