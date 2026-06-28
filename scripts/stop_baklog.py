import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from shared.dev_server_pids import DEFAULT_HOST, DEFAULT_PORT, pid_listening_on_port
from shared.install_paths import data_root
from shared.subprocess_guard import related_pids, terminate_pid_tree

HOST = DEFAULT_HOST
PORT = int(os.environ.get("PORT", str(DEFAULT_PORT)))
PID_FILE = data_root() / ".baklog_server.pid"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _port_open():
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _request_graceful_shutdown():
    if not _port_open():
        return False
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/api/shutdown", method="POST", headers={"X-BAKLOG-Local": "1"}, data=b""
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        return False
    for _ in range(30):
        time.sleep(0.1)
        if not _port_open():
            return True
    return False


def _port_pids():
    pids = set()
    if sys.platform == "win32":
        pid = pid_listening_on_port(HOST, PORT)
        if pid:
            pids.add(pid)
    else:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{PORT}"], capture_output=True, text=True, timeout=10, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return pids
        pids.update((int(t) for t in (out.stdout or "").split() if t.isdigit()))
    pids.discard(os.getpid())
    return pids


def _cmdline_pids():
    pids = set()
    if sys.platform == "win32":
        ps_cmd = "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'server\\.py|tray_app\\.py' } | Select-Object -ExpandProperty ProcessId"
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                creationflags=_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return pids
        pids.update((int(t) for t in (out.stdout or "").split() if t.isdigit()))
    else:
        try:
            out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return pids
        for line in (out.stdout or "").splitlines():
            head, _, rest = line.strip().partition(" ")
            if not head.isdigit() or "python" not in rest:
                continue
            if "server.py" in rest or "tray_app.py" in rest:
                pids.add(int(head))
    pids.discard(os.getpid())
    return pids


def collect_targets():
    return sorted(_port_pids() | _cmdline_pids())


def _live_server_pid():
    if not _port_open():
        return None
    pids = _port_pids()
    return next(iter(pids)) if pids else None


def dedupe():
    keep = _live_server_pid()
    protected = related_pids(keep) if keep else set()
    targets = collect_targets()
    killed = []
    for pid in targets:
        if pid in protected:
            continue
        terminate_pid_tree(pid)
        killed.append(pid)
    if killed:
        kept = f" (kept live server pid {keep})" if keep else ""
        print(f"[stop_baklog] deduped stray pids: {', '.join(map(str, killed))}{kept}")
    recorded = None
    try:
        if PID_FILE.is_file():
            txt = PID_FILE.read_text(encoding="utf-8").strip()
            recorded = int(txt) if txt.isdigit() else None
    except OSError:
        recorded = None
    if recorded != keep and _clear_pid_file():
        print(f"[stop_baklog] removed stale pid file {PID_FILE}")
    return 0


def _clear_pid_file():
    try:
        if PID_FILE.is_file():
            PID_FILE.unlink()
            return True
    except OSError:
        pass
    return False


def main():
    parser = argparse.ArgumentParser(description="Stop stray BAKLOG dev server / tray processes.")
    parser.add_argument("--dry-run", action="store_true", help="List what would be stopped without killing anything.")
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Keep the live server on the port; kill only extra strays + stale pid file.",
    )
    args = parser.parse_args()
    if args.dedupe:
        return dedupe()
    if args.dry_run:
        targets = collect_targets()
        state = "open" if _port_open() else "closed"
        print(f"[stop_baklog] dry run - dev port {HOST}:{PORT} is {state}")
        if targets:
            print(f"[stop_baklog] would stop pids: {', '.join(map(str, targets))}")
        else:
            print("[stop_baklog] no stray server/tray processes found")
        if PID_FILE.is_file():
            print(f"[stop_baklog] would remove pid file {PID_FILE}")
        return 0
    graceful = _request_graceful_shutdown()
    if graceful:
        print(f"[stop_baklog] dev server on {HOST}:{PORT} shut down gracefully")
    killed = []
    for pid in collect_targets():
        terminate_pid_tree(pid)
        killed.append(pid)
    if killed:
        print(f"[stop_baklog] force-stopped pids: {', '.join(map(str, killed))}")
    elif not graceful:
        print("[stop_baklog] nothing to stop - no dev server or tray process found")
    if _clear_pid_file():
        print(f"[stop_baklog] removed stale pid file {PID_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
