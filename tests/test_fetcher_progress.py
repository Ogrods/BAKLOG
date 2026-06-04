"""Tests for fetcher progress helpers and empty/drift guards."""
from __future__ import annotations

import json

from fetchers._base import refuse_drift_result, refuse_empty_result
from fetchers._progress import (
    HeartbeatTimer,
    RunStats,
    pct,
    progress_line,
    started,
)


def test_refuse_empty_result_blocks_by_default():
    assert refuse_empty_result([], label="test", allow_empty=False) == 2


def test_refuse_empty_result_allows_with_flag():
    assert refuse_empty_result([], label="test", allow_empty=True) is None


def test_refuse_empty_result_non_empty_ok():
    assert refuse_empty_result([1], label="test", allow_empty=False) is None


def _write_games_file(path, count):
    payload = {"game_count": count, "games": [{"id": i} for i in range(count)]}
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_refuse_drift_no_baseline_passes(tmp_path):
    # No previous file → can't measure drift → return None.
    out = tmp_path / "games.json"
    assert refuse_drift_result(list(range(5)), label="x", allow_drift=False, output_path=out) is None


def test_refuse_drift_within_threshold_passes(tmp_path):
    out = tmp_path / "games.json"
    _write_games_file(out, 100)
    # 60 >= floor(50) → allowed.
    assert refuse_drift_result(list(range(60)), label="x", allow_drift=False, output_path=out) is None


def test_refuse_drift_under_threshold_blocks(tmp_path):
    out = tmp_path / "games.json"
    _write_games_file(out, 600)
    # 3 << floor(300) → exit 3.
    assert refuse_drift_result(list(range(3)), label="x", allow_drift=False, output_path=out) == 3


def test_refuse_drift_allow_drift_overrides(tmp_path):
    out = tmp_path / "games.json"
    _write_games_file(out, 600)
    assert refuse_drift_result(list(range(3)), label="x", allow_drift=True, output_path=out) is None


def test_refuse_drift_custom_threshold(tmp_path):
    out = tmp_path / "games.json"
    _write_games_file(out, 100)
    # threshold 0.9 → floor 90 → 80 fails.
    assert (
        refuse_drift_result(
            list(range(80)), label="x", allow_drift=False, output_path=out, threshold=0.9
        )
        == 3
    )


def test_refuse_drift_handles_malformed_baseline(tmp_path):
    out = tmp_path / "games.json"
    out.write_text("{ not valid json", encoding="utf-8")
    assert refuse_drift_result(list(range(5)), label="x", allow_drift=False, output_path=out) is None


def test_refuse_drift_accepts_int_count(tmp_path):
    out = tmp_path / "games.json"
    _write_games_file(out, 200)
    assert refuse_drift_result(10, label="x", allow_drift=False, output_path=out) == 3
    assert refuse_drift_result(120, label="x", allow_drift=False, output_path=out) is None


def test_pct_partial_and_total():
    assert pct(0, 10) == "0%"
    assert pct(5, 10) == "50%"
    assert pct(10, 10) == "100%"
    assert pct(11, 10) == "100%"
    assert pct(1, 0) == ""
    assert pct(1, -1) == ""


def test_progress_line_with_and_without_total():
    assert progress_line(3, 10, "phase") == "[3/10] (30%) phase"
    assert progress_line(3, 10, "phase", "detail") == "[3/10] (30%) phase: detail"
    assert progress_line(3, 0, "phase", "detail") == "[3] phase: detail"


def test_heartbeat_timer_tick_progress_emits_after_interval(capsys, monkeypatch):
    times = [0.0, 0.0, 30.0, 30.0]

    def fake_monotonic():
        return times.pop(0) if times else 60.0

    monkeypatch.setattr("fetchers._progress.time.monotonic", fake_monotonic)
    timer = HeartbeatTimer(interval=25.0)
    timer.tick_progress(2, 8, "catalog", "1 hits")
    assert capsys.readouterr().out == ""
    timer.tick_progress(3, 8, "catalog", "2 hits")
    out = capsys.readouterr().out
    assert "[3/8]" in out
    assert "(38%)" in out
    assert "catalog: 2 hits" in out
    timer.tick_progress(4, 8, "catalog", "3 hits")
    assert capsys.readouterr().out == ""


def test_heartbeat_timer_emits_after_interval(capsys):
    import time as time_mod

    timer = HeartbeatTimer(interval=0.02)
    timer.tick("silent")
    assert capsys.readouterr().out == ""
    time_mod.sleep(0.03)
    timer.tick("still working")
    assert "still working" in capsys.readouterr().out
    timer.tick("no repeat")
    assert capsys.readouterr().out == ""


def test_run_stats_finish_returns_exit_code(capsys):
    t0 = started("demo")
    stats = RunStats()
    stats.warn("something odd")
    code = stats.finish("demo", t0, exit_code=0, extra="ok")
    assert code == 0
    out = capsys.readouterr()
    assert "demo started" in out.out
    assert "demo done" in out.out
    assert "1 warnings" in out.out
    assert "something odd" in out.err
