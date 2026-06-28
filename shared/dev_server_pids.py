"""PID/port helpers for the local BAKLOG dev server.

Shared between ``server.py`` (single-instance reclaim) and
``scripts/stop_baklog.py`` (operator cleanup) so the netstat / tasklist /
taskkill logic lives in one place instead of being copy-pasted.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

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
    """Best-effort confirm pid is a live BAKLOG server process (dev python.exe or
    a frozen BAKLOG.exe) so reclaim never kills an unrelated process that reused
    the pid. Frozen tester builds run as ``BAKLOG.exe``, not ``python``."""
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
        name = (out.stdout or "").lower()
        return "python" in name or "baklog" in name
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


def port_busy(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """True when something is already accepting TCP on host:port."""
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def read_pid_file(pid_file: str | os.PathLike[str]) -> int | None:
    """The pid recorded in pid_file, or None when missing/garbage."""
    try:
        recorded = Path(pid_file).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(recorded) if recorded.isdigit() else None


def write_pid_file(pid_file: str | os.PathLike[str]) -> None:
    """Record the current process pid so a restart can reclaim an orphaned port."""
    try:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        print(f"[server] could not write pid file: {exc}", file=sys.stderr, flush=True)


def remove_own_pid_file(pid_file: str | os.PathLike[str]) -> None:
    """Remove pid_file only when it still records THIS process (atexit safety)."""
    try:
        path = Path(pid_file)
        if path.is_file() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def clear_stale_pid_file(pid_file: str | os.PathLike[str]) -> bool:
    """Delete pid_file when it points at a dead / non-server pid.

    Self-heals leftovers from a hard terminal close or taskkill, where the
    process died before ``atexit`` could remove its own pid file. Returns True
    when a stale file was removed. A live BAKLOG server's pid file is kept.
    """
    pid = read_pid_file(pid_file)
    if pid is None or pid == os.getpid():
        return False
    if pid_is_python_server(pid):
        return False
    try:
        Path(pid_file).unlink()
        return True
    except OSError:
        return False


def reclaim_stale_server(
    host: str, port: int, pid_file: str | os.PathLike[str]
) -> bool:
    """If the busy port is held by our own orphaned instance, terminate it so
    this start can take over. Prefers the pid file, falls back to whoever is
    listening on the port. Returns True if a reclaim was attempted."""
    me = os.getpid()
    for pid in (read_pid_file(pid_file), pid_listening_on_port(host, port)):
        if pid is None or pid == me:
            continue
        if not pid_is_python_server(pid):
            continue
        print(
            f"[server] port {port} held by orphaned instance (pid {pid}) - reclaiming it",
            file=sys.stderr,
            flush=True,
        )
        terminate_pid(pid)
        return True
    return False


def reclaim_or_exit(
    host: str,
    port: int,
    pid_file: str | os.PathLike[str],
    busy_msg: str,
) -> None:
    """Single-instance guard run at boot.

    Always self-heals a stale pid file. Then, if the port is busy and held by
    our own orphan, reclaims it and waits for the socket to close; otherwise
    prints ``busy_msg`` and exits(1) so two live servers never share the port.
    """
    clear_stale_pid_file(pid_file)
    if not port_busy(host, port):
        return
    if reclaim_stale_server(host, port, pid_file):
        for _ in range(30):  # up to ~3s for the orphan's socket to close
            time.sleep(0.1)
            if not port_busy(host, port):
                return
    print(busy_msg, file=sys.stderr, flush=True)
    raise SystemExit(1)
