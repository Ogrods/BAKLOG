import plistlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import shared.startup as startup


def test_startup_supported_on_known_platforms(monkeypatch):
    for plat in ("win32", "darwin", "linux"):
        monkeypatch.setattr(sys, "platform", plat)
        assert startup.startup_supported() is True
    monkeypatch.setattr(sys, "platform", "freebsd")
    assert startup.startup_supported() is False


def test_startup_argv_frozen_uses_tray_exe(monkeypatch, tmp_path):
    tray_exe = tmp_path / "BAKLOG Tray.exe"
    tray_exe.write_text("tray", encoding="utf-8")
    monkeypatch.setattr(startup, "is_frozen", lambda: True)
    monkeypatch.setattr(startup, "frozen_tray_exe", lambda: tray_exe)
    assert startup.startup_argv() == [str(tray_exe)]


def test_startup_argv_frozen_falls_back_to_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(startup, "is_frozen", lambda: True)
    monkeypatch.setattr(startup, "frozen_tray_exe", lambda: tmp_path / "missing.exe")
    monkeypatch.setattr(startup.sys, "executable", "C:\\fallback\\BAKLOG.exe")
    assert startup.startup_argv() == ["C:\\fallback\\BAKLOG.exe"]


def test_startup_argv_dev_ends_with_tray_app(monkeypatch):
    monkeypatch.setattr(startup, "is_frozen", lambda: False)
    monkeypatch.setattr(startup, "python_executable", lambda: "/venv/bin/python")
    monkeypatch.setattr(startup, "pythonw_executable", lambda: "/venv/Scripts/pythonw.exe")
    argv = startup.startup_argv()
    assert len(argv) == 2
    assert argv[0] in ("/venv/bin/python", "/venv/Scripts/pythonw.exe")
    assert argv[1].endswith("tray_app.py")


