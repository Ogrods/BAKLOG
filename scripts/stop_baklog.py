#!/usr/bin/env python3
"""Stop every stray BAKLOG dev server / tray process.

Across a long dev session, ``python server.py`` (a blocking ``serve_forever()``
loop) and ``tray_app.py`` can pile up across terminals because they only stop on
Ctrl+C / SIGTERM / ``POST /api/shutdown``. This helper cleans the slate:

  1. Graceful first: if the dev port is up, ``POST /api/shutdown`` and wait for
     the port to close (mirrors tray_app.py's graceful quit).
  2. Force fallback: force-kill any python process still holding the dev port or
     running ``server.py`` / ``tray_app.py``.
  3. Remove the stale ``.baklog_server.pid`` file.

Usage:
  .\\.venv\\Scripts\\python.exe scripts/stop_baklog.py            # graceful + force cleanup
  .\\.venv\\Scripts\\python.exe scripts/stop_baklog.py --dry-run  # list, don't kill
  .\\.venv\\Scripts\\python.exe scripts/stop_baklog.py --dedupe   # keep the live server, kill extras
"""
from __future__ import annotations

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

from shared.dev_server_pids import (  # noqa: E402 - sys.path bootstrap above
    DEFAULT_HOST,
    DEFAULT_PORT,
    pid_listening_on_port,
)
from shared.install_paths import data_root  # noqa: E402
from shared.subprocess_guard import related_pids, terminate_pid_tree  # noqa: E402

HOST = DEFAULT_HOST
PORT = int(os.environ.get("PORT", str(DEFAULT_PORT)))
PID_FILE = data_root() / ".baklog_server.pid"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.3):
            return True
    except OSError:
        return False


def _request_graceful_shutdown() -> bool:
    """POST /api/shutdown and return True once the port closes."""
    if not _port_open():
        return False
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/api/shutdown",
        method="POST",
        headers={"X-BAKLOG-Local": "1"},
        data=b"",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:  # noqa: BLE001 - any failure falls through to force-kill
        return False
    for _ in range(30):  # up to ~3s for serve_forever to unwind + socket close
        time.sleep(0.1)
        if not _port_open():
            return True
    return False


def _port_pids() -> set[int]:
    """PID(s) currently holding the dev-server port."""
    pids: set[int] = set()
    if sys.platform == "win32":
        pid = pid_listening_on_port(HOST, PORT)
        if pid:
            pids.add(pid)
    else:
        try:
            out = subprocess.run(
                ["lsof", "-ti", f"tcp:{PORT}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return pids
        pids.update(int(t) for t in (out.stdout or "").split() if t.isdigit())
    pids.discard(os.getpid())
    return pids


def _cmdline_pids() -> set[int]:
    """PIDs of python processes whose command line runs server.py / tray_app.py."""
    pids: set[int] = set()
    if sys.platform == "win32":
        ps_cmd = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -like 'python*' -and "
            "$_.CommandLine -match 'server\\.py|tray_app\\.py' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
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
        pids.update(int(t) for t in (out.stdout or "").split() if t.isdigit())
    else:
        try:
            out = subprocess.run(
                ["ps", "-eo", "pid=,args="],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
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


def collect_targets() -> list[int]:
    """All stray pids worth stopping (port holder + command-line matches)."""
    return sorted(_port_pids() | _cmdline_pids())


def _live_server_pid() -> int | None:
    """The single process currently LISTENING on the dev port (the good server)."""
    if not _port_open():
        return None
    pids = _port_pids()
    return next(iter(pids)) if pids else None


def dedupe() -> int:
    """Keep the one server listening on the port; force-stop every other stray
    server/tray process and clear the pid file unless it points at the keeper.

    Used by the Cursor session-end hook so abandoned agent terminals don't pile
    up, without ever killing the server a session is actively using."""
    keep = _live_server_pid()
    # Protect the keeper's whole launch tree: on Windows a venv python.exe
    # launcher spawns the real python3.13.exe child that binds the port, so a
    # tree-kill (taskkill /T) of the launcher would cascade into the listening
    # child. related_pids(keep) covers that parent launcher + any children.
    protected = related_pids(keep) if keep else set()
    targets = collect_targets()
    killed: list[int] = []
    for pid in targets:
        if pid in protected:
            continue
        terminate_pid_tree(pid)
        killed.append(pid)
    if killed:
        kept = f" (kept live server pid {keep})" if keep else ""
        print(f"[stop_baklog] deduped stray pids: {', '.join(map(str, killed))}{kept}")
    # Only clear the pid file when it does NOT record the server we kept.
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


def _clear_pid_file() -> bool:
    try:
        if PID_FILE.is_file():
            PID_FILE.unlink()
            return True
    except OSError:
        pass
    return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stop stray BAKLOG dev server / tray processes."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be stopped without killing anything.",
    )
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

    killed: list[int] = []
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
