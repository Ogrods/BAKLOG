"""Cross-platform login startup registration for the BAKLOG tray launcher.

Windows: per-user registry Run key.
macOS: LaunchAgent plist in ~/Library/LaunchAgents.
Linux: XDG autostart .desktop in ~/.config/autostart.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from shared.install_paths import bundle_root, is_frozen

_SUPPORTED = frozenset({"win32", "darwin", "linux"})

# Windows registry
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "BAKLOG"

# macOS LaunchAgent
_LAUNCH_AGENT_LABEL = "com.baklog.tray"
_LAUNCH_AGENT_NAME = f"{_LAUNCH_AGENT_LABEL}.plist"

# Linux XDG autostart
_DESKTOP_NAME = "baklog-tray.desktop"


def startup_supported() -> bool:
    """True when the current OS has a login-startup backend."""
    return sys.platform in _SUPPORTED


def python_executable() -> str:
    """Interpreter for dev tray launches. Prefers the project venv."""
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = bundle_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",  # Windows
        root / ".venv" / "bin" / "python",          # POSIX
        root / ".venv" / "bin" / "python3",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return sys.executable


def pythonw_executable() -> str:
    """Windows no-console interpreter; falls back to python_executable()."""
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = bundle_root()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if pythonw.is_file():
        return str(pythonw)
    return python_executable()


def startup_argv() -> list[str]:
    """Argv used to launch the tray at login."""
    if is_frozen():
        return [sys.executable]
    if sys.platform == "win32":
        return [pythonw_executable(), str(bundle_root() / "tray_app.py")]
    return [python_executable(), str(bundle_root() / "tray_app.py")]


def _launch_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / _LAUNCH_AGENT_NAME


def _desktop_path() -> Path:
    return Path.home() / ".config" / "autostart" / _DESKTOP_NAME


def _argv_to_exec_line(argv: list[str]) -> str:
    """Serialize argv for a .desktop Exec= line (POSIX shell quoting)."""
    return shlex.join(argv)


# --- Windows ---


def _win_is_enabled() -> bool:
    try:
        import winreg
    except ImportError:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
            return True
    except OSError:
        return False


def _win_enable() -> None:
    import winreg

    cmd = subprocess.list2cmdline(startup_argv())
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
        winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, cmd)


def _win_disable() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _RUN_VALUE)
    except FileNotFoundError:
        pass
    except OSError:
        pass


# --- macOS ---


def _mac_is_enabled() -> bool:
    return _launch_agent_path().is_file()


def _mac_enable() -> None:
    path = _launch_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": _LAUNCH_AGENT_LABEL,
        "ProgramArguments": startup_argv(),
        "RunAtLoad": True,
        "KeepAlive": False,
    }
    with path.open("wb") as fh:
        plistlib.dump(plist, fh)
    subprocess.run(
        ["launchctl", "load", str(path)],
        check=False,
        capture_output=True,
    )


def _mac_disable() -> None:
    path = _launch_agent_path()
    if not path.is_file():
        return
    subprocess.run(
        ["launchctl", "unload", str(path)],
        check=False,
        capture_output=True,
    )
    try:
        path.unlink()
    except OSError:
        pass


# --- Linux ---


def _linux_is_enabled() -> bool:
    return _desktop_path().is_file()


def _linux_enable() -> None:
    path = _desktop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = _argv_to_exec_line(startup_argv())
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=BAKLOG\n"
        f"Exec={exec_line}\n"
        "Hidden=false\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    path.write_text(content, encoding="utf-8")


def _linux_disable() -> None:
    path = _desktop_path()
    try:
        path.unlink()
    except OSError:
        pass


# --- Public API ---


def is_startup_enabled() -> bool:
    """True when BAKLOG is registered to start at login."""
    if not startup_supported():
        return False
    try:
        if sys.platform == "win32":
            return _win_is_enabled()
        if sys.platform == "darwin":
            return _mac_is_enabled()
        if sys.platform == "linux":
            return _linux_is_enabled()
    except Exception:  # noqa: BLE001 - startup checks must never crash the tray
        return False
    return False


def enable_startup() -> None:
    """Register BAKLOG to launch at login."""
    if not startup_supported():
        return
    try:
        if sys.platform == "win32":
            _win_enable()
        elif sys.platform == "darwin":
            _mac_enable()
        elif sys.platform == "linux":
            _linux_enable()
    except Exception:  # noqa: BLE001 - startup toggles must never crash the tray
        pass


def disable_startup() -> None:
    """Remove BAKLOG from login startup."""
    if not startup_supported():
        return
    try:
        if sys.platform == "win32":
            _win_disable()
        elif sys.platform == "darwin":
            _mac_disable()
        elif sys.platform == "linux":
            _linux_disable()
    except Exception:  # noqa: BLE001 - startup toggles must never crash the tray
        pass


def toggle_startup() -> None:
    """Flip login startup registration on or off."""
    if is_startup_enabled():
        disable_startup()
    else:
        enable_startup()
