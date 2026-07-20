"""
Frozen-build connect-flow smoke test.

Verifies that the frozen server starts and responds to connect-related API
endpoints without crashing. Run as a post-build gate after
packaging/build_windows.ps1.

Usage:
    python scripts/frozen_connect_smoke.py --exd release/BAKLOG

This test:
    1. Starts the frozen server (with BAKLOG_NO_BROWSER=1)
    2. Hits /api/config to verify server is alive
    3. Hits /api/auth/status to verify auth endpoints don't crash
    4. Verifies the server stays alive after connect endpoint hits
    5. Shuts down cleanly
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "http://127.0.0.1:8765"
SMOKE_PORT = 8765  # Must match default server port
START_TIMEOUT_SEC = 15
POLL_INTERVAL_SEC = 0.5


def _start_server(exe: Path, env: dict[str, str]) -> subprocess.Popen:
    """Start the frozen server as a subprocess."""
    print(f"Starting server: {exe}", file=sys.stderr)
    merged_env = os.environ.copy()
    merged_env.update(env)
    proc = subprocess.Popen(
        [str(exe)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
        if sys.platform == "win32"
        else 0,
    )
    return proc


def _wait_for_server(timeout: float = START_TIMEOUT_SEC) -> bool:
    """Poll /api/config until the server responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(
                f"{BASE_URL}/api/config",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(POLL_INTERVAL_SEC)
    return False


def _hit_endpoint(path: str) -> dict:
    """GET an endpoint and return parsed JSON."""
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def _shutdown_server(proc: subprocess.Popen) -> None:
    """Send graceful shutdown via API, then force-kill."""
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/shutdown",
            method="POST",
            headers={"X-BAKLOG-Local": "1"},
        )
        urllib.request.urlopen(req, timeout=5)
        proc.wait(timeout=10)
    except (urllib.error.URLError, TimeoutError, OSError):
        pass

    if proc.poll() is None:
        if sys.platform == "win32":
            proc.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _collect_stderr(proc: subprocess.Popen) -> str:
    """Read remaining stderr from the process (non-blocking best-effort)."""
    try:
        out, _ = proc.communicate(timeout=3)
        return (out or b"").decode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        proc.kill()
        out, _ = proc.communicate(timeout=3)
        return (out or b"").decode("utf-8", errors="replace")


def run_smoke(exe: Path) -> dict:
    """Run the connect-flow smoke test and return a report."""
    report: dict = {
        "ok": False,
        "exe": str(exe),
        "steps": [],
        "error": None,
    }

    if not exe.is_file():
        report["error"] = f"exe not found: {exe}"
        return report

    env = {
        "BAKLOG_NO_BROWSER": "1",
        "BAKLOG_PROFILE": "smoke",
        "BAKLOG_IDLE_SHUTDOWN_MINUTES": "0",
    }

    proc = _start_server(exe, env)

    try:
        # Step 1: Wait for server
        if not _wait_for_server():
            report["error"] = "server did not start within timeout"
            report["stderr"] = _collect_stderr(proc)
            return report
        report["steps"].append({"step": "wait_for_server", "ok": True})

        # Step 2: /api/config
        try:
            config = _hit_endpoint("/api/config")
            assert isinstance(config, dict), "config is not a dict"
            assert config.get("frozen") is True, "config.frozen is not True"
            report["steps"].append({"step": "api_config", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "api_config", "ok": False, "error": str(exc)})
            report["error"] = f"api/config failed: {exc}"
            return report

        # Step 3: /api/auth/status (connect endpoints)
        try:
            status = _hit_endpoint("/api/auth/status")
            assert isinstance(status, dict), "auth status not a dict"
            report["steps"].append({"step": "api_auth_status", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "api_auth_status", "ok": False, "error": str(exc)})
            report["error"] = f"api/auth/status failed: {exc}"
            return report

        # Step 4: /api/fetchers (used by connections view)
        try:
            fetchers = _hit_endpoint("/api/fetchers")
            assert isinstance(fetchers, dict), "fetchers not a dict"
            report["steps"].append({"step": "api_fetchers", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "api_fetchers", "ok": False, "error": str(exc)})
            report["error"] = f"api/fetchers failed: {exc}"
            return report

        # Step 5: Verify server is still alive after all the hits
        try:
            alive = _hit_endpoint("/api/config")
            assert alive.get("frozen") is True, "server not alive after connect endpoint hits"
            report["steps"].append({"step": "post_connect_alive", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "post_connect_alive", "ok": False, "error": str(exc)})
            report["error"] = f"server crashed after connect endpoint hits: {exc}"
            return report

        report["ok"] = True

    finally:
        _shutdown_server(proc)
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)

    report["stderr"] = _collect_stderr(proc)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Frozen-build connect-flow smoke test"
    )
    ap.add_argument(
        "--exe", type=Path, required=True,
        help="Path to frozen BAKLOG.exe",
    )
    ap.add_argument(
        "--json-out", type=Path, default=None,
        help="Write JSON report to file",
    )
    args = ap.parse_args()

    report = run_smoke(args.exe)
    text = json.dumps(report, indent=2)
    print(text)

    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")

    if not report["ok"]:
        print(
            f"\nFAILED: connect-flow smoke test ({report.get('error', 'unknown')})",
            file=sys.stderr,
        )
    else:
        print(f"\nAll {len(report['steps'])} connect-flow steps passed.")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
