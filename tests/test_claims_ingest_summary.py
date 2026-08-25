"""Unit tests for scripts/claims_ingest_summary.py (Phase 1 claims cron)."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.claims_ingest_summary as cis


def test_build_markdown_classifies_new_and_gone(tmp_path: Path) -> None:
    auto = [
        {"id": "epic-new", "title": "New Game", "store": "epic", "source": "epic"},
        {"id": "epic-keep", "title": "Keep", "store": "epic", "source": "epic"},
    ]
    landing = [
        {"id": "epic-keep", "title": "Keep", "store": "epic"},
        {"id": "epic-gone", "title": "Gone", "store": "epic"},
    ]
    md = cis.build_markdown(
        auto_items=auto,
        landing_items=landing,
        live_line="OK: age=1.0d",
        live_stale=False,
    )
    assert "New scrape candidates (not in landing): **1**" in md
    assert "Landing ids missing from scrape: **1**" in md
    assert "`epic-new`" in md
    assert "`epic-gone`" in md
    assert "Phase 1: notify only" in md


def test_main_skip_live_writes_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    auto_path = tmp_path / "auto.json"
    landing_path = tmp_path / "landing.json"
    auto_path.write_text(
        json.dumps({"items": [{"id": "a1", "title": "A", "source": "epic"}]}),
        encoding="utf-8",
    )
    landing_path.write_text(
        json.dumps({"items": [{"id": "a1", "title": "A", "store": "epic"}]}),
        encoding="utf-8",
    )
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    code = cis.main(
        [
            "--auto",
            str(auto_path),
            "--landing",
            str(landing_path),
            "--skip-live",
        ]
    )
    assert code == 0
    text = summary.read_text(encoding="utf-8")
    assert "Claims ingest summary" in text
    assert "SKIP: live age check disabled" in text
    captured = capsys.readouterr()
    assert "Claims ingest summary" in captured.out


def test_main_missing_auto_fails(tmp_path: Path) -> None:
    landing = tmp_path / "landing.json"
    landing.write_text(json.dumps({"items": []}), encoding="utf-8")
    code = cis.main(
        [
            "--auto",
            str(tmp_path / "missing.json"),
            "--landing",
            str(landing),
            "--skip-live",
        ]
    )
    assert code == 1
