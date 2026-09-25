"""RunManager triggers a deal alert scan after clean itad / claims runs only."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

import server
import shared.deal_alerts as deal_alerts


@pytest.fixture
def mgr_and_scans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runs_dir = tmp_path / "runs"

    def _runs_dir_fn(*, profile_id=None):
        return runs_dir

    monkeypatch.setattr("shared.profile_paths.runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "runs_dir", _runs_dir_fn)
    monkeypatch.setattr(server, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(server, "ACTIVE_RUNS_FILE", runs_dir / "active.json")
    monkeypatch.setattr(server, "RUN_HISTORY_FILE", runs_dir / "history.json")
    monkeypatch.setattr(server, "QUEUE_FILE", runs_dir / "queue.json")
    scans: list[str | None] = []
    monkeypatch.setattr(deal_alerts, "scan", lambda profile_id=None, **_k: scans.append(profile_id) or 0)
    mgr = server.RunManager(runs_dir=runs_dir, enable_watchdog=False)
    yield mgr, runs_dir, scans
    mgr.shutdown()
    mgr.join_threads(timeout=5.0)


def _finish(mgr, runs_dir: Path, key: str, exit_code: int) -> server.Run:
    run = server.Run(key, runs_dir=runs_dir)
    run.status = "done" if exit_code == 0 else "failed"
    run.exit_code = exit_code
    run.ended_at = time.time()
    run.mark_finished()
    mgr._finalize_run(run)
    return run


@pytest.mark.parametrize("key", ["itad", "claims"])
def test_clean_price_runs_trigger_scan(mgr_and_scans, key):
    mgr, runs_dir, scans = mgr_and_scans
    run = _finish(mgr, runs_dir, key, 0)
    assert scans == [run.profile_id]


@pytest.mark.parametrize(("key", "code"), [("itad", 1), ("claims", 2), ("steam", 0), ("wishlistSteam", 0)])
def test_failed_or_unrelated_runs_do_not_scan(mgr_and_scans, key, code):
    mgr, runs_dir, scans = mgr_and_scans
    _finish(mgr, runs_dir, key, code)
    assert scans == []


def test_scan_errors_never_break_finalize(mgr_and_scans, monkeypatch: pytest.MonkeyPatch):
    mgr, runs_dir, _scans = mgr_and_scans

    def boom(*_a, **_k):
        raise RuntimeError("nope")

    monkeypatch.setattr(deal_alerts, "scan", boom)
    run = _finish(mgr, runs_dir, "itad", 0)
    assert any(h.get("id") == run.id for h in mgr.snapshot()["history"])


def test_finalize_twice_scans_once(mgr_and_scans):
    mgr, runs_dir, scans = mgr_and_scans
    run = _finish(mgr, runs_dir, "itad", 0)
    mgr._finalize_run(run)
    assert scans == [run.profile_id]
