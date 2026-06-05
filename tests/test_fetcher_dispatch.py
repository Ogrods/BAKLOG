"""Tests for frozen fetcher child dispatch."""

from __future__ import annotations

from baklog_fetcher_dispatch import run_fetcher


def test_run_fetcher_unknown_key():
    assert run_fetcher("not-a-real-fetcher-key", []) == 2


def test_run_fetcher_steam_help_exits_zero():
    # Exercises import + argparse without network or credentials.
    assert run_fetcher("steam", ["--help"]) == 0
