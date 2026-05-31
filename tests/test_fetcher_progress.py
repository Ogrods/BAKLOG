"""Tests for fetcher progress helpers and empty-result guard."""
from __future__ import annotations

from fetchers._base import refuse_empty_result
from fetchers._progress import RunStats, done, started


def test_refuse_empty_result_blocks_by_default():
    assert refuse_empty_result([], label="test", allow_empty=False) == 2


def test_refuse_empty_result_allows_with_flag():
    assert refuse_empty_result([], label="test", allow_empty=True) is None


def test_refuse_empty_result_non_empty_ok():
    assert refuse_empty_result([1], label="test", allow_empty=False) is None


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
