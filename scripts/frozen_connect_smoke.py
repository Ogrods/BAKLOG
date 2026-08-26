"""
Frozen-build connect-flow smoke test.

Verifies that the frozen server starts and responds to connect-related API
endpoints without crashing. Run as a post-build gate after
packaging/build_windows.ps1.

Usage:
    python scripts/frozen_connect_smoke.py --exe release/BAKLOG/BAKLOG

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
import sys
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from scripts.frozen_smoke_server import (  # noqa: E402
    CONNECT_SMOKE_PORT,
    FrozenSmokeServer,
)


def _hit_endpoint(base_url: str, path: str) -> dict:
    """GET an endpoint and return parsed JSON."""
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def _hit_endpoint_allow_auth_gate(base_url: str, path: str, *, auth_required: bool) -> dict:
    """GET path; when auth is on, a 401 proves the gate (no crash)."""
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8")
        payload = json.loads(data)
        if auth_required:
            raise AssertionError(
                f"{path} returned {getattr(resp, 'status', 200)} while authRequired; "
                "expected 401 without a bearer"
            )
        return payload if isinstance(payload, dict) else {"ok": True}
    except urllib.error.HTTPError as exc:
        if auth_required and exc.code == 401:
            return {"ok": True, "auth_gated": True, "status": 401}
        raise


def run_smoke(exe: Path, *, port: int = CONNECT_SMOKE_PORT) -> dict:
    """Run the connect-flow smoke test and return a report."""
    report: dict = {
        "ok": False,
        "exe": str(exe),
        "port": port,
        "steps": [],
        "error": None,
    }

    if not exe.is_file():
        report["error"] = f"exe not found: {exe}"
        return report

    env = {
        **os.environ,
        "BAKLOG_NO_BROWSER": "1",
        "BAKLOG_PROFILE": "smoke",
        "BAKLOG_IDLE_SHUTDOWN_MINUTES": "0",
    }

    print(f"Starting server: {exe} (port {port})", file=sys.stderr)
    with FrozenSmokeServer(exe, env=env, port=port) as server:
        # Step 1: Wait for server
        if not server.ok:
            report["error"] = server.error
            return report
        report["steps"].append({"step": "wait_for_server", "ok": True})
        base_url = server.base

        # Step 2: /api/config
        try:
            config = _hit_endpoint(base_url, "/api/config")
            assert isinstance(config, dict), "config is not a dict"
            assert config.get("frozen") is True, "config.frozen is not True"
            auth_required = bool(config.get("authRequired"))
            report["steps"].append(
                {"step": "api_config", "ok": True, "authRequired": auth_required}
            )
        except Exception as exc:
            report["steps"].append({"step": "api_config", "ok": False, "error": str(exc)})
            report["error"] = f"api/config failed: {exc}"
            return report

        # Step 3: /api/auth/status (connect endpoints)
        try:
            status = _hit_endpoint_allow_auth_gate(
                base_url, "/api/auth/status", auth_required=auth_required
            )
            assert isinstance(status, dict), "auth status not a dict"
            report["steps"].append({"step": "api_auth_status", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "api_auth_status", "ok": False, "error": str(exc)})
            report["error"] = f"api/auth/status failed: {exc}"
            return report

        # Step 4: /api/fetchers (used by connections view)
        try:
            fetchers = _hit_endpoint_allow_auth_gate(
                base_url, "/api/fetchers", auth_required=auth_required
            )
            assert isinstance(fetchers, dict), "fetchers not a dict"
            report["steps"].append({"step": "api_fetchers", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "api_fetchers", "ok": False, "error": str(exc)})
            report["error"] = f"api/fetchers failed: {exc}"
            return report

        # Step 5: Verify server is still alive after all the hits
        try:
            alive = _hit_endpoint(base_url, "/api/config")
            assert alive.get("frozen") is True, "server not alive after connect endpoint hits"
            report["steps"].append({"step": "post_connect_alive", "ok": True})
        except Exception as exc:
            report["steps"].append({"step": "post_connect_alive", "ok": False, "error": str(exc)})
            report["error"] = f"server crashed after connect endpoint hits: {exc}"
            return report

        report["ok"] = True

    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Frozen-build connect-flow smoke test"
    )
    ap.add_argument(
        "--exe", type=Path, required=True,
        help="Path to frozen BAKLOG server binary",
    )
    ap.add_argument(
        "--json-out", type=Path, default=None,
        help="Write JSON report to file",
    )
    ap.add_argument(
        "--port", type=int, default=CONNECT_SMOKE_PORT,
        help=f"Port for the smoke server (default {CONNECT_SMOKE_PORT})",
    )
    args = ap.parse_args()

    report = run_smoke(args.exe, port=args.port)
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
