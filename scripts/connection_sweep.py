#!/usr/bin/env python3
"""Holistic connection + fetcher health sweep for the active profile.

Reads auth status from auth.manager (no API bearer needed), optionally runs
store/wishlist fetchers, and logs NDJSON to debug-21853a.log for debug sessions.

Usage:
  python scripts/connection_sweep.py status
  python scripts/connection_sweep.py fetch [--include-enrich] [--fetcher KEY]
  python scripts/connection_sweep.py all
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "debug-21853a.log"

# Mirror js/fetcher-health.js FETCHER_PROVIDER_GROUP
FETCHER_PROVIDER_GROUP: dict[str, tuple[str, ...]] = {
    "amazon": ("amazon_web", "amazon"),
    "gog": ("gog", "gog_galaxy"),
    "itch": ("itch", "itch_local"),
}

STORE_GROUPS = ("library", "wishlist")
ENRICH_GROUP = "enrich"


def _dbg(hyp: str, location: str, message: str, **data) -> None:
    # region agent log (session 21853a)
    try:
        rec = {
            "sessionId": "21853a",
            "hypothesisId": hyp,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")
    except Exception:
        pass
    # endregion


def _status_by_key() -> dict[str, dict]:
    from auth.manager import get_status

    return {row["key"]: row for row in get_status()}


def _active_profile() -> tuple[str, str]:
    from shared.profile_paths import get_active_profile_id, profile_label

    pid = get_active_profile_id()
    try:
        label = profile_label(pid)
    except Exception:
        label = pid
    return pid, label


def fetcher_providers(key: str) -> list[str]:
    from fetchers.registry import AUTH_PROVIDER_BY_KEY

    group = FETCHER_PROVIDER_GROUP.get(key)
    if group:
        return list(group)
    single = AUTH_PROVIDER_BY_KEY.get(key)
    return [single] if single else []


def credentials_satisfied(key: str, status_map: dict[str, dict]) -> bool:
    providers = fetcher_providers(key)
    if not providers:
        return True  # enrich fetchers without auth mapping
    return any(status_map.get(p, {}).get("status") == "connected" for p in providers)


def count_games(path: Path) -> int | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for k in ("games", "items", "library"):
            if isinstance(data.get(k), list):
                return len(data[k])
        return len(data)
    return None


def output_json_for(key: str) -> Path | None:
    from fetchers.registry import LIBRARY_JSON_BY_KEY, WISHLIST_JSON_BY_KEY
    from shared.profile_paths import catalog_path

    name = LIBRARY_JSON_BY_KEY.get(key) or WISHLIST_JSON_BY_KEY.get(key)
    if not name:
        return None
    return catalog_path(name)


def run_fetcher(key: str, entry: dict, profile_id: str, timeout_s: float) -> dict:
    from auth.manager import subprocess_env_for_profile
    from shared.install_paths import bundle_root
    from shared.subprocess_guard import popen_fetcher

    script = entry.get("script")
    if not script:
        return {"ok": False, "error": "no script in manifest"}
    script_path = bundle_root() / str(script)
    if not script_path.is_file():
        return {"ok": False, "error": f"missing script {script}"}

    args = list(entry.get("args") or [])

    cmd = [sys.executable, str(script_path), *args]
    env = subprocess_env_for_profile(profile_id)
    t0 = time.monotonic()
    try:
        proc = popen_fetcher(
            cmd,
            cwd=str(bundle_root()),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            out, _ = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate(timeout=10)
            return {
                "ok": False,
                "exit_code": -9,
                "elapsed_s": round(time.monotonic() - t0, 1),
                "error": f"timeout after {timeout_s}s",
                "tail": (out or "")[-500:],
            }
        exit_code = proc.returncode
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "tail": (out or "")[-500:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc), "elapsed_s": round(time.monotonic() - t0, 1)}


def cmd_status() -> int:
    pid, label = _active_profile()
    status_map = _status_by_key()
    connected = sum(1 for r in status_map.values() if r.get("status") == "connected")
    expired = sum(1 for r in status_map.values() if r.get("status") == "expired")
    unverified = sum(1 for r in status_map.values() if r.get("status") == "unverified")

    _dbg(
        "H4",
        "connection_sweep.py:status",
        "provider status summary",
        profile_id=pid,
        profile_label=label,
        connected=connected,
        expired=expired,
        unverified=unverified,
        total=len(status_map),
    )

    print(f"Profile: {label} ({pid})")
    print(f"{'STATUS':12} {'KEY':22} LABEL")
    print("-" * 60)
    for key in sorted(status_map):
        row = status_map[key]
        st = row.get("status", "?")
        mark = {"connected": "OK", "expired": "EXPIRED", "unverified": "UNVERIFIED"}.get(st, st.upper())
        err = row.get("last_error")
        suffix = f"  — {err[:60]}" if err and st != "connected" else ""
        print(f"[{mark:10}] {key:22} {row.get('label', '')}{suffix}")
        _dbg(
            "H4",
            "connection_sweep.py:status_row",
            "provider row",
            key=key,
            status=st,
            last_error=err,
            fetcher_keys=row.get("fetcher_keys"),
        )

    print(f"\n{connected} connected, {expired} expired, {unverified} unverified")
    return 0 if expired == 0 else 1


def cmd_fetch(*, include_enrich: bool, fetcher: str | None, timeout_s: float) -> int:
    from fetchers.registry import ENRICH_FETCHER_KEYS, entries_by_key

    pid, label = _active_profile()
    status_map = _status_by_key()
    manifest = entries_by_key()
    keys = [fetcher] if fetcher else sorted(manifest)
    if fetcher and fetcher not in manifest:
        print(f"Unknown fetcher {fetcher!r}")
        return 1

    print(f"Profile: {label} ({pid})")
    exit_code = 0
    results: list[dict] = []

    for key in keys:
        entry = manifest[key]
        group = entry.get("group", "")
        if group == ENRICH_GROUP and not include_enrich:
            continue
        if group not in STORE_GROUPS and group != ENRICH_GROUP and group != "prices":
            continue
        if group == ENRICH_GROUP and key in ENRICH_FETCHER_KEYS and not include_enrich:
            continue

        if not credentials_satisfied(key, status_map):
            providers = fetcher_providers(key)
            prov_status = {p: status_map.get(p, {}).get("status") for p in providers}
            print(f"[SKIP] {key:18} providers not connected: {prov_status}")
            _dbg("H3", "connection_sweep.py:fetch_skip", "credentials not satisfied", key=key, providers=prov_status)
            continue

        print(f"Running {key}…", flush=True)
        result = run_fetcher(key, entry, pid, timeout_s)
        out_path = output_json_for(key)
        rows = count_games(out_path) if out_path else None
        result["rows"] = rows
        result["output"] = str(out_path.name) if out_path else None
        results.append({"key": key, **result})

        mark = "PASS" if result.get("ok") else "FAIL"
        print(
            f"  [{mark}] exit={result.get('exit_code')} "
            f"rows={rows} elapsed={result.get('elapsed_s')}s"
        )
        if not result.get("ok"):
            exit_code = 1
            tail = result.get("tail") or result.get("error") or ""
            if tail:
                print(f"  tail: {tail[-200:]}")

        hyp = "H1"
        if key.startswith("wishlist"):
            hyp = "H2"
        if rows == 0 and result.get("ok"):
            hyp = "H5"
        _dbg(
            hyp,
            "connection_sweep.py:fetch_result",
            "fetcher finished",
            key=key,
            providers=fetcher_providers(key),
            **{k: v for k, v in result.items() if k != "tail"},
        )

    passed = sum(1 for r in results if r.get("ok"))
    failed = len(results) - passed
    print(f"\nSweep: {passed} passed, {failed} failed, {len(keys) - len(results)} skipped")
    _dbg(
        "H1",
        "connection_sweep.py:fetch_summary",
        "sweep complete",
        passed=passed,
        failed=failed,
        results=[{k: v for k, v in r.items() if k != "tail"} for r in results],
    )
    return exit_code


def main() -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "fetch", "all"))
    parser.add_argument("--include-enrich", action="store_true", help="Also run HLTB/reviews/covers/tags")
    parser.add_argument("--fetcher", help="Single fetcher key")
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-fetcher timeout seconds")
    args = parser.parse_args()

    _dbg("H0", "connection_sweep.py:main", "sweep started", command=args.command, runId="sweep")

    code = 0
    if args.command in ("status", "all"):
        code = max(code, cmd_status())
    if args.command in ("fetch", "all"):
        code = max(
            code,
            cmd_fetch(
                include_enrich=args.include_enrich,
                fetcher=args.fetcher,
                timeout_s=args.timeout,
            ),
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
