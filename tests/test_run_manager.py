"""Tests for RunManager queue, cancel, and persistence."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import server

# Whole module is subprocess/timing-heavy (real Popen spawns + watchdog polling).
# It dominates CI wall time, so it runs on the dedicated Ubuntu "slow" lane and is
# excluded from the Windows/macOS smoke jobs. Run locally with `-m slow`.
pytestmark = pytest.mark.slow


@pytest.fixture()
def runs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    def _runs_dir_fn(*, profile_id=None):
        return runs_dir

    monkeypatch.setattr("shared.profile_paths.runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "print('ok')"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    monkeypatch.setitem(
        server.FETCHERS,
        "demo2",
        {
            "label": "Demo2",
            "argv": [server.sys.executable, "-c", "print('two')"],
            "refreshArgs": [],
            "metaKey": "demo2",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    monkeypatch.setitem(
        server.FETCHERS,
        "demo3",
        {
            "label": "Demo3",
            "argv": [server.sys.executable, "-c", "print('three')"],
            "refreshArgs": [],
            "metaKey": "demo3",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    mgr = server.RunManager(runs_dir=runs_dir, enable_watchdog=False)
    yield mgr, runs_dir
    try:
        mgr.cancel_all()
    except Exception:
        pass
    try:
        mgr.shutdown()
    except Exception:
        pass
    mgr.join_threads(timeout=5.0)


def test_submit_rejects_duplicate_key(runs_env):
    mgr, _ = runs_env
    mgr.submit("demo")
    with pytest.raises(ValueError, match="already queued or running"):
        mgr.submit("demo")


def test_submit_rejects_active_after_removed_from_pending(runs_env) -> None:
    """cancel() drops a run from _pending while _active is still finishing."""
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "cancelling"
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    with pytest.raises(ValueError, match="already queued or running"):
        mgr.submit("demo")


def test_cancel_all_clears_active_and_queue(runs_env):
    mgr, runs_dir = runs_env
    active = server.Run("demo", runs_dir=runs_dir)
    active.status = "running"
    active.started_at = time.time()
    queued = server.Run("demo", runs_dir=runs_dir)
    with mgr._lock:
        mgr._pending.extend([active, queued])
        mgr._runs_by_id[active.id] = active
        mgr._runs_by_id[queued.id] = queued
        mgr._active = active
    summaries = mgr.cancel_all()
    assert len(summaries) == 2
    assert active.status == "cancelled"
    assert queued.status == "cancelled"
    snap = mgr.snapshot()
    assert snap["queue"] == []


def test_resync_stalled_queue_recovers_dead_worker(runs_env) -> None:
    """Queued runs in _pending with an empty worker queue must execute after resync."""
    mgr, runs_dir = runs_env
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    mgr._worker_thread = dead
    run = server.Run("demo", runs_dir=runs_dir)
    with mgr._lock:
        mgr._pending.append(run)
        mgr._runs_by_id[run.id] = run
    assert mgr._resync_stalled_queue() == 1
    mgr._ensure_worker_thread()
    deadline = time.time() + 10
    while time.time() < deadline:
        snap = mgr.snapshot()
        if not snap["active"] and not snap["queue"]:
            if any(h.get("id") == run.id for h in snap["history"]):
                break
        time.sleep(0.05)
    else:
        pytest.fail(f"resynced run did not finish: {mgr.snapshot()}")


def test_cancel_all_returns_before_async_kill(runs_env, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr, _ = runs_env

    def slow_kill(pid: int) -> None:
        time.sleep(2)

    monkeypatch.setattr(server, "_terminate_pid", slow_kill)
    mgr.submit("demo")
    try:
        mgr.submit("demo2")
    except ValueError:
        pass
    t0 = time.time()
    summaries = mgr.cancel_all()
    elapsed = time.time() - t0
    assert elapsed < 1.0
    assert summaries


def test_cancel_schedules_sync_completion_when_worker_dead(
    runs_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the worker thread is dead, cancel must not rely on it to finalize."""
    completed: list[str] = []

    def _record_complete(_mgr: server.RunManager, run: server.Run) -> None:
        completed.append(run.id)
        run.status = "cancelled"
        run.exit_code = -1
        run.ended_at = time.time()
        if not run._finished.is_set():
            run.mark_finished()
        _mgr._finalize_run(run)

    mgr, runs_dir = runs_env
    monkeypatch.setattr(server, "_kill_pids_async", lambda _pids: None)
    monkeypatch.setattr(
        mgr,
        "_complete_cancel_after_kill",
        lambda run: _record_complete(mgr, run),
    )
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    mgr._worker_thread = dead

    class _FakeProc:
        pid = 424242

        def poll(self) -> None:
            return None

        def wait(self, timeout: float | None = None) -> int:
            return 0

    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "running"
    run.started_at = time.time()
    run._proc = _FakeProc()
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    cancelled, err = mgr.cancel(run.id)
    assert err is None
    assert cancelled is not None
    assert completed == [run.id]
    assert any(h.get("id") == run.id for h in mgr.snapshot()["history"])


