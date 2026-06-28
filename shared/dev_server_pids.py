import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform == "win32":
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


def terminate_pid(pid):
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


def pid_is_python_server(pid):
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


def pid_listening_on_port(host=DEFAULT_HOST, port=DEFAULT_PORT):
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
        if len(parts) >= 5 and parts[0].upper() == "TCP" and (parts[1] == needle) and (parts[3].upper() == "LISTENING"):
            if parts[-1].isdigit():
                return int(parts[-1])
    return None


def port_busy(host=DEFAULT_HOST, port=DEFAULT_PORT):
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def read_pid_file(pid_file):
    try:
        recorded = Path(pid_file).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(recorded) if recorded.isdigit() else None


def write_pid_file(pid_file):
    try:
        Path(pid_file).write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        print(f"[server] could not write pid file: {exc}", file=sys.stderr, flush=True)


def remove_own_pid_file(pid_file):
    try:
        path = Path(pid_file)
        if path.is_file() and path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass


def clear_stale_pid_file(pid_file):
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


def reclaim_stale_server(host, port, pid_file):
    me = os.getpid()
    for pid in (read_pid_file(pid_file), pid_listening_on_port(host, port)):
        if pid is None or pid == me:
            continue
        if not pid_is_python_server(pid):
            continue
        print(
            f"[server] port {port} held by orphaned instance (pid {pid}) - reclaiming it", file=sys.stderr, flush=True
        )
        terminate_pid(pid)
        return True
    return False


def reclaim_or_exit(host, port, pid_file, busy_msg):
    clear_stale_pid_file(pid_file)
    if not port_busy(host, port):
        return
    if reclaim_stale_server(host, port, pid_file):
        for _ in range(30):
            time.sleep(0.1)
            if not port_busy(host, port):
                return
    print(busy_msg, file=sys.stderr, flush=True)
    raise SystemExit(1)
