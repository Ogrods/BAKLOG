import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from shared.install_paths import bundle_root, frozen_tray_exe, is_frozen

_SUPPORTED = frozenset({"win32", "darwin", "linux"})
_RUN_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Run"
_RUN_VALUE = "BAKLOG"
_LAUNCH_AGENT_LABEL = "com.baklog.tray"
_LAUNCH_AGENT_NAME = f"{_LAUNCH_AGENT_LABEL}.plist"
_DESKTOP_NAME = "baklog-tray.desktop"


def startup_supported():
    return sys.platform in _SUPPORTED


def python_executable():
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = bundle_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / ".venv" / "bin" / "python3",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return sys.executable


def pythonw_executable():
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = bundle_root()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.is_file():
        return str(pythonw)
    return python_executable()


def startup_argv():
    if is_frozen():
        tray = frozen_tray_exe()
        if tray.is_file():
            return [str(tray)]
        return [sys.executable]
    if sys.platform == "win32":
        return [pythonw_executable(), str(bundle_root() / "tray_app.py")]
    return [python_executable(), str(bundle_root() / "tray_app.py")]


def _launch_agent_path():
    return Path.home() / "Library" / "LaunchAgents" / _LAUNCH_AGENT_NAME


def _desktop_path():
    return Path.home() / ".config" / "autostart" / _DESKTOP_NAME


def _argv_to_exec_line(argv):
    return shlex.join(argv)


def _win_is_enabled():
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
            return True
    except OSError:
        return False


def _win_enable():
    import winreg

    cmd = subprocess.list2cmdline(startup_argv())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, cmd)


def _win_disable():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _win_run_command():
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, _RUN_VALUE)
            return str(value) if value else None
    except OSError:
        return None


def _parse_win_run_target(cmd):
    text = cmd.strip()
    if not text:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        if end > 0:
            return Path(text[1:end])
    parts = text.split()
    return Path(parts[0]) if parts else None


def reconcile_startup():
    if sys.platform != "win32":
        return False
    try:
        cmd = _win_run_command()
        if not cmd:
            return False
        target = _parse_win_run_target(cmd)
        if target is None or target.is_file():
            return False
        _win_disable()
        return True
    except Exception:
        return False


def _mac_is_enabled():
    return _launch_agent_path().is_file()


def _mac_enable():
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = {"Label": _LAUNCH_AGENT_LABEL, "ProgramArguments": startup_argv(), "RunAtLoad": True, "KeepAlive": False}
    with path.open("wb") as fh:
        plistlib.dump(plist, fh)
    subprocess.run(["launchctl", "load", str(path)], check=False, capture_output=True)


def _mac_disable():
    path = _launch_agent_path()
    if not path.is_file():
        return
    subprocess.run(["launchctl", "unload", str(path)], check=False, capture_output=True)
    try:
        path.unlink()
    except OSError:
        pass


def _linux_is_enabled():
    return _desktop_path().is_file()


def _linux_enable():
    path = _desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = _argv_to_exec_line(startup_argv())
    content = f"[Desktop Entry]\nType=Application\nName=BAKLOG\nExec={exec_line}\nHidden=false\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n"
    path.write_text(content, encoding="utf-8")


def _linux_disable():
    path = _desktop_path()
    try:
        path.unlink()
    except OSError:
        pass


def is_startup_enabled():
    if not startup_supported():
        return False
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        if sys.platform == "darwin":
            return _mac_is_enabled()
        if sys.platform == "linux":
            return _linux_is_enabled()
    except Exception:
        return False
    return False


def enable_startup():
    if not startup_supported():
        return
    try:
        if sys.platform == "win32":
            _win_enable()
        elif sys.platform == "darwin":
            _mac_enable()
        elif sys.platform == "linux":
            _linux_enable()
    except Exception:
        pass


def disable_startup():
    if not startup_supported():
        return
    try:
        if sys.platform == "win32":
            _win_disable()
        elif sys.platform == "darwin":
            _mac_disable()
        elif sys.platform == "linux":
            _linux_disable()
    except Exception:
        pass


def toggle_startup():
    if is_startup_enabled():
        disable_startup()
    else:
        enable_startup()
