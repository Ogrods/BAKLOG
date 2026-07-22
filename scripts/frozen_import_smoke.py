"""
Frozen bundle import-chain smoke test.

Verifies that critical try/except imports and lazy-loaded modules are
actually bundled by PyInstaller.  Run as a subprocess calling the frozen
BAKLOG.exe with -c "import X; print('ok')" for each module.

Usage:
    python scripts/frozen_import_smoke.py --exe release/BAKLOG/BAKLOG.exe
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Modules that are imported via try/except or lazy patterns and may be
# missed by PyInstaller's auto-dependency scan.
CRITICAL_IMPORTS = [
    # Browser automation (CDP) — needed by ALL browser-based connect flows
    "websocket",
    "websocket._app",
    "websocket._core",
    "websocket._abnf",
    "websocket._exceptions",
    "websocket._handshake",
    "websocket._http",
    "websocket._logging",
    "websocket._socket",
    "websocket._ssl_compat",
    "websocket._url",
    "websocket._utils",
    # Cookie extraction — needed by Battle.net
    "browser_cookie3",
    # CDP browser module itself
    "auth.cdp_browser",
    # Client modules that depend on the above
    "clients.battlenet_client",
    "clients.amazon_web_client",
    "clients.nintendo_client",
    # Fetcher dispatch entry
    "baklog_fetcher_dispatch",
    # Shared modules (module-level imports in server.py)
    "shared.dev_server_pids",
    "shared.idle_watchdog",
    "shared.log_redact",
    "shared.server_epic_oauth",
    "shared.server_internal_routes",
    "shared.server_personal",
    "shared.server_static",
    "shared.server_stream_tickets",
    "shared.server_auth_secrets",
    "shared.platform_support",
    "shared.profile_paths",
    "shared.subprocess_guard",
    # Lazy/try/except imports
    "shared.supabase_auth",
    "shared.server_support",
    "shared.profiles",
]


def run_import_test(exe: Path, module_name: str) -> dict:
    """Run a single import test in the frozen exe subprocess."""
    code = f"import {module_name}; print('ok')"
    try:
        proc = subprocess.run(
            [str(exe), "-E", "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW)
            if sys.platform == "win32"
            else 0,
        )
    except subprocess.TimeoutExpired:
        return {"module": module_name, "ok": False, "error": "timeout"}
    except FileNotFoundError:
        return {"module": module_name, "ok": False, "error": f"exe not found: {exe}"}
    except Exception as exc:
        return {"module": module_name, "ok": False, "error": str(exc)}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if proc.returncode != 0:
        # Extract the actual error from stderr
        error_lines = [
            line
            for line in stderr.splitlines()
            if "Error" in line or "error" in line or "Traceback" in line
        ]
        error = error_lines[-1] if error_lines else stderr[-200:] if stderr else f"exit {proc.returncode}"
        return {"module": module_name, "ok": False, "error": error}
    if "ok" not in stdout:
        return {"module": module_name, "ok": False, "error": f"unexpected output: {stdout[:100]}"}
    return {"module": module_name, "ok": True, "error": None}


def run_smoke(exe: Path) -> dict:
    """Run all import tests and return a report."""
    exe = exe.resolve()
    report = {
        "ok": False,
        "exe": str(exe),
        "tests": [],
        "summary": {"total": 0, "passed": 0, "failed": 0},
    }
    if not exe.is_file():
        report["error"] = f"exe not found: {exe}"
        return report

    for mod in CRITICAL_IMPORTS:
        result = run_import_test(exe, mod)
        report["tests"].append(result)
        report["summary"]["total"] += 1
        if result["ok"]:
            report["summary"]["passed"] += 1
        else:
            report["summary"]["failed"] += 1

    report["ok"] = report["summary"]["failed"] == 0
    return report


def main():
    ap = argparse.ArgumentParser(description="Frozen bundle import-chain smoke test")
    ap.add_argument("--exe", type=Path, required=True, help="Path to frozen BAKLOG.exe")
    ap.add_argument("--json-out", type=Path, default=None, help="Write JSON report to file")
    args = ap.parse_args()

    report = run_smoke(args.exe)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")

    if report["summary"]["failed"]:
        print(f"\nFAILED: {report['summary']['failed']} import(s) missing from frozen bundle", file=sys.stderr)
        for t in report["tests"]:
            if not t["ok"]:
                print(f"  {t['module']}: {t['error']}", file=sys.stderr)
    else:
        print(f"\nAll {report['summary']['passed']} imports OK in frozen bundle.")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())