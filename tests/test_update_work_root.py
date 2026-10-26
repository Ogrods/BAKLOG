"""POSIX update workspace must match packaging/apply_update.sh."""

from __future__ import annotations

from shared.update_ready_state import default_work_root, posix_update_temp_base


def test_posix_update_temp_base_prefers_tmpdir(monkeypatch) -> None:
    monkeypatch.setenv("TMPDIR", "/custom/tmp")
    monkeypatch.setenv("TEMP", "/windows/style/temp")
    assert str(posix_update_temp_base()).replace("\\", "/") == "/custom/tmp"


def test_posix_update_temp_base_defaults_to_tmp(monkeypatch) -> None:
    monkeypatch.delenv("TMPDIR", raising=False)
    assert str(posix_update_temp_base()).replace("\\", "/") == "/tmp"


def test_default_work_root_linux_matches_apply_script(monkeypatch) -> None:
    import sys

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("TMPDIR", "/run/user/1000")
    monkeypatch.setenv("TEMP", "/should/not/win")
    root = default_work_root()
    assert str(root).replace("\\", "/").endswith("/run/user/1000/BAKLOG-update")
