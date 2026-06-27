"""Windows uninstall helpers: login autostart registry, keyring, and data dir."""

from __future__ import annotations

import os
import shutil
import socket
import time
import urllib.request
from pathlib import Path

from shared.startup import disable_startup

_SHUTDOWN_HOST = "127.0.0.1"
_SHUTDOWN_PORT = int(os.environ.get("PORT", "8765"))


def _request_graceful_shutdown() -> bool:
    """POST /api/shutdown when the local server is up. Best-effort."""
    try:
        with socket.create_connection((_SHUTDOWN_HOST, _SHUTDOWN_PORT), timeout=0.3):
            pass
    except OSError:
        return False
    req = urllib.request.Request(
        f"http://{_SHUTDOWN_HOST}:{_SHUTDOWN_PORT}/api/shutdown",
        method="POST",
        headers={"X-BAKLOG-Local": "1"},
        data=b"",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except OSError:
        return False
    for _ in range(30):
        time.sleep(0.1)
        try:
            with socket.create_connection((_SHUTDOWN_HOST, _SHUTDOWN_PORT), timeout=0.3):
                continue
        except OSError:
            return True
    return False


def cleanup_autostart() -> None:
    """Remove HKCU Run\\BAKLOG login autostart (safe when the app is uninstalled)."""
    disable_startup()


def wipe_user_data(data_dir: Path) -> list[str]:
    """Remove library data dir and OS keyring master key. Returns status notes."""
    from auth.secrets import delete_keyring_master_key

    notes: list[str] = []
    _request_graceful_shutdown()
    cleanup_autostart()
    if delete_keyring_master_key():
        notes.append("Removed OS keyring master key")
    if data_dir.is_dir():
        shutil.rmtree(data_dir)
        notes.append(f"Removed {data_dir}")
    return notes
