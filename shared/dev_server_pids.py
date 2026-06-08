"""PID/port helpers for the local BAKLOG dev server.

Shared between ``server.py`` (single-instance reclaim) and
``scripts/stop_baklog.py`` (operator cleanup) so the netstat / tasklist /
taskkill logic lives in one place instead of being copy-pasted.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) is not a reliable existence probe on Windows (WinError 87).
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            line = (out.stdout or "").strip()
            return bool(line) and "no tasks are running" not in line.lower()
        except (OSError, subprocess.TimeoutExpired):
            return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def pid_is_python_server(pid: int) -> bool:
    """Best-effort confirm pid is a live Python process running this server,
    so reclaim never kills an unrelated process that reused the pid."""
    if not pid_alive(pid):
        return False
    if sys.platform != "win32":
        return True
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "python" in (out.stdout or "").lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def pid_listening_on_port(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> int | None:
    """The PID currently LISTENING on host:port, via netstat (Windows) — covers
    orphans that predate the pid file (e.g. closed-terminal leftovers)."""
    if sys.platform != "win32":
        return None
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    needle = f"{host}:{port}"
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if (
            len(parts) >= 5
            and parts[0].upper() == "TCP"
            and parts[1] == needle
            and parts[3].upper() == "LISTENING"
        ):
            if parts[-1].isdigit():
                return int(parts[-1])
    return None
