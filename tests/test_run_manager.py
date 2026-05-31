"""Tests for RunManager queue, cancel, and persistence."""
from __future__ import annotations

import json
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
    yield mgr, runs_dir
    mgr.shutdown()


def test_submit_rejects_duplicate_key(runs_env):
    mgr, _ = runs_env
    mgr.submit("demo")
    with pytest.raises(ValueError, match="already queued or running"):
        mgr.submit("demo")


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