def test_force_reset_clears_queue(runs_env) -> None:
    mgr, _ = runs_env
    mgr.submit("demo")
    try:
        mgr.submit("demo2")
    except ValueError:
        pass
    snap = mgr.snapshot()
    assert snap["active"] or snap["queue"]
    result = mgr.force_reset()
    assert result.get("force") is True
    snap = mgr.snapshot()
    assert not snap["active"]
    assert not snap["queue"]


def test_force_finalize_stuck_cancelling(runs_env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "CANCEL_STUCK_GRACE_SEC", 0.01)
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "cancelling"
    run._cancelling_since = time.monotonic() - 10.0
    run.started_at = time.time()
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    mgr._force_finalize_stuck_cancelling()
    snap = mgr.snapshot()
    assert snap["active"] is None
    assert any(h.get("id") == run.id for h in snap["history"])


def test_force_finalize_orphaned_active_run(
    runs_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "STUCK_NO_PROC_GRACE_SEC", 0.01)
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "running"
    run._proc = None
    run._no_proc_since = time.monotonic() - 100.0
    run.started_at = time.time()
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    mgr._force_finalize_orphaned_runs()
    snap = mgr.snapshot()
    assert snap["active"] is None
    hist = next(h for h in snap["history"] if h.get("id") == run.id)
    assert hist["status"] == "failed"
    assert hist["exit_code"] == -1
    assert "no live subprocess" in (hist.get("note") or "")


def test_orphaned_reaper_spares_live_process(
    runs_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "STUCK_NO_PROC_GRACE_SEC", 0.01)

    class _LiveProc:
        pid = 4242

        @staticmethod
        def poll():
            return None

    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "running"
    run._proc = _LiveProc()
    run.started_at = time.time()
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    mgr._force_finalize_orphaned_runs()
    snap = mgr.snapshot()
    assert snap["active"] is not None
    assert snap["active"]["id"] == run.id
    assert not any(h.get("id") == run.id for h in snap["history"])


def test_orphaned_reaper_one_cycle_grace(
    runs_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server, "STUCK_NO_PROC_GRACE_SEC", 0.01)
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "running"
    run._proc = None
    run.started_at = time.time()
    with mgr._lock:
        mgr._active = run
        mgr._runs_by_id[run.id] = run
    mgr._force_finalize_orphaned_runs()
    assert run._no_proc_since is not None
    snap = mgr.snapshot()
    assert snap["active"] is not None
    time.sleep(0.02)
    mgr._force_finalize_orphaned_runs()
    snap = mgr.snapshot()
    assert snap["active"] is None
    assert any(h.get("id") == run.id for h in snap["history"])


def test_cancel_queued_run(runs_env):
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    with mgr._lock:
        mgr._pending.append(run)
        mgr._runs_by_id[run.id] = run
    cancelled, err = mgr.cancel(run.id)
    assert err is None
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    mgr._queue.put(run)
    deadline = time.time() + 5
    while time.time() < deadline:
        if any(h.get("id") == run.id for h in mgr.snapshot()["history"]):
            break
        time.sleep(0.05)
    else:
        pytest.fail("cancelled run was not finalized into history")


def test_finalize_run_is_idempotent(runs_env) -> None:
    mgr, runs_dir = runs_env
    run = mgr.submit("demo")
    run.status = "cancelled"
    run.exit_code = -1
    run.ended_at = time.time()
    run.mark_finished()
    mgr._finalize_run(run)
    hist = server._load_run_history_from(runs_dir / "history.json")
    assert sum(1 for h in hist if h.get("id") == run.id) == 1
    mgr._finalize_run(run)
    hist2 = server._load_run_history_from(runs_dir / "history.json")
    assert sum(1 for h in hist2 if h.get("id") == run.id) == 1


