"""Unit tests for scripts/claims_ingest_summary.py (Phase 1 claims cron)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scripts.claims_ingest_summary as cis


def test_sanitize_title_strips_backticks_and_newlines() -> None:
    assert cis.sanitize_title("Foo\n`bar`  baz") == "Foo 'bar' baz"
    assert cis.sanitize_title("   ") == "(no title)"


def test_build_markdown_classifies_new_and_gone() -> None:
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
        skew_line="WARN: landing vs live skew=10.00d",
    )
    assert "New scrape candidates (not in landing): **1**" in md
    assert "Landing ids missing from scrape: **1**" in md
    assert "`epic-new`" in md
    assert "`epic-gone`" in md
    assert "Phase 1: notify only" in md
    assert "Landing vs live skew" in md


def test_landing_vs_live_skew_line() -> None:
    land = datetime(2026, 8, 24, tzinfo=UTC)
    live = datetime(2026, 8, 7, tzinfo=UTC)
    line = cis.landing_vs_live_skew_line(land, live, skew_days=1.0)
    assert line is not None
    assert line.startswith("WARN:")
    ok = cis.landing_vs_live_skew_line(land, land + timedelta(hours=12), skew_days=1.0)
    assert ok is not None
    assert ok.startswith("OK:")


def _old_live_doc(items: list[dict], *, days: float = 10.0) -> dict:
    generated = datetime.now(UTC) - timedelta(days=days)
    return {"generated_at": generated.isoformat(), "items": items}


def test_check_live_age_old_but_unchanged_is_ok(monkeypatch) -> None:
    claims = [{"id": "a1", "title": "A", "store": "epic", "claim_url": "https://x/a1"}]
    monkeypatch.setattr(cis, "fetch_live_doc", lambda _url: (_old_live_doc(claims), None))
    line, stale, generated = cis.check_live_age(
        "https://example.invalid", max_age_days=7, landing_items=[dict(claims[0])]
    )
    assert stale is False
    assert generated is not None
    assert line.startswith("OK:")
    assert "claims unchanged" in line


def test_check_live_age_old_and_divergent_is_stale(monkeypatch) -> None:
    live = [{"id": "a1", "title": "A", "store": "epic"}]
    landing = [*live, {"id": "b2", "title": "B", "store": "gog"}]
    monkeypatch.setattr(cis, "fetch_live_doc", lambda _url: (_old_live_doc(live), None))
    line, stale, _ = cis.check_live_age(
        "https://example.invalid", max_age_days=7, landing_items=landing
    )
    assert stale is True
    assert line.startswith("WARN:")
    assert "refresh and republish" in line


def test_check_live_age_old_without_landing_stays_stale(monkeypatch) -> None:
    live = [{"id": "a1", "title": "A", "store": "epic"}]
    monkeypatch.setattr(cis, "fetch_live_doc", lambda _url: (_old_live_doc(live), None))
    line, stale, _ = cis.check_live_age("https://example.invalid", max_age_days=7)
    assert stale is True
    assert line.startswith("WARN:")


def test_check_live_age_fresh_is_ok(monkeypatch) -> None:
    live = [{"id": "a1", "title": "A", "store": "epic"}]
    monkeypatch.setattr(cis, "fetch_live_doc", lambda _url: (_old_live_doc(live, days=1), None))
    line, stale, _ = cis.check_live_age("https://example.invalid", max_age_days=7, landing_items=[])
    assert stale is False
    assert line.startswith("OK:")
    assert "claims unchanged" not in line


def test_main_skip_live_writes_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    auto_path = tmp_path / "auto.json"
    landing_path = tmp_path / "landing.json"
    auto_path.write_text(
        json.dumps({"items": [{"id": "a1", "title": "A", "source": "epic"}]}),
        encoding="utf-8",
    )
    landing_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-24T00:00:00Z",
                "items": [{"id": "a1", "title": "A", "store": "epic"}],
            }
        ),
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


def test_feed_runway_line() -> None:
    now = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)

    def iso(delta: timedelta) -> str:
        return (now + delta).isoformat().replace("+00:00", "Z")

    assert cis.feed_runway_line([], now=now).startswith("WARN: published feed has no live claims")
    expired = [{"id": "a", "ends_at": iso(timedelta(days=-1))}]
    assert cis.feed_runway_line(expired, now=now).startswith("WARN: published feed has no live")
    ending = [{"id": "b", "ends_at": iso(timedelta(hours=10))}]
    assert cis.feed_runway_line(ending, now=now).startswith("WARN: all 1 live claim(s) end within 48h")
    healthy = [*ending, {"id": "c", "ends_at": iso(timedelta(days=5))}]
    assert cis.feed_runway_line(healthy, now=now) == "OK: 2 live claim(s) in the published feed"
    undated = [*ending, {"id": "d", "ends_at": None}]
    assert cis.feed_runway_line(undated, now=now).startswith("OK: 2 live claim(s)")


def test_build_markdown_includes_runway_line() -> None:
    md = cis.build_markdown(
        auto_items=[],
        landing_items=[],
        live_line="SKIP",
        live_stale=False,
        runway_line="WARN: published feed has no live claims",
    )
    assert "### Feed runway" in md
    assert "WARN: published feed has no live claims" in md
