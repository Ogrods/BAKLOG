"""scripts/approve_feed_pr_ci.py: pick the waiting feed PR run, never fail the job."""

from __future__ import annotations

import pytest

import scripts.approve_feed_pr_ci as apc

RUNS = [
    {"databaseId": 3, "headSha": "new", "status": "completed", "conclusion": "action_required"},
    {"databaseId": 2, "headSha": "old", "status": "completed", "conclusion": "action_required"},
    {"databaseId": 1, "headSha": "new", "status": "completed", "conclusion": "success"},
]


def test_select_waiting_run_matches_sha_and_conclusion() -> None:
    assert apc.select_waiting_run(RUNS, "new")["databaseId"] == 3
    assert apc.select_waiting_run(RUNS, "old")["databaseId"] == 2
    assert apc.select_waiting_run(RUNS, "missing") is None
    assert apc.select_waiting_run([RUNS[2]], "new") is None


def test_main_approves_waiting_run(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    approved: list[int] = []
    monkeypatch.setattr(apc, "list_pr_runs", lambda branch: RUNS)
    monkeypatch.setattr(apc, "approve", lambda repo, run_id: approved.append(run_id) or True)
    assert apc.main(["--sha", "new", "--repo", "o/r", "--wait-seconds", "0"]) == 0
    assert approved == [3]
    assert "Approved CI run 3" in capsys.readouterr().out


def test_main_warns_without_failing_when_nothing_waits(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(apc, "list_pr_runs", lambda branch: [])
    monkeypatch.setattr(apc, "approve", lambda repo, run_id: pytest.fail("must not approve"))
    assert apc.main(["--sha", "abc", "--repo", "o/r", "--wait-seconds", "0"]) == 0
    assert "::warning::No action_required CI run found for abc" in capsys.readouterr().out


def test_dry_run_reports_without_approving(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(apc, "list_pr_runs", lambda branch: RUNS)
    monkeypatch.setattr(apc, "approve", lambda repo, run_id: pytest.fail("must not approve"))
    assert apc.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "newest PR run 3" in out
    assert "would approve run 3" in out