def test_startup_argv_dev_windows_prefers_pythonw(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(startup, "is_frozen", lambda: False)
    monkeypatch.setattr(startup, "pythonw_executable", lambda: "C:\\proj\\.venv\\Scripts\\pythonw.exe")
    argv = startup.startup_argv()
    assert argv[0] == "C:\\proj\\.venv\\Scripts\\pythonw.exe"


def test_pythonw_executable_honors_override(monkeypatch):
    monkeypatch.setenv("BAKLOG_PYTHON", "/custom/pythonw")
    assert startup.pythonw_executable() == "/custom/pythonw"


def test_toggle_startup_enables_when_disabled(monkeypatch):
    monkeypatch.setattr(startup, "is_startup_enabled", lambda: False)
    calls = []
    monkeypatch.setattr(startup, "enable_startup", lambda: calls.append("enable"))
    monkeypatch.setattr(startup, "disable_startup", lambda: calls.append("disable"))
    startup.toggle_startup()
    assert calls == ["enable"]


def test_toggle_startup_disables_when_enabled(monkeypatch):
    monkeypatch.setattr(startup, "is_startup_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(startup, "enable_startup", lambda: calls.append("enable"))
    monkeypatch.setattr(startup, "disable_startup", lambda: calls.append("disable"))
    startup.toggle_startup()
    assert calls == ["disable"]


class _FakeRegKey:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_win_is_enabled_true_when_value_exists(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def fake_open(key, subkey, reserved, access):
        return _FakeRegKey()

    def fake_query(key, name):
        assert name == startup._RUN_VALUE
        return ("cmd", 1)

    fake_winreg = MagicMock()
    fake_winreg.HKEY_CURRENT_USER = 0
    fake_winreg.KEY_READ = 1
    fake_winreg.OpenKey = fake_open
    fake_winreg.QueryValueEx = fake_query
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert startup._win_is_enabled() is True


def test_win_is_enabled_false_on_missing_value(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")

    def fake_open(key, subkey, reserved, access):
        raise OSError("missing")

    fake_winreg = MagicMock()
    fake_winreg.HKEY_CURRENT_USER = 0
    fake_winreg.KEY_READ = 1
    fake_winreg.OpenKey = fake_open
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    assert startup._win_is_enabled() is False


def test_win_enable_sets_registry_value(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(startup, "startup_argv", lambda: ["C:\\pythonw.exe", "C:\\tray_app.py"])
    stored = {}

    def fake_create(key, subkey):
        return _FakeRegKey()

    def fake_set(key, name, reserved, typ, value):
        stored[name] = value

    fake_winreg = MagicMock()
    fake_winreg.HKEY_CURRENT_USER = 0
    fake_winreg.REG_SZ = 1
    fake_winreg.CreateKey = fake_create
    fake_winreg.SetValueEx = fake_set
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    startup._win_enable()
    assert startup._RUN_VALUE in stored
    assert "tray_app.py" in stored[startup._RUN_VALUE]


def test_win_disable_deletes_value(monkeypatch):
    deleted = []

    def fake_open(key, subkey, reserved, access):
        return _FakeRegKey()

    def fake_delete(key, name):
        deleted.append(name)

    fake_winreg = MagicMock()
    fake_winreg.HKEY_CURRENT_USER = 0
    fake_winreg.KEY_SET_VALUE = 2
    fake_winreg.OpenKey = fake_open
    fake_winreg.DeleteValue = fake_delete
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    startup._win_disable()
    assert deleted == [startup._RUN_VALUE]


def test_mac_enable_writes_plist_and_loads(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(startup, "startup_argv", lambda: ["/venv/bin/python", "/app/tray_app.py"])
    agent_dir = tmp_path / "Library" / "LaunchAgents"
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    launchctl_calls = []

    def fake_run(cmd, **kwargs):
        launchctl_calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    startup._mac_enable()
    plist_path = agent_dir / startup._LAUNCH_AGENT_NAME
    assert plist_path.is_file()
    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    assert data["Label"] == startup._LAUNCH_AGENT_LABEL
    assert data["ProgramArguments"] == ["/venv/bin/python", "/app/tray_app.py"]
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] is False
    assert launchctl_calls == [["launchctl", "load", str(plist_path)]]


def test_mac_disable_unloads_and_removes_plist(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    agent_dir = tmp_path / "Library" / "LaunchAgents"
    agent_dir.mkdir(parents=True)
    plist_path = agent_dir / startup._LAUNCH_AGENT_NAME
    plist_path.write_bytes(b"plist")
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    launchctl_calls = []

    def fake_run(cmd, **kwargs):
        launchctl_calls.append(cmd)
        return MagicMock(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    startup._mac_disable()
    assert not plist_path.is_file()
    assert launchctl_calls == [["launchctl", "unload", str(plist_path)]]


def test_mac_is_enabled_when_plist_exists(monkeypatch, tmp_path):
    agent_dir = tmp_path / "Library" / "LaunchAgents"
    agent_dir.mkdir(parents=True)
    (agent_dir / startup._LAUNCH_AGENT_NAME).write_bytes(b"x")
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    assert startup._mac_is_enabled() is True


def test_linux_enable_writes_desktop_file(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(startup, "startup_argv", lambda: ["/venv/bin/python", "/app/tray_app.py"])
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    startup._linux_enable()
    desktop = tmp_path / ".config" / "autostart" / startup._DESKTOP_NAME
    assert desktop.is_file()
    text = desktop.read_text(encoding="utf-8")
    assert "Name=BAKLOG" in text
    assert "Exec=/venv/bin/python /app/tray_app.py" in text
    assert "X-GNOME-Autostart-enabled=true" in text


def test_linux_disable_removes_desktop_file(monkeypatch, tmp_path):
    desktop_dir = tmp_path / ".config" / "autostart"
    desktop_dir.mkdir(parents=True)
    desktop = desktop_dir / startup._DESKTOP_NAME
    desktop.write_text("[Desktop Entry]\n", encoding="utf-8")
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    startup._linux_disable()
    assert not desktop.is_file()


def test_linux_is_enabled_when_desktop_exists(monkeypatch, tmp_path):
    desktop_dir = tmp_path / ".config" / "autostart"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / startup._DESKTOP_NAME).write_text("x", encoding="utf-8")
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    assert startup._linux_is_enabled() is True


def test_is_startup_enabled_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd")
    assert startup.is_startup_enabled() is False


def test_enable_disable_noop_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "freebsd")
    startup.enable_startup()
    startup.disable_startup()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry integration")
def test_win_round_trip_integration(monkeypatch):
    try:
        import winreg
    except ImportError:
        pytest.skip("winreg unavailable")
    monkeypatch.setattr(startup, "startup_argv", lambda: ["test.exe", "tray"])
    startup.disable_startup()
    assert startup.is_startup_enabled() is False
    startup.enable_startup()
    try:
        assert startup.is_startup_enabled() is True
    finally:
        startup.disable_startup()
    assert startup.is_startup_enabled() is False


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS LaunchAgent integration")
def test_mac_round_trip_integration(monkeypatch, tmp_path):
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(startup, "startup_argv", lambda: [sys.executable, str(Path(__file__).resolve())])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: MagicMock(returncode=0))
    startup.disable_startup()
    assert startup.is_startup_enabled() is False
    startup.enable_startup()
    try:
        assert startup.is_startup_enabled() is True
    finally:
        startup.disable_startup()
    assert startup.is_startup_enabled() is False


@pytest.mark.skipif(sys.platform != "linux", reason="Linux XDG autostart integration")
def test_linux_round_trip_integration(monkeypatch, tmp_path):
    monkeypatch.setattr(startup.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(startup, "startup_argv", lambda: [sys.executable, str(Path(__file__).resolve())])
    startup.disable_startup()
    assert startup.is_startup_enabled() is False
    startup.enable_startup()
    try:
        assert startup.is_startup_enabled() is True
    finally:
        startup.disable_startup()
    assert startup.is_startup_enabled() is False
