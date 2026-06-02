"""Tests for RunManager queue, cancel, and persistence."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

import server


@pytest.fixture()
def runs_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"
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
    mgr = server.RunManager(runs_dir=runs_dir)
    yield mgr, runs_dir
    mgr.cancel_all()
    mgr.shutdown()


def test_submit_rejects_duplicate_key(runs_env):
    mgr, _ = runs_env
    mgr.submit("demo")
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
    queued = server.Run("demo2", runs_dir=runs_dir)
    with mgr._lock:
        mgr._pending.extend([running, queued])
        mgr._runs_by_id[running.id] = running
        mgr._runs_by_id[queued.id] = queued
        mgr._active = running
    with pytest.raises(ValueError, match="queue full"):
        mgr.submit("demo3")


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

    # Pre-fill one slot so concurrent submits race for the last slot.
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
    assert len(errors) >= 2


def test_launch_timeout_marks_failed_and_admits_next(runs_env, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server, "LAUNCH_TIMEOUT_SEC", 0.1)
    mgr, _runs_dir = runs_env
    launch_started = threading.Event()

    def blocking_popen(*args, **kwargs):
        launch_started.set()
        time.sleep(60)

    monkeypatch.setattr(server.subprocess, "Popen", blocking_popen)
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

    monkeypatch.setattr(server.subprocess, "Popen", blocking_popen)
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
                "print('started'); import time; time.sleep(10)",
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
    mgr = server.RunManager(runs_dir=runs_dir)
    snap = mgr.snapshot()
    assert snap["active"] or snap["queue"]
    mgr.shutdown()
