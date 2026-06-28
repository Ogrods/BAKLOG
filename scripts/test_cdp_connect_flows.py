#!/usr/bin/env python3
"""CDP Connect flow test harness (GOG web, Battle.net, Nintendo, Humble, EA).

Automates preflight, profile setup, auth-status checks, and fetcher runs.
Browser sign-in still requires manual completion in the headed Chrome window.

Usage:
  python scripts/test_cdp_connect_flows.py preflight
  python scripts/test_cdp_connect_flows.py status
  python scripts/test_cdp_connect_flows.py fetch [--provider gog]
  python scripts/test_cdp_connect_flows.py all
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8765"
PROFILE_LABEL = "conn-test"
RESULTS_PATH = ROOT / "docs" / "cdp-connect-test-results.json"

CDP_PROVIDERS: dict[str, dict[str, object]] = {
    "gog": {
        "label": "GOG (web)",
        "fetchers": ["gog", "wishlistGog"],
        "games_json": ["games_gog.json", "games_wishlist_gog.json"],
        "login_hint": "Land on gog.com library/account before the window closes.",
    },
    "battlenet": {
        "label": "Battle.net",
        "fetchers": ["battlenet"],
        "games_json": ["games_battlenet.json"],
        "login_hint": "Open account.battle.net/games so the session is fully active.",
        "test_reconnect": True,
    },
    "nintendo": {
        "label": "Nintendo",
        "fetchers": ["nintendo"],
        "games_json": ["games_nintendo.json"],
        "login_hint": "Let ec.nintendo.com/my/transactions/ finish loading.",
    },
    "humble": {
        "label": "Humble Bundle",
        "fetchers": ["humble", "wishlistHumble"],
        "games_json": ["games_humble.json", "games_wishlist_humble.json"],
        "login_hint": "Complete CAPTCHA; library page opens after sign-in.",
    },
    "ea": {
        "label": "EA App",
        "fetchers": ["ea"],
        "games_json": ["games_ea.json"],
        "login_hint": "After sign-in, EA deals page confirms the session.",
    },
}


@dataclass
class ProviderResult:
    provider: str
    label: str
    auth_status: str = "unknown"
    connect: str = "not_run"
    fetchers: dict[str, dict[str, object]] = field(default_factory=dict)
    games_row_counts: dict[str, int | None] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass
class TestRun:
    started_at: str
    profile_id: str | None = None
    profile_label: str = PROFILE_LABEL
    preflight: dict[str, object] = field(default_factory=dict)
    providers: list[ProviderResult] = field(default_factory=list)
    finished_at: str | None = None


def _headers(*, local: bool = True) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Origin": BASE}
    if local:
        h["X-BAKLOG-Local"] = "1"
    return h


def api(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    strict_local: bool = False,
    timeout: float = 30.0,
) -> tuple[int, dict | str]:
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        method=method,
        headers=_headers(local=True),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def ping_server() -> bool:
    try:
        code, _ = api("GET", "/api/runs")
        return code == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def chrome_available() -> bool:
    import os

    if os.environ.get("BAKLOG_CHROME_PATH"):
        return Path(os.environ["BAKLOG_CHROME_PATH"]).is_file()
    for name in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if Path(name).is_file():
            return True
    return bool(shutil.which("chrome") or shutil.which("google-chrome") or shutil.which("chromium"))


def profile_games_dir(profile_id: str) -> Path:
    idx = ROOT / "profiles" / "index.json"
    if idx.is_file():
        return ROOT / "profiles" / profile_id
    return ROOT


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
        for key in ("games", "items", "library"):
            if isinstance(data.get(key), list):
                return len(data[key])
        return len(data)
    return None


def wait_idle(timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, snap = api("GET", "/api/runs")
        if code != 200 or not isinstance(snap, dict):
            time.sleep(0.25)
            continue
        if not snap.get("active") and not snap.get("queue"):
            return True
        time.sleep(0.25)
    return False


def wait_run_done(run_id: str, timeout: float = 600.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code, snap = api("GET", "/api/runs")
        if code == 200 and isinstance(snap, dict):
            for row in snap.get("history") or []:
                if row.get("id") == run_id and row.get("status") in ("done", "failed", "cancelled"):
                    return row
        time.sleep(0.5)
    return None


def auth_status_map() -> dict[str, dict]:
    code, body = api("GET", "/api/auth/status")
    if code != 200 or not isinstance(body, dict):
        return {}
    out: dict[str, dict] = {}
    for p in body.get("providers") or []:
        if isinstance(p, dict) and p.get("key"):
            out[str(p["key"])] = p
    return out


def ensure_conn_test_profile() -> tuple[str | None, str]:
    code, body = api("GET", "/api/profiles")
    if code != 200 or not isinstance(body, dict):
        return None, f"GET /api/profiles failed HTTP {code}: {body}"

    profiles = body.get("profiles") or []
    for p in profiles:
        if isinstance(p, dict) and str(p.get("label", "")).lower() == PROFILE_LABEL.lower():
            pid = str(p.get("id") or "")
            if pid and body.get("active") != pid:
                sw_code, sw_body = api("POST", "/api/profiles/active", {"id": pid})
                if sw_code not in (200, 204):
                    return None, f"switch profile failed HTTP {sw_code}: {sw_body}"
            return pid or None, "existing profile activated"

    cr_code, created = api("POST", "/api/profiles", {"label": PROFILE_LABEL})
    if cr_code not in (200, 201) or not isinstance(created, dict):
        return None, f"create profile failed HTTP {cr_code}: {created}"
    pid = str(created.get("id") or "")
    if not pid:
        return None, "create profile returned no id"
    sw_code, sw_body = api("POST", "/api/profiles/active", {"id": pid})
    if sw_code not in (200, 204):
        return None, f"switch new profile failed HTTP {sw_code}: {sw_body}"
    return pid, "created and activated"


def start_connect(provider: str) -> tuple[bool, str]:
    code, body = api("POST", f"/api/auth/{provider}/start", {})
    if code not in (200, 202) or not isinstance(body, dict):
        return False, f"HTTP {code}: {body}"
    sid = body.get("session_id") or body.get("id")
    return True, f"browser opened (session_id={sid}) — complete sign-in manually"


def disconnect_provider(provider: str) -> tuple[bool, str]:
    code, body = api("POST", f"/api/auth/{provider}/disconnect", {})
    if code not in (200, 204):
        return False, f"HTTP {code}: {body}"
    return True, "disconnected"


def run_fetcher(key: str) -> dict[str, object]:
    if not wait_idle(120):
        return {"ok": False, "error": "queue not idle before submit"}
    code, body = api("POST", f"/api/run/{key}", {})
    if code not in (200, 202) or not isinstance(body, dict):
        return {"ok": False, "http": code, "body": body}
    run_id = body.get("run_id")
    if not run_id:
        return {"ok": False, "http": code, "body": body, "error": "no run_id"}
    hist = wait_run_done(str(run_id))
    if not hist:
        return {"ok": False, "run_id": run_id, "error": "timeout waiting for run"}
    exit_code = hist.get("exit_code")
    return {
        "ok": exit_code == 0,
        "run_id": run_id,
        "exit_code": exit_code,
        "status": hist.get("status"),
    }


def cmd_preflight(run: TestRun) -> int:
    ok_server = ping_server()
    ok_chrome = chrome_available()
    pid, profile_msg = (None, "skipped — server down")
    if ok_server:
        pid, profile_msg = ensure_conn_test_profile()

    run.profile_id = pid
    run.preflight = {
        "server_up": ok_server,
        "chrome_available": ok_chrome,
        "profile": profile_msg,
        "url": f"{BASE}/#connections",
    }
    print(f"Server: {'up' if ok_server else 'DOWN'} at {BASE}")
    print(f"Chrome/Edge: {'found' if ok_chrome else 'NOT FOUND'}")
    print(f"Profile conn-test: {profile_msg}" + (f" (id={pid})" if pid else ""))
    if ok_server and pid:
        print(f"Open: {BASE}/#connections")
    return 0 if ok_server and ok_chrome and pid else 1


def cmd_status(run: TestRun) -> int:
    if not ping_server():
        print("Server down — run preflight after starting server.py")
        return 1
    pid, _ = ensure_conn_test_profile()
    run.profile_id = pid
    auth = auth_status_map()
    for key, spec in CDP_PROVIDERS.items():
        pr = ProviderResult(provider=key, label=str(spec["label"]))
        row = auth.get(key) or {}
        pr.auth_status = str(row.get("status") or "missing")
        pr.connect = "connected" if pr.auth_status == "connected" else "manual_required"
        if pr.auth_status != "connected":
            pr.notes.append(str(spec["login_hint"]))
        run.providers.append(pr)
        mark = "OK" if pr.auth_status == "connected" else "NEEDS CONNECT"
        print(f"[{mark}] {pr.label:16} status={pr.auth_status}")
    return 0


def wait_connected(provider: str, timeout: float = 300.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        auth = auth_status_map()
        if (auth.get(provider) or {}).get("status") == "connected":
            return True
        time.sleep(2.0)
    return False


def cmd_fetch(run: TestRun, *, provider: str | None = None, launch_connect: bool, wait_connect: float) -> int:
    if not ping_server():
        print("Server down")
        return 1
    pid, _ = ensure_conn_test_profile()
    run.profile_id = pid
    auth = auth_status_map()
    keys = [provider] if provider else list(CDP_PROVIDERS)
    if provider and provider not in CDP_PROVIDERS:
        print(f"Unknown provider {provider!r}")
        return 1

    games_root = profile_games_dir(pid or "") if pid else ROOT
    exit_code = 0

    for key in keys:
        spec = CDP_PROVIDERS[key]
        pr = ProviderResult(provider=key, label=str(spec["label"]))
        row = auth.get(key) or {}
        pr.auth_status = str(row.get("status") or "missing")

        if pr.auth_status != "connected":
            handled = False
            if launch_connect:
                ok, msg = start_connect(key)
                pr.connect = msg if ok else f"start failed: {msg}"
                if ok and wait_connect > 0:
                    print(f"Waiting up to {int(wait_connect)}s for {key} sign-in…")
                    if wait_connected(key, wait_connect):
                        pr.auth_status = "connected"
                        pr.connect = "connected_after_sign_in"
                        handled = True
                    else:
                        pr.notes.append("Sign-in timed out — complete Connect in browser and re-run fetch")
                        run.providers.append(pr)
                        print(f"[TIMEOUT] {pr.label} — sign-in not detected")
                        exit_code = 1
                        continue
                elif not ok:
                    run.providers.append(pr)
                    print(f"[FAIL] {pr.label} — could not start Connect")
                    exit_code = 1
                    continue
                else:
                    pr.notes.append("Complete browser sign-in, then re-run: fetch --provider " + key)
                    run.providers.append(pr)
                    print(f"[SKIP] {pr.label} — waiting for manual sign-in")
                    exit_code = 1
                    continue
            if not handled:
                pr.connect = "manual_required"
                pr.notes.append(str(spec["login_hint"]))
                run.providers.append(pr)
                print(f"[SKIP] {pr.label} — not connected ({pr.auth_status})")
                exit_code = 1
                continue

        pr.connect = "connected"
        for fetcher_key in spec["fetchers"]:  # type: ignore[union-attr]
            print(f"Running fetcher {fetcher_key}…")
            result = run_fetcher(str(fetcher_key))
            pr.fetchers[str(fetcher_key)] = result
            mark = "PASS" if result.get("ok") else "FAIL"
            print(f"  [{mark}] {fetcher_key} exit={result.get('exit_code')} {result.get('error', '')}")

        for gj in spec["games_json"]:  # type: ignore[union-attr]
            path = games_root / str(gj)
            pr.games_row_counts[str(gj)] = count_games(path)
            print(f"  {gj}: {pr.games_row_counts[str(gj)]} rows")

        if spec.get("test_reconnect") and pr.auth_status == "connected":
            print(f"Testing disconnect/reconnect chip for {key}…")
            ok, msg = disconnect_provider(key)
            pr.notes.append(f"disconnect: {msg}")
            auth2 = auth_status_map()
            disconnected = (auth2.get(key) or {}).get("status") != "connected"
            pr.notes.append(f"post-disconnect status={(auth2.get(key) or {}).get('status')}")
            if disconnected:
                ok2, msg2 = start_connect(key)
                pr.notes.append(f"reconnect start: {msg2 if ok2 else 'failed ' + msg2}")
            else:
                pr.notes.append("disconnect did not flip status — check UI reconnect chip manually")

        run.providers.append(pr)

    return exit_code


def save_results(run: TestRun) -> None:
    run.finished_at = datetime.now(UTC).isoformat()
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "profile_id": run.profile_id,
        "profile_label": run.profile_label,
        "preflight": run.preflight,
        "providers": [asdict(p) for p in run.providers],
    }
    RESULTS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nResults written to {RESULTS_PATH.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("preflight", "status", "fetch", "all"),
        help="preflight | status | fetch | all",
    )
    parser.add_argument("--provider", help="Single provider key for fetch")
    parser.add_argument(
        "--launch-connect",
        action="store_true",
        help="Open headed browser for disconnected providers (manual sign-in still required)",
    )
    parser.add_argument(
        "--wait-connect",
        type=float,
        default=0.0,
        metavar="SECS",
        help="After --launch-connect, poll auth status up to SECS (default 0 = do not wait)",
    )
    args = parser.parse_args()

    run = TestRun(started_at=datetime.now(UTC).isoformat())
    code = 0

    if args.command in ("preflight", "all"):
        code = max(code, cmd_preflight(run))
    if args.command in ("status", "all") and ping_server():
        code = max(code, cmd_status(run))
    if args.command in ("fetch", "all") and ping_server():
        code = max(
            code,
            cmd_fetch(
                run,
                provider=args.provider,
                launch_connect=args.launch_connect,
                wait_connect=args.wait_connect,
            ),
        )

    save_results(run)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
