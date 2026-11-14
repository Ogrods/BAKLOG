"""Tests for Windows uninstall cleanup helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from shared import uninstall_cleanup


def test_cleanup_autostart_calls_disable(monkeypatch) -> None:
    called = {"n": 0}

    def _disable() -> None:
        called["n"] += 1

    monkeypatch.setattr(uninstall_cleanup, "disable_startup", _disable)
    uninstall_cleanup.cleanup_autostart()
    assert called["n"] == 1


def test_wipe_user_data_removes_dir_and_keyring(monkeypatch, tmp_path: Path) -> None:
    data_dir = tmp_path / "BAKLOG-Data"
    data_dir.mkdir()
    (data_dir / "profiles").mkdir()
    keyring_calls = {"n": 0}

    monkeypatch.setattr(uninstall_cleanup, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(uninstall_cleanup, "disable_startup", lambda: None)
    monkeypatch.setattr(
        "auth.secrets.delete_keyring_master_key",
        lambda: keyring_calls.update(n=keyring_calls["n"] + 1) or True,
    )

    notes = uninstall_cleanup.wipe_user_data(data_dir)
    assert not data_dir.exists()
    assert keyring_calls["n"] == 1
    assert any("keyring" in note.lower() for note in notes)
    assert any("BAKLOG-Data" in note for note in notes)


def test_wipe_user_data_skips_keyring_when_rmtree_fails(
    monkeypatch, tmp_path: Path
) -> None:
    data_dir = tmp_path / "BAKLOG-Data"
    data_dir.mkdir()
    keyring_calls = {"n": 0}
    order: list[str] = []

    monkeypatch.setattr(uninstall_cleanup, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(uninstall_cleanup, "disable_startup", lambda: None)
    monkeypatch.setattr(
        "auth.secrets.delete_keyring_master_key",
        lambda: (
            order.append("keyring")
            or keyring_calls.update(n=keyring_calls["n"] + 1)
            or True
        ),
    )

    def _fail_rmtree(path):  # noqa: ANN001
        order.append("rmtree")
        raise OSError("locked")

    monkeypatch.setattr(uninstall_cleanup.shutil, "rmtree", _fail_rmtree)

    with pytest.raises(uninstall_cleanup.WipeIncompleteError):
        uninstall_cleanup.wipe_user_data(data_dir)
    assert order == ["rmtree", "rmtree", "rmtree"]
    assert keyring_calls["n"] == 0
    assert data_dir.exists()


def test_wipe_refuses_unexpected_dir_name(monkeypatch, tmp_path: Path) -> None:
    bad = tmp_path / "Documents"
    bad.mkdir()
    monkeypatch.setattr(uninstall_cleanup, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(uninstall_cleanup, "disable_startup", lambda: None)
    with pytest.raises(uninstall_cleanup.WipeIncompleteError):
        uninstall_cleanup.wipe_user_data(bad)


def test_wipe_portable_bundle_keeps_tray_exe(monkeypatch, tmp_path: Path) -> None:
    from shared import install_paths

    app_dir = tmp_path / "BAKLOG"
    app_dir.mkdir()
    (app_dir / "BAKLOG Tray.exe").write_text("tray", encoding="utf-8")
    (app_dir / "_internal").mkdir()
    (app_dir / "profiles").mkdir()
    (app_dir / "profiles" / "index.json").write_text("{}", encoding="utf-8")
    (app_dir / "portable.txt").write_text("", encoding="utf-8")
    (app_dir / "games_steam.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(uninstall_cleanup, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(uninstall_cleanup, "disable_startup", lambda: None)
    monkeypatch.setattr(
        "auth.secrets.delete_keyring_master_key",
        lambda: True,
    )
    monkeypatch.setattr(install_paths, "is_frozen", lambda: True)
    monkeypatch.setattr(install_paths, "is_portable_frozen", lambda: True)
    monkeypatch.setattr(install_paths, "frozen_bundle_dir", lambda: app_dir.resolve())

    notes = uninstall_cleanup.wipe_user_data(app_dir)
    assert (app_dir / "BAKLOG Tray.exe").is_file()
    assert (app_dir / "_internal").is_dir()
    assert not (app_dir / "profiles").exists()
    assert not (app_dir / "games_steam.json").exists()
    assert any("keyring" in n.lower() for n in notes)


def test_tray_uninstall_wipe_failure_exits_nonzero(monkeypatch) -> None:
    import tray_app

    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    monkeypatch.setattr(
        "shared.uninstall_cleanup.wipe_user_data",
        lambda _path: (_ for _ in ()).throw(
            uninstall_cleanup.WipeIncompleteError("boom")
        ),
    )
    monkeypatch.setattr(
        "shared.install_paths.resolved_data_dir_for_uninstall",
        lambda: Path("/tmp/BAKLOG-Data"),
    )
    monkeypatch.setattr(sys, "argv", ["BAKLOG Tray.exe", "--uninstall-wipe-user-data"])
    assert tray_app.main() == 1


def test_request_graceful_shutdown_when_port_closed(monkeypatch) -> None:
    monkeypatch.setattr(uninstall_cleanup.socket, "create_connection", MagicMock(side_effect=OSError()))
    assert uninstall_cleanup._request_graceful_shutdown() is False


def test_tray_uninstall_wipe_flag_exits_zero(monkeypatch) -> None:
    import tray_app

    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    monkeypatch.setattr(
        "shared.uninstall_cleanup.wipe_user_data",
        lambda _path: ["Removed test data"],
    )
    monkeypatch.setattr(
        "shared.install_paths.resolved_data_dir_for_uninstall",
        lambda: Path("/tmp/BAKLOG-Data"),
    )
    monkeypatch.setattr(sys, "argv", ["BAKLOG Tray.exe", "--uninstall-wipe-user-data"])
    assert tray_app.main() == 0


def test_tray_uninstall_cleanup_flag_exits_zero(monkeypatch) -> None:
    import tray_app

    called = {"n": 0}

    def _cleanup() -> None:
        called["n"] += 1

    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    monkeypatch.setattr("shared.uninstall_cleanup.cleanup_autostart", _cleanup)
    monkeypatch.setattr(sys, "argv", ["BAKLOG Tray.exe", "--uninstall-cleanup"])
    assert tray_app.main() == 0
    assert called["n"] == 1


def test_tray_uninstall_flags_rejected_in_dev(monkeypatch) -> None:
    import tray_app

    monkeypatch.setattr(tray_app, "is_frozen", lambda: False)
    monkeypatch.setattr(sys, "argv", ["tray_app.py", "--uninstall-wipe-user-data"])
    assert tray_app.main() == 1