def test_history_persisted_on_finish(runs_env):
    mgr, runs_dir = runs_env
    run = mgr.submit("demo")
    deadline = time.time() + 10
    while time.time() < deadline:
        snap = mgr.snapshot()
        if not snap["active"] and not snap["queue"]:
            hist = snap["history"]
            if hist and hist[0]["id"] == run.id:
                break
        time.sleep(0.05)
    else:
        pytest.fail("run did not finish in time")

    history_file = runs_dir / "history.json"
    assert history_file.exists()
    saved = json.loads(history_file.read_text(encoding="utf-8"))
    assert saved[0]["key"] == "demo"
    assert saved[0]["status"] == "done"


def test_run_log_replay_from_disk(runs_env):
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.add_line("stdout", "hello")
    run.add_line("stdout", "world")
    replay = run.replay_lines()
    assert [m["text"] for m in replay] == ["hello", "world"]
    assert [m["seq"] for m in replay] == [1, 2]
    assert (runs_dir / f"{run.id}.jsonl").exists()


def test_stall_watchdog_emits_notice(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "STALL_FIRST_NOTICE_SEC", 0.2)
    monkeypatch.setattr(server, "STALL_POLL_SEC", 0.05)
    monkeypatch.setattr(server, "STALL_REPEAT_SEC", 0.5)
    mgr, _runs_dir = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "sleepy",
        {
            "label": "Sleepy",
            "argv": [server.sys.executable, "-c", "import time; time.sleep(1.5); print('done')"],
            "refreshArgs": [],
            "metaKey": "sleepy",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    run = mgr.submit("sleepy")
    saw_stall = False
    poll_deadline = time.time() + 10
    while time.time() < poll_deadline:
        replay = run.replay_lines()
        if any("no output for" in m.get("text", "") for m in replay):
            saw_stall = True
            break
        time.sleep(0.05)
    assert saw_stall, "expected stall watchdog line in run log"
    assert run._finished.wait(timeout=10)
    assert run.exit_code == 0
    drain = time.time() + 5
    while time.time() < drain:
        snap = mgr.snapshot()
        if not snap["active"] and not snap["queue"]:
            break
        time.sleep(0.05)
    time.sleep(0.2)


def test_reap_orphan_on_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    active = runs_dir / "active.json"
    active.write_text(
        json.dumps(
            {
                "runs": [
                    {
                        "id": "deadbeef",
                        "pid": 999999,
                        "key": "demo",
                        "label": "Demo",
                        "started_at": 1.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", active)
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "pass"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "requires": [],
        },
    )
    mgr = server.RunManager(runs_dir=runs_dir)
    snap = mgr.snapshot()
    assert snap["history"]
    assert snap["history"][0].get("note")
    assert json.loads(active.read_text())["runs"] == []
    mgr.shutdown()


def test_submit_queue_full_returns_error(runs_env):
    mgr, runs_dir = runs_env
    running = server.Run("demo", runs_dir=runs_dir)
    running.status = "running"
    running.started_at = time.time()
    with mgr._lock:
        mgr._pending.append(running)
        mgr._runs_by_id[running.id] = running
        mgr._active = running
    with pytest.raises(ValueError, match="queue full"):
        mgr.submit("demo2")


def test_submit_atomic_under_concurrency(runs_env):
    mgr, runs_dir = runs_env
    errors: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def worker(key: str) -> None:
        barrier.wait(timeout=5)
        try:
            mgr.submit(key)
        except ValueError as exc:
            with lock:
                errors.append(str(exc))

    # Pre-fill the single slot so concurrent submits all race for a full queue.
    running = server.Run("demo", runs_dir=runs_dir)
    running.status = "running"
    with mgr._lock:
        mgr._pending.append(running)
        mgr._runs_by_id[running.id] = running
        mgr._active = running

    t1 = threading.Thread(target=worker, args=("demo2",))
    t2 = threading.Thread(target=worker, args=("demo2",))
    t3 = threading.Thread(target=worker, args=("demo2",))
    for t in (t1, t2, t3):
        t.start()
    for t in (t1, t2, t3):
        t.join(timeout=5)
    queue_full = [e for e in errors if "queue full" in e or "already" in e]
    assert queue_full, f"expected rejections, got {errors}"
    assert len(errors) == 3


def test_launch_timeout_marks_failed_and_admits_next(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "LAUNCH_TIMEOUT_SEC", 0.1)
    mgr, _runs_dir = runs_env
    launch_started = threading.Event()

    class _LateProc:
        pid = 424242

        def poll(self):
            return None

    def blocking_popen(*args, **kwargs):
        launch_started.set()
        # LAUNCH_TIMEOUT_SEC is mocked to 0.1s above, so the timeout fires long
        # before this returns. Keep the sleep short so the abandoned launch thread
        # does not linger for a full minute after the assertion already passed.
        time.sleep(5)
        return _LateProc()

    monkeypatch.setattr(server, "popen_fetcher", blocking_popen)
    run = mgr.submit("demo")
    assert launch_started.wait(timeout=5)
    deadline = time.time() + 8
    while time.time() < deadline:
        snap = mgr.snapshot()
        hist = snap["history"]
        if hist and hist[0]["id"] == run.id and hist[0]["status"] == "failed":
            break
        time.sleep(0.05)
    else:
        pytest.fail("launch timeout did not mark run failed")
    second = mgr.submit("demo")
    assert second.id != run.id


def test_cancel_during_launch_does_not_leave_running_status(runs_env, monkeypatch: pytest.MonkeyPatch):
    mgr, _ = runs_env
    gate = threading.Event()
    real_popen = server.subprocess.Popen

    def blocking_popen(*args, **kwargs):
        gate.wait(timeout=5)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(server, "popen_fetcher", blocking_popen)
    run = mgr.submit("demo")
    deadline = time.time() + 5
    while time.time() < deadline:
        if run.status == "launching":
            break
        time.sleep(0.02)
    cancelled, err = mgr.cancel(run.id)
    assert err is None
    assert cancelled is not None
    gate.set()
    assert run._finished.wait(timeout=10)
    assert run.status in ("cancelled", "failed")
    assert run.status != "running"


def test_max_runtime_cap_kills_run(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 1.5)
    monkeypatch.setattr(server, "STALL_POLL_SEC", 0.05)
    monkeypatch.setattr(server, "SILENT_STALL_KILL_SEC", 9999)
    mgr, _ = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "trickle",
        {
            "label": "Trickle",
            "argv": [
                server.sys.executable,
                "-c",
                "import time\nwhile True:\n print('tick')\n time.sleep(0.2)",
            ],
            "refreshArgs": [],
            "metaKey": "trickle",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    run = mgr.submit("trickle")
    saw_cap = False
    deadline = time.time() + 20
    while time.time() < deadline:
        replay = run.replay_lines()
        if any("maximum runtime" in m.get("text", "") for m in replay):
            saw_cap = True
            break
        time.sleep(0.05)
    assert saw_cap, "expected max-runtime cap message in run log"
    assert run._finished.wait(timeout=15)
    assert run.status == "failed"
    assert run.exit_code == -1


def test_max_run_seconds_for_key_uses_fetcher_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 1800.0)
    monkeypatch.setitem(
        server.FETCHERS,
        "hltb",
        {**(server.FETCHERS.get("hltb") or {}), "maxRunSeconds": 7200},
    )
    assert server._max_run_seconds_for_key("hltb") == 7200.0
    assert server._max_run_seconds_for_key("steam") == 1800.0


def test_max_run_seconds_for_key_enforces_sixty_second_floor(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 1800.0)
    monkeypatch.setitem(server.FETCHERS, "fast", {"maxRunSeconds": 5.0})
    assert server._max_run_seconds_for_key("fast") == 60.0


def test_max_run_seconds_for_key_zero_means_no_cap(monkeypatch: pytest.MonkeyPatch):
    # 0 (or negative) is the "no runtime cap" sentinel -> infinity, so a long
    # HLTB enrich on a big library is never force-killed by the runtime ceiling.
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 1800.0)
    monkeypatch.setitem(server.FETCHERS, "hltb", {"maxRunSeconds": 0})
    assert server._max_run_seconds_for_key("hltb") == float("inf")


def test_manifest_registration_keeps_zero_cap_sentinel():
    # The shipped HLTB manifest entry must register as the uncapped sentinel
    # (0), not get rewritten to the 60s floor.
    assert server.FETCHERS["hltb"]["maxRunSeconds"] == 0
    assert server._max_run_seconds_for_key("hltb") == float("inf")


def test_per_fetcher_max_runtime_override(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 9999.0)
    monkeypatch.setattr(server, "STALL_POLL_SEC", 0.05)
    monkeypatch.setattr(server, "SILENT_STALL_KILL_SEC", 9999)
    real_cap = server._max_run_seconds_for_key

    def _cap_for_long_enrich(key: str) -> float:
        if key == "long_enrich":
            return 2.0
        return real_cap(key)

    monkeypatch.setattr(server, "_max_run_seconds_for_key", _cap_for_long_enrich)
    mgr, _ = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "long_enrich",
        {
            "label": "Long enrich",
            "argv": [
                server.sys.executable,
                "-c",
                "print('start'); import time; time.sleep(10)",
            ],
            "refreshArgs": [],
            "metaKey": "long_enrich",
            "group": "enrich",
            "color": "#fff",
            "requires": [],
            "maxRunSeconds": 7200.0,
        },
    )
    run = mgr.submit("long_enrich")
    saw_cap = False
    deadline = time.time() + 30
    while time.time() < deadline:
        replay = run.replay_lines()
        if any("maximum runtime (2" in m.get("text", "") for m in replay):
            saw_cap = True
            break
        time.sleep(0.05)
    assert saw_cap, "expected per-fetcher cap message in run log"
    assert run._finished.wait(timeout=30)
    assert run.status == "failed"


def test_stall_kill_after_single_stdout_line(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "STALL_FIRST_NOTICE_SEC", 0.2)
    monkeypatch.setattr(server, "STALL_POLL_SEC", 0.05)
    monkeypatch.setattr(server, "SILENT_STALL_KILL_SEC", 0.5)
    mgr, _ = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "one_line",
        {
            "label": "One line",
            "argv": [
                server.sys.executable,
                "-c",
                "print('started'); import time; time.sleep(5)",
            ],
            "refreshArgs": [],
            "metaKey": "one_line",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    run = mgr.submit("one_line")
    saw_kill = False
    deadline = time.time() + 15
    while time.time() < deadline:
        replay = run.replay_lines()
        if any("force-killing" in m.get("text", "") for m in replay):
            saw_kill = True
            break
        time.sleep(0.05)
    assert saw_kill, "expected stall kill after single stdout line"
    assert run._finished.wait(timeout=10)


def test_heartbeat_keeps_long_run_alive(runs_env, monkeypatch: pytest.MonkeyPatch):
    """Positive guard for the find_fetcher_heartbeat_loops fix: a run that keeps
    emitting stdout faster than SILENT_STALL_KILL_SEC must survive past that
    window. This is exactly what HeartbeatTimer / run_with_heartbeat / per-item
    progress lines do in the long fetcher + enrich loops, so the watchdog's
    reset-on-output behavior (last_line_at = now) is what keeps healthy long
    pulls alive. Mirrors the negative test_stall_kill_after_single_stdout_line."""
    # Stall window (0.6s) is shorter than the total run (~1.5s) but longer than
    # each inter-line gap (0.1s): the run only survives if every printed line
    # resets the stall timer.
    monkeypatch.setattr(server, "STALL_FIRST_NOTICE_SEC", 0.2)
    monkeypatch.setattr(server, "STALL_POLL_SEC", 0.05)
    monkeypatch.setattr(server, "SILENT_STALL_KILL_SEC", 0.6)
    monkeypatch.setattr(server, "MAX_RUN_SECONDS", 9999.0)
    mgr, _ = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "heartbeating",
        {
            "label": "Heartbeating",
            "argv": [
                server.sys.executable,
                "-c",
                "import time\n"
                "for i in range(15):\n"
                " print('  \u00b7 still working', i, flush=True)\n"
                " time.sleep(0.1)\n"
                "print('done', flush=True)",
            ],
            "refreshArgs": [],
            "metaKey": "heartbeating",
            "group": "enrich",
            "color": "#fff",
            "requires": [],
        },
    )
    run = mgr.submit("heartbeating")
    assert run._finished.wait(timeout=20)
    replay = run.replay_lines()
    texts = [m.get("text", "") for m in replay]
    assert not any("force-killing" in t for t in texts), (
        "heartbeating run was force-killed despite emitting periodic stdout"
    )
    assert any("still working" in t for t in texts), "expected heartbeat lines in run log"
    assert any("done" in t for t in texts), "expected the run to reach completion"
    assert run.exit_code == 0
    assert run.status == "done"


def test_durable_queue_skips_when_key_already_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    hist = runs_dir / "history.json"
    hist.write_text(
        json.dumps(
            [
                {
                    "id": "finished-1",
                    "key": "demo",
                    "status": "done",
                    "label": "Demo",
                }
            ]
        ),
        encoding="utf-8",
    )
    queue_file = runs_dir / "queue.json"
    queue_file.write_text(
        json.dumps({"runs": [{"id": "stale", "key": "demo", "refresh": False}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", hist)
    monkeypatch.setattr(server, "QUEUE_FILE", queue_file)
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "print('ok')"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    mgr = server.RunManager(runs_dir=runs_dir, enable_watchdog=False)
    snap = mgr.snapshot()
    assert not snap["active"]
    assert not snap["queue"]
    mgr.shutdown()


def test_durable_queue_restored_on_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    queue_file = runs_dir / "queue.json"
    queue_file.write_text(
        json.dumps({"runs": [{"id": "old", "key": "demo", "refresh": False}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", queue_file)
    monkeypatch.setitem(
        server.FETCHERS,
        "demo",
        {
            "label": "Demo",
            "argv": [server.sys.executable, "-c", "print('ok')"],
            "refreshArgs": [],
            "metaKey": "demo",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    mgr = server.RunManager(runs_dir=runs_dir, enable_watchdog=False)
    snap = mgr.snapshot()
    assert snap["active"] or snap["queue"]
    mgr.shutdown()


def test_has_runs_for_profile(runs_env) -> None:
    mgr, runs_dir = runs_env
    work_run = server.Run("demo", runs_dir=runs_dir, profile_id="work")
    work_run.status = "queued"
    play_run = server.Run("demo2", runs_dir=runs_dir, profile_id="play")
    play_run.status = "done"
    with mgr._lock:
        mgr._pending.append(work_run)
        mgr._pending.append(play_run)
    assert mgr.has_runs_for_profile("work") is True
    assert mgr.has_runs_for_profile("play") is False
    assert mgr.has_runs_for_profile("missing") is False


def test_has_runs_for_profile_includes_active_not_in_pending(runs_env) -> None:
    mgr, runs_dir = runs_env
    active = server.Run("demo", runs_dir=runs_dir, profile_id="work")
    active.status = "running"
    with mgr._lock:
        mgr._active = active
        mgr._runs_by_id[active.id] = active
    assert mgr.has_runs_for_profile("work") is True
    assert mgr.has_runs_for_profile("play") is False


def test_cancel_all_and_wait_finishes_queued(runs_env) -> None:
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    with mgr._lock:
        mgr._pending.append(run)
        mgr._runs_by_id[run.id] = run
    result = mgr.cancel_all_and_wait(timeout=5.0)
    assert result["stragglers"] == []
    assert len(result["cancelled"]) == 1
    assert run._finished.is_set()


def test_cancel_all_and_wait_reports_stragglers(runs_env) -> None:
    mgr, runs_dir = runs_env
    run = server.Run("demo", runs_dir=runs_dir)
    run.status = "cancelling"
    with mgr._lock:
        mgr._pending.append(run)
        mgr._runs_by_id[run.id] = run
    result = mgr.cancel_all_and_wait(timeout=0.05)
    assert result["stragglers"]
    assert result["stragglers"][0]["id"] == run.id
    assert not run._finished.is_set()


def test_cancel_all_and_wait_includes_active_not_in_pending(runs_env) -> None:
    mgr, runs_dir = runs_env
    active = server.Run("demo", runs_dir=runs_dir)
    active.status = "running"
    with mgr._lock:
        mgr._active = active
        mgr._runs_by_id[active.id] = active
    result = mgr.cancel_all_and_wait(timeout=5.0)
    assert active.id in {s["id"] for s in result["cancelled"]}
    assert result["stragglers"] == []
    assert active._finished.is_set()


def test_shutdown_cancels_in_flight_run(runs_env, monkeypatch: pytest.MonkeyPatch) -> None:
    mgr, _runs_dir = runs_env
    monkeypatch.setitem(
        server.FETCHERS,
        "slow",
        {
            "label": "Slow",
            "argv": [server.sys.executable, "-c", "import time; time.sleep(10)"],
            "refreshArgs": [],
            "metaKey": "slow",
            "group": "library",
            "color": "#fff",
            "requires": [],
        },
    )
    run = mgr.submit("slow")
    deadline = time.time() + 5
    while time.time() < deadline:
        if run.status in ("running", "launching"):
            break
        time.sleep(0.05)
    mgr.shutdown()
    assert run._finished.is_set() or run.status in ("cancelled", "failed", "cancelling")
    snap = mgr.snapshot()
    assert snap["active"] is None


def test_manifest_fetcher_argv_uses_absolute_script_path() -> None:
    """Manifest scripts launch via an absolute path so cwd never matters."""
    spec = server.FETCHERS["steam"]
    script = spec["argv"][1]
    assert Path(script).is_absolute()
    assert script == str(server.ROOT / "fetchers/fetch_games.py")


def test_execute_runs_from_repo_root_for_nondefault_profile(
    runs_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fetchers must run with cwd=repo root even on a non-default profile.

    Regression guard for the bug where cwd was the profile data dir
    (profiles/<id>/), which has no fetch_*.py and broke every UI run on
    Supabase/account profiles. Profile scoping is via BAKLOG_PROFILE, not cwd.
    """
    import auth.manager

    mgr, _runs_dir = runs_env
    monkeypatch.setattr(server, "get_active_profile_id", lambda: "work")
    monkeypatch.setattr(
        auth.manager,
        "subprocess_env_for_profile",
        lambda pid: {"BAKLOG_PROFILE": pid, "PYTHONUNBUFFERED": "1"},
    )

    captured: dict[str, object] = {}
    real_popen = server.subprocess.Popen

    def capturing_popen(argv, **kwargs):
        captured["cwd"] = kwargs.get("cwd")
        captured["argv"] = list(argv)
        return real_popen(
            [server.sys.executable, "-c", "print('ok')"],
            stdout=kwargs.get("stdout"),
            stderr=kwargs.get("stderr"),
            text=kwargs.get("text", True),
            encoding=kwargs.get("encoding"),
            errors=kwargs.get("errors"),
            bufsize=kwargs.get("bufsize", -1),
            cwd=kwargs.get("cwd"),
        )

    monkeypatch.setattr(server, "popen_fetcher", capturing_popen)

    run = mgr.submit("steam")
    assert run.profile_id == "work"
    assert run._finished.wait(timeout=10)

    assert captured["cwd"] == str(server.ROOT)
    assert captured["argv"][1] == str(server.ROOT / "fetchers/fetch_games.py")


@pytest.fixture()
def internal_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        server.INTERNAL_JOBS,
        "buildClaims",
        {
            "label": "Build free claims feed",
            "script": "fetchers/build_free_claims.py",
            "group": "claims",
            "args": [],
            "options": {},
        },
    )
    monkeypatch.setitem(
        server.INTERNAL_JOBS,
        "claimSources",
        {
            "label": "Fetch claim sources",
            "script": "fetchers/fetch_claim_sources.py",
            "group": "claims",
            "args": [],
            "options": {},
        },
    )


def test_internal_lane_parallel_to_fetcher(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    running = server.Run("demo", runs_dir=runs_dir)
    running.status = "running"
    with mgr._lock:
        mgr._pending.append(running)
        mgr._runs_by_id[running.id] = running
        mgr._active = running

    internal = mgr.submit_internal("buildClaims")

    assert internal._internal
    snap = mgr.snapshot()
    assert snap["active"]["key"] == "demo"
    assert snap["queue"] == []


def test_fetcher_lane_parallel_to_internal(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    internal = server.Run(
        "buildClaims",
        runs_dir=runs_dir,
        internal=True,
    )
    internal.status = "running"
    with mgr._lock:
        mgr._pending.append(internal)
        mgr._runs_by_id[internal.id] = internal
        mgr._internal_active = internal

    fetcher = mgr.submit("demo")

    assert not fetcher._internal
    snap = mgr.snapshot()
    assert snap["internal_active"]["key"] == "buildClaims"
    assert snap["active"]["key"] == "demo"


def test_enrich_lane_parallel_to_fetcher(runs_env) -> None:
    mgr, runs_dir = runs_env
    monkeypatch_item = {
        "label": "Enrich demo",
        "argv": [server.sys.executable, "-c", "print('enrich')"],
        "refreshArgs": [],
        "metaKey": "enrich_demo",
        "group": "enrich",
        "color": "#fff",
        "requires": [],
    }
    server.FETCHERS["enrich_demo"] = monkeypatch_item
    try:
        running = server.Run("demo", runs_dir=runs_dir)
        running.status = "running"
        with mgr._lock:
            mgr._pending.append(running)
            mgr._runs_by_id[running.id] = running
            mgr._active = running

        enrich = mgr.submit("enrich_demo")
        assert enrich._enrich
        snap = mgr.snapshot()
        assert snap["active"]["key"] == "demo"
        assert snap["enrich_active"]["key"] == "enrich_demo"
    finally:
        server.FETCHERS.pop("enrich_demo", None)


def test_internal_lane_still_serializes_among_itself(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    running = server.Run(
        "buildClaims",
        runs_dir=runs_dir,
        internal=True,
    )
    running.status = "running"
    with mgr._lock:
        mgr._pending.append(running)
        mgr._runs_by_id[running.id] = running
        mgr._internal_active = running

    with pytest.raises(ValueError, match="admin job"):
        mgr.submit_internal("claimSources")


def _seed_both_lanes_running(mgr, runs_dir):
    fetcher = server.Run("demo", runs_dir=runs_dir)
    fetcher.status = "running"
    internal = server.Run("buildClaims", runs_dir=runs_dir, internal=True)
    internal.status = "running"
    with mgr._lock:
        mgr._active = fetcher
        mgr._internal_active = internal
        mgr._runs_by_id[fetcher.id] = fetcher
        mgr._runs_by_id[internal.id] = internal
    return fetcher, internal


def test_cancel_all_lane_fetcher_spares_internal(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    fetcher, internal = _seed_both_lanes_running(mgr, runs_dir)

    cancelled = mgr.cancel_all(lane="fetcher")

    assert {c["id"] for c in cancelled} == {fetcher.id}
    assert fetcher._finished.is_set()
    assert not internal._finished.is_set()
    assert mgr._internal_active is internal


def test_cancel_all_lane_internal_spares_fetcher(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    fetcher, internal = _seed_both_lanes_running(mgr, runs_dir)

    cancelled = mgr.cancel_all(lane="internal")

    assert {c["id"] for c in cancelled} == {internal.id}
    assert internal._finished.is_set()
    assert not fetcher._finished.is_set()
    assert mgr._active is fetcher


def test_cancel_all_no_lane_cancels_both(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    fetcher, internal = _seed_both_lanes_running(mgr, runs_dir)

    cancelled = mgr.cancel_all()

    assert {c["id"] for c in cancelled} == {fetcher.id, internal.id}
    assert fetcher._finished.is_set()
    assert internal._finished.is_set()


def test_force_reset_lane_fetcher_spares_internal(runs_env, internal_jobs) -> None:
    mgr, runs_dir = runs_env
    fetcher, internal = _seed_both_lanes_running(mgr, runs_dir)

    result = mgr.force_reset(lane="fetcher")

    assert {c["id"] for c in result["cancelled"]} == {fetcher.id}
    assert fetcher._finished.is_set()
    assert not internal._finished.is_set()
    assert mgr._active is None
    assert mgr._internal_active is internal


def _seed_fetcher_and_enrich_running(mgr, runs_dir):
    fetcher = server.Run("demo", runs_dir=runs_dir)
    fetcher.status = "running"
    enrich = server.Run("hltb", runs_dir=runs_dir, enrich=True)
    enrich.status = "running"
    with mgr._lock:
        mgr._active = fetcher
        mgr._enrich_active = enrich
        mgr._runs_by_id[fetcher.id] = fetcher
        mgr._runs_by_id[enrich.id] = enrich
    return fetcher, enrich


def test_cancel_all_lane_fetcher_spares_enrich(runs_env) -> None:
    mgr, runs_dir = runs_env
    fetcher, enrich = _seed_fetcher_and_enrich_running(mgr, runs_dir)

    cancelled = mgr.cancel_all(lane="fetcher")

    assert {c["id"] for c in cancelled} == {fetcher.id}
    assert fetcher._finished.is_set()
    assert not enrich._finished.is_set()
    assert mgr._enrich_active is enrich


def test_cancel_all_lane_enrich_spares_fetcher(runs_env) -> None:
    mgr, runs_dir = runs_env
    fetcher, enrich = _seed_fetcher_and_enrich_running(mgr, runs_dir)

    cancelled = mgr.cancel_all(lane="enrich")

    assert {c["id"] for c in cancelled} == {enrich.id}
    assert enrich._finished.is_set()
    assert not fetcher._finished.is_set()
    assert mgr._active is fetcher
