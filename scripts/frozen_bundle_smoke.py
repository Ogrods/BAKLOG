#!/usr/bin/env python3
"""Post-build smoke for a frozen BAKLOG onedir bundle (CI + local release).

Checks artifact layout, bundled auth .env, server boot (/api/config), data-dir
migration, and fetcher --help dispatch for every manifest key.

Usage (from repo root, after packaging/build_windows.ps1):
  .\\.venv\\Scripts\\python.exe scripts\\frozen_bundle_smoke.py \\
    --bundle-dir release/BAKLOG
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _read_expected_version() -> str:
    text = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not m:
        raise RuntimeError("could not read version from pyproject.toml")
    return m.group(1)


def _wait_for_server(base: str, proc: subprocess.Popen, *, timeout_sec: float = 30.0) -> tuple[bool, str | None]:
    from scripts.smoke_port_guard import wait_for_owned_server

    return wait_for_owned_server(proc, base, timeout_sec=timeout_sec)


def _manifest_fetcher_count(bundle_dir: Path) -> int:
    for rel in (
        Path("_internal") / "fetchers" / "manifest.json",
        Path("fetchers") / "manifest.json",
    ):
        path = bundle_dir / rel
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return len(data.get("fetchers") or [])
    return 0


def _env_has_auth_keys(env_path: Path) -> tuple[bool, list[str]]:
    required = ("BAKLOG_SUPABASE_URL", "BAKLOG_SUPABASE_ANON_KEY")
    found: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val:
                found[key] = val
    missing = [k for k in required if not found.get(k)]
    return not missing, missing


def run_smoke(bundle_dir: Path, *, expected_version: str | None = None) -> dict:
    bundle_dir = bundle_dir.resolve()
    version = expected_version or _read_expected_version()
    report: dict = {"ok": False, "bundle_dir": str(bundle_dir), "checks": {}}

    server_exe = bundle_dir / "BAKLOG.exe"
    tray_exe = bundle_dir / "BAKLOG Tray.exe"
    fallback = bundle_dir / "_internal" / "curated" / "free_claims.fallback.json"
    env_path = bundle_dir / ".env"

    static_ok = server_exe.is_file() and tray_exe.is_file() and fallback.is_file()
    fetcher_count = _manifest_fetcher_count(bundle_dir)
    env_ok, env_missing = _env_has_auth_keys(env_path)
    report["checks"]["static"] = {
        "server_exe": server_exe.is_file(),
        "tray_exe": tray_exe.is_file(),
        "curated_fallback": fallback.is_file(),
        "fetcher_manifest_count": fetcher_count,
        "bundled_env": env_ok,
    }
    if not static_ok:
        report["error"] = "missing required bundle files"
        return report
    if fetcher_count < 1:
        report["error"] = "fetchers/manifest.json missing or empty in bundle"
        return report
    if not env_ok:
        report["error"] = f"bundled .env missing keys: {', '.join(env_missing)}"
        return report

    from scripts.frozen_data_dir_migration_smoke import run_smoke as migrate_smoke
    from scripts.smoke_port_guard import port_collision_message, port_listener_pid

    migrate = migrate_smoke(bundle_dir)
    report["checks"]["migration"] = migrate
    if not migrate.get("ok"):
        report["error"] = "frozen_data_dir_migration_smoke failed"
        return report

    proc: subprocess.Popen | None = None
    config: dict | None = None
    holder = port_listener_pid()
    if holder is not None:
        report["error"] = port_collision_message(holder)
        report["port_collision_before_start"] = holder
        return report
    try:
        with tempfile.TemporaryDirectory(prefix="baklog-bundle-smoke-") as td:
            localappdata = Path(td)
            env = {
                **os.environ,
                "LOCALAPPDATA": str(localappdata),
                "BAKLOG_NO_BROWSER": "1",
            }
            env.pop("BAKLOG_DATA_DIR", None)
            env.pop("BAKLOG_PORTABLE", None)
            proc = subprocess.Popen(
                [str(server_exe)],
                cwd=str(bundle_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            ok, wait_err = _wait_for_server("http://127.0.0.1:8765", proc)
            if not ok:
                err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
                report["error"] = wait_err or f"server did not respond; stderr tail: {err[-400:]}"
                return report
            with urllib.request.urlopen("http://127.0.0.1:8765/api/config", timeout=5) as resp:
                config = json.loads(resp.read().decode("utf-8"))
    finally:
        if proc is not None and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(proc.pid), "/T"],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.terminate()

    if not isinstance(config, dict):
        report["error"] = "invalid /api/config response"
        return report

    cfg_version = str(config.get("version") or "")
    cfg_frozen = bool(config.get("frozen"))
    report["checks"]["config"] = {
        "version": cfg_version,
        "frozen": cfg_frozen,
        "auth_required": config.get("authRequired"),
        "has_capabilities": isinstance(config.get("capabilities"), dict),
        "has_pro_settings": isinstance(config.get("proSettings"), dict),
    }
    if not isinstance(config.get("capabilities"), dict):
        report["error"] = "missing capabilities in /api/config"
        return report
    if not isinstance(config.get("proSettings"), dict):
        report["error"] = "missing proSettings in /api/config"
        return report
    if cfg_version != version:
        report["error"] = f"version mismatch: expected {version!r}, got {cfg_version!r}"
        return report
    if not cfg_frozen:
        report["error"] = "expected frozen=true in /api/config"
        return report

    dispatch = subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "frozen_fetcher_smoke.py"),
            "--exe",
            str(server_exe),
            "--data-dir",
            str(_REPO),
            "--dispatch-only",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(_REPO),
    )
    report["checks"]["fetcher_dispatch_exit"] = dispatch.returncode
    if dispatch.returncode != 0:
        tail = "\n".join((dispatch.stdout or "").splitlines()[-12:] + (dispatch.stderr or "").splitlines()[-12:])
        report["error"] = f"fetcher dispatch smoke failed (exit {dispatch.returncode})\n{tail}"
        return report

    report["ok"] = True
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Frozen bundle post-build smoke")
    ap.add_argument(
        "--bundle-dir",
        type=Path,
        default=_REPO / "release" / "BAKLOG",
        help="PyInstaller onedir output (contains BAKLOG.exe)",
    )
    ap.add_argument("--expected-version", default=None, help="Override pyproject version check")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    report = run_smoke(args.bundle_dir, expected_version=args.expected_version)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
