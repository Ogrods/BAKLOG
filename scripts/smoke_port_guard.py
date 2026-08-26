"""Dev-port ownership checks for frozen smoke tests (127.0.0.1:8765)."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

from shared.dev_server_pids import DEFAULT_HOST, DEFAULT_PORT, pid_listening_on_port
from shared.subprocess_guard import related_pids, terminate_pid_tree


def port_listener_pid(
    host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> int | None:
    if sys.platform == "win32":
        return pid_listening_on_port(host, port)
    try:
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for token in (out.stdout or "").split():
        if token.isdigit():
            return int(token)
    return None


def proc_owns_dev_port(
    proc: subprocess.Popen,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> bool:
    if proc.poll() is not None:
        return False
    listener = port_listener_pid(host, port)
    if listener is None:
        return False
    return listener in related_pids(proc.pid)


def wait_for_owned_server(
    proc: subprocess.Popen,
    base: str,
    *,
    timeout_sec: float = 25.0,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> tuple[bool, str | None]:
    """Wait until /api/config responds from the spawned process tree."""
    deadline = time.monotonic() + timeout_sec
    collision_holder: int | None = None
    while time.monotonic() < deadline:
        listener = port_listener_pid(host, port)
        if listener is not None and proc.poll() is None:
            if listener not in related_pids(proc.pid):
                collision_holder = listener
        if proc_owns_dev_port(proc, host=host, port=port):
            try:
                with urllib.request.urlopen(f"{base}/api/config", timeout=2) as resp:
                    if resp.status == 200:
                        return True, None
            except (urllib.error.URLError, TimeoutError, OSError):
                pass
        time.sleep(0.4)
    if collision_holder is not None:
        return (
            False,
            f"port {host}:{port} held by pid {collision_holder}, not spawned smoke process "
            f"(pid {proc.pid}); run scripts/stop_baklog.py",
        )
    return False, f"server did not respond within {timeout_sec}s"


def wait_for_http_server(
    proc: subprocess.Popen,
    base: str,
    *,
    timeout_sec: float = 30.0,
) -> tuple[bool, str | None]:
    """Wait until /api/config responds after a fresh spawn (port already cleared)."""
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        exit_code = proc.poll()
        if exit_code is not None and exit_code != 0:
            return False, f"server exited early with code {exit_code}"
        try:
            with urllib.request.urlopen(f"{base}/api/config", timeout=2) as resp:
                if resp.status == 200:
                    return True, None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.4)
    exit_code = proc.poll()
    suffix = f" (proc exit {exit_code})" if exit_code is not None else ""
    return False, f"server did not respond within {timeout_sec}s{suffix}"


def ensure_dev_port_free(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout_sec: float = 15.0,
) -> tuple[bool, str | None]:
    """Terminate any listener on the dev port and wait until it is free."""
    holder = port_listener_pid(host, port)
    if holder is None:
        return True, None
    terminate_pid_tree(holder)
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if port_listener_pid(host, port) is None:
            return True, None
        time.sleep(0.25)
    holder = port_listener_pid(host, port)
    if holder is None:
        return True, None
    return False, port_collision_message(holder, host=host, port=port)


def port_collision_message(
    holder: int, *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT
) -> str:
    return (
        f"port {host}:{port} already in use by pid {holder}; "
        "run scripts/stop_baklog.py"
    )
