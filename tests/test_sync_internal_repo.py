"""Public pre-push must never commit baklog-internal into Ogrods/BAKLOG."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SYNC_PS1 = ROOT / "scripts" / "sync-internal-repo.ps1"
HOOK_PS1 = ROOT / "scripts" / "hooks" / "pre-push-internal.ps1"


def test_sync_script_clears_hook_git_env_and_merge_copies():
    text = SYNC_PS1.read_text(encoding="utf-8")
    assert "function Clear-InheritedGitEnv" in text
    assert "GIT_DIR" in text
    assert "GIT_INDEX_FILE" in text
    assert "git -C $Path" in text or "git -C $InternalRepo" in text
    assert "Remove-Item $dest -Recurse" not in text
    assert "baklog-internal" in text
    assert "Ogrods/BAKLOG" in text
    assert "reset" in text and "--hard" in text
    hook = HOOK_PS1.read_text(encoding="utf-8")
    assert "BAKLOG_SKIP_INTERNAL_SYNC" in hook
    assert "GIT_DIR" in hook


def _git(cwd: Path, *args: str, extra_env: dict[str, str] | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        {
            "GIT_AUTHOR_NAME": "baklog-test",
            "GIT_AUTHOR_EMAIL": "baklog-test@example.com",
            "GIT_COMMITTER_NAME": "baklog-test",
            "GIT_COMMITTER_EMAIL": "baklog-test@example.com",
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stdout}\n{proc.stderr}"
    return (proc.stdout or "").strip()


def _init_repo(path: Path, *, origin: str) -> None:
    path.mkdir(parents=True)
    subprocess.run(
        ["git", "init"],
        check=True,
        capture_output=True,
        text=True,
        cwd=path,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    _git(path, "config", "user.email", "baklog-test@example.com")
    _git(path, "config", "user.name", "baklog-test")
    _git(path, "checkout", "-B", "main")
    _git(path, "remote", "add", "origin", origin)


def _run_sync(
    *,
    repo_root: Path,
    internal: Path,
    manifest: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SYNC_PS1),
            "-RepoRoot",
            str(repo_root),
            "-InternalRepo",
            str(internal),
            "-ManifestFile",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell sync script")
def test_sync_with_hook_git_dir_does_not_move_public_head(tmp_path: Path) -> None:
    public = tmp_path / "public"
    internal = tmp_path / "internal"
    _init_repo(public, origin="https://github.com/Ogrods/BAKLOG.git")
    _init_repo(internal, origin="https://github.com/Ogrods/baklog-internal.git")

    pub_rules = public / ".cursor" / "rules"
    pub_rules.mkdir(parents=True)
    (pub_rules / "landing.mdc").write_text("public-landing-rule\n", encoding="utf-8")
    (public / "keep-public.txt").write_text("public\n", encoding="utf-8")
    _git(public, "add", "-A")
    _git(public, "commit", "-m", "public base")
    public_head = _git(public, "rev-parse", "HEAD")

    int_rules = internal / ".cursor" / "rules"
    int_rules.mkdir(parents=True)
    (int_rules / "internal-workflow.mdc").write_text("keep-me\n", encoding="utf-8")
    (internal / "README.md").write_text("internal\n", encoding="utf-8")
    _git(internal, "add", "-A")
    _git(internal, "commit", "-m", "internal base")
    internal_head = _git(internal, "rev-parse", "HEAD")

    manifest = tmp_path / "manifest.txt"
    manifest.write_text(".cursor/rules/\n", encoding="utf-8")

    proc = _run_sync(
        repo_root=public,
        internal=internal,
        manifest=manifest,
        extra_env={"GIT_DIR": str(public / ".git")},
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"

    assert _git(public, "rev-parse", "HEAD") == public_head
    assert _git(internal, "rev-parse", "HEAD") != internal_head
    assert (internal / ".cursor" / "rules" / "landing.mdc").read_text(
        encoding="utf-8"
    ) == "public-landing-rule\n"
    assert (internal / ".cursor" / "rules" / "internal-workflow.mdc").read_text(
        encoding="utf-8"
    ) == "keep-me\n"
    assert (public / "keep-public.txt").read_text(encoding="utf-8") == "public\n"


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell sync script")
def test_sync_refuses_public_baklog_as_destination(tmp_path: Path) -> None:
    public = tmp_path / "public"
    _init_repo(public, origin="https://github.com/Ogrods/BAKLOG.git")
    (public / "README.md").write_text("public\n", encoding="utf-8")
    _git(public, "add", "-A")
    _git(public, "commit", "-m", "public base")
    public_head = _git(public, "rev-parse", "HEAD")

    manifest = tmp_path / "manifest.txt"
    manifest.write_text("README.md\n", encoding="utf-8")

    proc = _run_sync(repo_root=public, internal=public, manifest=manifest)
    assert proc.returncode != 0
    blob = f"{proc.stdout}\n{proc.stderr}"
    assert "same git work tree" in blob or "not baklog-internal" in blob
    assert _git(public, "rev-parse", "HEAD") == public_head
