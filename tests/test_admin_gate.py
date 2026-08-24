"""Tests for admin attach gate vs default installed data root."""

from __future__ import annotations

from pathlib import Path

from shared.admin_gate import resolve_admin_enabled


def test_admin_off_when_env_unset(tmp_path: Path) -> None:
    ok, warn = resolve_admin_enabled(tmp_path, env={})
    assert ok is False
    assert warn is None


def test_admin_ok_on_non_installed_root(tmp_path: Path) -> None:
    installed = tmp_path / "BAKLOG-Data"
    installed.mkdir()
    dev = tmp_path / "BAKLOG-Dev"
    dev.mkdir()
    ok, warn = resolve_admin_enabled(
        dev,
        env={"BAKLOG_ADMIN": "1"},
        default_installed_dir=installed,
    )
    assert ok is True
    assert warn is None


def test_admin_refused_on_default_installed_root(tmp_path: Path) -> None:
    installed = tmp_path / "BAKLOG-Data"
    installed.mkdir()
    ok, warn = resolve_admin_enabled(
        installed,
        env={"BAKLOG_ADMIN": "1"},
        default_installed_dir=installed,
    )
    assert ok is False
    assert warn is not None
    assert "BAKLOG_ADMIN_ALLOW_INSTALLED" in warn


def test_admin_allow_installed_override(tmp_path: Path) -> None:
    installed = tmp_path / "BAKLOG-Data"
    installed.mkdir()
    ok, warn = resolve_admin_enabled(
        installed,
        env={"BAKLOG_ADMIN": "1", "BAKLOG_ADMIN_ALLOW_INSTALLED": "1"},
        default_installed_dir=installed,
    )
    assert ok is True
    assert warn is None
