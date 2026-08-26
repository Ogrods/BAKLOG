"""Single-session frozen server lifecycle shared by the frozen smoke scripts.

Each smoke script starts the frozen server at most once, on its own port, and
tears the whole process tree down on exit. Readiness is decided by polling
``/api/config`` rather than by port ownership: a PyInstaller launcher can hand
the listening socket to a process outside the spawned tree, so ownership checks
time out even when the server is healthy.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.smoke_port_guard import (  # noqa: E402
    ensure_port_free,
    port_listener_pid,
    wait_for_port_free,
)
from shared.dev_server_pids import DEFAULT_HOST  # noqa: E402
from shared.subprocess_guard import terminate_pid_tree  # noqa: E402

# One port per smoke step so a failed teardown cannot cascade into the next
# step. The product default (8765) stays on the bundle smoke.
BUNDLE_SMOKE_PORT = 8765
MIGRATION_SMOKE_PORT = 8766
CONNECT_SMOKE_PORT = 8767

DEFAULT_START_TIMEOUT_SEC = 30.0


def _spawn(exe: Path, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """Spawn the frozen server detached enough to be tree-killed on exit."""
    return subprocess.Popen(
        [str(exe)],
        cwd=str(cwd),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )


def _probe_config(base: str, *, timeout: float = 2.0) -> bool:
    """True when /api/config answers 200."""
    try:
        with urllib.request.urlopen(f"{base}/api/config", timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class FrozenSmokeServer:
    """Context manager that owns one frozen-server run for a smoke script.

    Enter clears the port, spawns the server, and waits for HTTP readiness.
    Check ``ok``/``error`` after entering; exit kills the process tree and any
    process still holding the port.
    """

    def __init__(
        self,
        exe: Path,
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        port: int = BUNDLE_SMOKE_PORT,
        host: str = DEFAULT_HOST,
        start_timeout_sec: float = DEFAULT_START_TIMEOUT_SEC,
    ) -> None:
        self.exe = Path(exe)
        self.cwd = Path(cwd) if cwd is not None else self.exe.parent
        self.port = port
        self.host = host
        self.start_timeout_sec = start_timeout_sec
        self.env = {**(env if env is not None else os.environ), "PORT": str(port)}
        self.proc: subprocess.Popen | None = None
        self.ok = False
        self.error: str | None = None

    @property
    def base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> FrozenSmokeServer:
        if not self.exe.is_file():
            self.error = f"frozen server not found: {self.exe}"
            return self
        free, free_err = ensure_port_free(host=self.host, port=self.port)
        if not free:
            self.error = free_err
            return self
        self.proc = _spawn(self.exe, self.cwd, self.env)
        self.ok, self.error = self._wait_for_http()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.proc is not None and self.proc.poll() is None:
            terminate_pid_tree(self.proc.pid)
        holder = port_listener_pid(self.host, self.port)
        if holder is not None:
            terminate_pid_tree(holder)
        wait_for_port_free(host=self.host, port=self.port, timeout_sec=5.0)

    def _wait_for_http(self) -> tuple[bool, str | None]:
        assert self.proc is not None
        deadline = time.monotonic() + self.start_timeout_sec
        while time.monotonic() < deadline:
            exit_code = self.proc.poll()
            if exit_code is not None and exit_code != 0:
                return False, f"server exited with code {exit_code}{self._stderr_suffix()}"
            if _probe_config(self.base):
                return True, None
            time.sleep(0.4)
        return False, (
            f"server did not respond on {self.base} within "
            f"{self.start_timeout_sec}s{self._stderr_suffix()}"
        )

    def _stderr_suffix(self) -> str:
        if self.proc is None or self.proc.stderr is None:
            return ""
        try:
            raw = self.proc.stderr.read() or b""
        except (OSError, ValueError):
            return ""
        text = raw.decode("utf-8", errors="replace").strip()
        return f"; stderr tail: {text[-400:]}" if text else ""

    def get_json(self, path: str, *, timeout: float = 5.0):
        import json

        with urllib.request.urlopen(f"{self.base}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
