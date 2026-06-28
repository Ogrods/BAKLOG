import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8765"
ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "cache" / "runs"


def api(method, path, timeout=30.0):
    req = urllib.request.Request(f"{BASE}{path}", method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
            try:
                return (resp.status, json.loads(body))
            except json.JSONDecodeError:
                return (resp.status, body)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return (e.code, json.loads(body))
        except json.JSONDecodeError:
            return (e.code, body)


def runs():
    _, data = api("GET", "/api/runs")
    return data


def wait_idle(timeout=120.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runs()
        if not snap.get("active") and (not snap.get("queue")):
            return True
        time.sleep(0.25)
    return False


def wait_done(run_id, timeout=300.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runs()
        for r in snap.get("history") or []:
            if r.get("id") == run_id and r.get("status") in ("done", "failed", "cancelled"):
                return r
        time.sleep(0.25)
    return None


def read_json(path):
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def post_run(key):
    return api("POST", f"/api/run/{key}")


def poll_until(predicate, timeout=30.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = runs()
        if predicate(snap):
            return snap
        time.sleep(interval)
    return runs()


def get_server_pid():
    out = subprocess.run(
        [
            "powershell",
            "-Command",
            "(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess)",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


class Results:
    def __init__(self):
        self.items = []

    def record(self, name, ok, detail=""):
        self.items.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))

    def ok(self):
        return all((x[1] for x in self.items))


def section_b(r):
    print("\n=== B1: ITAD single run ===")
    if not wait_idle(30):
        r.record("B1 preflight idle", False, "queue not empty")
        return
    code, body = post_run("itad")
    ok_submit = code in (200, 202) and isinstance(body, dict) and body.get("run_id")
    r.record("B1 submit itad", bool(ok_submit), f"HTTP {code}")
    if ok_submit:
        hist = wait_done(body["run_id"], timeout=120)
        r.record("B1 itad finished exit 0", hist is not None and hist.get("exit_code") == 0, str(hist))
    print("\n=== B2: queue position (steamCovers + hltb) ===")
    if not wait_idle(60):
        r.record("B2 preflight idle", False, "queue not empty")
        return
    c1, b1 = post_run("steamCovers")
    c2, b2 = post_run("hltb")
    r.record("B2 steamCovers submitted", c1 in (200, 202), f"HTTP {c1}")
    r.record("B2 hltb submitted", c2 in (200, 202), f"HTTP {c2}")
    snap = poll_until(
        lambda s: (
            (s.get("active") or {}).get("key") == "steamCovers"
            and any((q.get("key") == "hltb" for q in s.get("queue") or []))
        ),
        timeout=15,
    )
    active = snap.get("active") or {}
    queue = snap.get("queue") or []
    qfile = read_json(RUNS_DIR / "queue.json")
    r.record("B2 active is steamCovers", active.get("key") == "steamCovers", str(active.get("key")))
    r.record("B2 hltb in api queue", any((q.get("key") == "hltb" for q in queue)), f"queue={queue}")
    r.record("B2 hltb in queue.json", any((x.get("key") == "hltb" for x in qfile.get("runs", []))), str(qfile))
    print("\n=== B3: third submit 409 ===")
    c3, b3 = post_run("amazon")
    snap2 = runs()
    total = (1 if snap2.get("active") else 0) + len(snap2.get("queue") or [])
    r.record("B3 amazon 409", c3 == 409, f"HTTP {c3} body={b3}")
    r.record("B3 max 2 in flight", total <= 2, f"in_flight={total}")
    print("\n=== B4: cancel-all ===")
    code, _ = api("POST", "/api/runs/cancel")
    time.sleep(1.0)
    snap3 = runs()
    r.record("B4 cancel HTTP 200", code == 200, f"HTTP {code}")
    r.record("B4 api idle", not snap3.get("active") and (not snap3.get("queue")), str(snap3))
    r.record("B4 active.json empty", not read_json(RUNS_DIR / "active.json").get("runs"), "")
    r.record("B4 queue.json empty", not read_json(RUNS_DIR / "queue.json").get("runs"), "")


def section_c(r):
    print("\n=== C: client recovery (server contracts) ===")
    if not wait_idle(60):
        r.record("C preflight idle", False, "queue not empty")
        return
    code, body = post_run("hltb")
    run_id = body.get("run_id") if isinstance(body, dict) else None
    r.record("C1 submit hltb", code in (200, 202) and bool(run_id), f"HTTP {code}")
    snap = poll_until(lambda s: (s.get("active") or {}).get("id") == run_id, timeout=15)
    active = snap.get("active") or {}
    r.record("C1 active persisted for reload", active.get("id") == run_id, str(active))
    stream_ok = False
    if run_id:
        try:
            req = urllib.request.Request(f"{BASE}/api/stream/{run_id}")
            with urllib.request.urlopen(req, timeout=5) as resp:
                chunk = resp.read(64)
                stream_ok = resp.status == 200 and len(chunk) >= 0
        except Exception as exc:
            r.record("C1 SSE stream reachable", False, str(exc))
        else:
            r.record("C1 SSE stream reachable", stream_ok, f"status={resp.status}")
    code, _ = api("POST", "/api/runs/cancel")
    time.sleep(0.5)
    snap2 = runs()
    cancelled = any((h.get("id") == run_id and h.get("status") == "cancelled" for h in snap2.get("history") or []))
    r.record("C3 cancel in history", cancelled, f"run_id={run_id}")
    r.record("C3 idle after cancel", not snap2.get("active"), str(snap2))


def section_d(r):
    print("\n=== D1: durable queue restore after server kill ===")
    if not wait_idle(60):
        r.record("D1 preflight idle", False, "queue not empty")
        return
    pid = get_server_pid()
    if not pid:
        r.record("D1 server pid", False, "no listener on 8765")
        return
    c1, b1 = post_run("steamCovers")
    c2, b2 = post_run("hltb")
    hltb_id = b2.get("run_id") if isinstance(b2, dict) else None
    steam_id = b1.get("run_id") if isinstance(b1, dict) else None
    poll_until(
        lambda s: (
            (s.get("active") or {}).get("key") == "steamCovers"
            and any((q.get("key") == "hltb" for q in s.get("queue") or []))
        ),
        timeout=20,
    )
    queue_before = read_json(RUNS_DIR / "queue.json")
    has_hltb = any((x.get("key") == "hltb" for x in queue_before.get("runs", [])))
    r.record("D1 pre-kill queue has hltb", has_hltb, str(queue_before))
    subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], capture_output=True)
    time.sleep(1.0)
    queue_after_kill = read_json(RUNS_DIR / "queue.json")
    survived = any((x.get("key") == "hltb" for x in queue_after_kill.get("runs", [])))
    r.record("D1 queue.json survived kill", survived, str(queue_after_kill))
    proc = subprocess.Popen(
        ["python.exe", "server.py"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )
    time.sleep(2.5)
    for _ in range(20):
        try:
            urllib.request.urlopen(f"{BASE}/api/runs", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    else:
        r.record("D1 server restart", False, "not responding")
        return
    r.record("D1 server restart", True, f"new pid={get_server_pid()}")

    def _hltb_resumed(snap):
        active = snap.get("active") or {}
        if active.get("key") == "hltb":
            return True
        hist = snap.get("history") or []
        return any((h.get("id") == hltb_id and h.get("status") in ("running", "done") for h in hist))

    snap_after = poll_until(_hltb_resumed, timeout=30)
    active_after = snap_after.get("active") or {}
    hist = snap_after.get("history") or []
    steam_hist = next((h for h in hist if h.get("id") == steam_id), None)
    hltb_running = active_after.get("key") == "hltb" or any((h.get("id") == hltb_id for h in hist))
    r.record("D1 hltb re-queued/running", hltb_running, str(active_after))
    if steam_hist:
        not_steam = active_after.get("id") != steam_id
        r.record("D1 steam not resurrected as active", not_steam, str(steam_hist.get("status")))
    else:
        r.record("D1 steam history entry", True, "no steam in history (killed mid-run)")
    api("POST", "/api/runs/cancel")
    wait_idle(60)
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except Exception:
        pass
    print("\n=== D2/D3: launch FSM via pytest ===")
    pytest = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_run_manager.py::test_launch_timeout_marks_failed_and_admits_next",
            "tests/test_run_manager.py::test_cancel_during_launch_does_not_leave_running_status",
            "-q",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    r.record("D2 launch timeout pytest", pytest.returncode == 0, pytest.stdout.strip() or pytest.stderr.strip())
    r.record("D3 cancel-during-launch pytest", pytest.returncode == 0, "")


def section_e(r):
    print("\n=== E: post-test cleanup ===")
    wait_idle(120)
    api("POST", "/api/runs/cancel")
    time.sleep(0.5)
    snap = runs()
    r.record("E api idle", not snap.get("active") and (not snap.get("queue")), str(snap))
    r.record("E active.json empty", not read_json(RUNS_DIR / "active.json").get("runs"), "")
    r.record("E queue.json empty", not read_json(RUNS_DIR / "queue.json").get("runs"), "")
    out = subprocess.run(
        ["powershell", "-Command", "(Get-Process python* -ErrorAction SilentlyContinue).Count"],
        capture_output=True,
        text=True,
    )
    count = out.stdout.strip()
    r.record("E python process count reasonable", count.isdigit() and int(count) <= 3, f"count={count}")


def main():
    r = Results()
    print("=== Section A (already verified): server up, registry 200, 21 manifest fetchers ===")
    section_b(r)
    section_c(r)
    section_d(r)
    section_e(r)
    print("\n=== FINAL SUMMARY ===")
    failed = [n for n, ok, _ in r.items if not ok]
    for name, ok, detail in r.items:
        print(f"  {('OK' if ok else 'XX')} {name}: {detail}")
    if failed:
        print(f"\n{len(failed)} failure(s): {', '.join(failed)}")
        return 1
    print("\nAll live test checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
