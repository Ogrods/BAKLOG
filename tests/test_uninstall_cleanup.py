import sys
from pathlib import Path
from unittest.mock import MagicMock

from shared import uninstall_cleanup


def test_cleanup_autostart_calls_disable(monkeypatch):
    called = {"n": 0}

    def _disable():
        called["n"] += 1

    monkeypatch.setattr(uninstall_cleanup, "disable_startup", _disable)
    uninstall_cleanup.cleanup_autostart()
    assert called["n"] == 1


def test_wipe_user_data_removes_dir_and_keyring(monkeypatch, tmp_path):
    data_dir = tmp_path / "BAKLOG-Data"
    data_dir.mkdir()
    (data_dir / "profiles").mkdir()
    keyring_calls = {"n": 0}
    monkeypatch.setattr(uninstall_cleanup, "_request_graceful_shutdown", lambda: False)
    monkeypatch.setattr(uninstall_cleanup, "disable_startup", lambda: None)
    monkeypatch.setattr(
        "auth.secrets.delete_keyring_master_key", lambda: keyring_calls.update(n=keyring_calls["n"] + 1) or True
    )
    notes = uninstall_cleanup.wipe_user_data(data_dir)
    assert not data_dir.exists()
    assert keyring_calls["n"] == 1
    assert any("keyring" in note.lower() for note in notes)
    assert "BAKLOG-Data" in notes[-1]


def test_request_graceful_shutdown_when_port_closed(monkeypatch):
    monkeypatch.setattr(uninstall_cleanup.socket, "create_connection", MagicMock(side_effect=OSError()))
    assert uninstall_cleanup._request_graceful_shutdown() is False


def test_tray_uninstall_wipe_flag_exits_zero(monkeypatch):
    import tray_app

    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    monkeypatch.setattr("shared.uninstall_cleanup.wipe_user_data", lambda _path: ["Removed test data"])
    monkeypatch.setattr("shared.install_paths.resolved_data_dir_for_uninstall", lambda: Path("/tmp/BAKLOG-Data"))
    monkeypatch.setattr(sys, "argv", ["BAKLOG Tray.exe", "--uninstall-wipe-user-data"])
    assert tray_app.main() == 0


def test_tray_uninstall_cleanup_flag_exits_zero(monkeypatch):
    import tray_app

    called = {"n": 0}

    def _cleanup():
        called["n"] += 1

    monkeypatch.setattr(tray_app, "is_frozen", lambda: True)
    monkeypatch.setattr("shared.uninstall_cleanup.cleanup_autostart", _cleanup)
    monkeypatch.setattr(sys, "argv", ["BAKLOG Tray.exe", "--uninstall-cleanup"])
    assert tray_app.main() == 0
    assert called["n"] == 1


def test_tray_uninstall_flags_rejected_in_dev(monkeypatch):
    import tray_app

    monkeypatch.setattr(tray_app, "is_frozen", lambda: False)
    monkeypatch.setattr(sys, "argv", ["tray_app.py", "--uninstall-wipe-user-data"])
    assert tray_app.main() == 1
