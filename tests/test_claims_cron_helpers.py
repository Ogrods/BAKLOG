"""Tests for synth_claims_approved_from_landing and claims_feed_fingerprint."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.claims_feed_fingerprint as cff
import scripts.synth_claims_approved_from_landing as synth


def test_synthesize_approved_ids_and_premium() -> None:
    landing = [
        {"id": "a", "store": "epic", "title": "A", "premium_only": True},
        {"id": "b", "store": "steam", "title": "B"},
    ]
    payload = synth.synthesize_approved(landing)
    assert payload["ids"] == ["a", "b"]
    assert payload["premium_only_ids"] == ["a"]
    assert "store_overrides" not in payload


def test_synthesize_store_overrides_when_auto_differs() -> None:
    landing = [{"id": "m1", "store": "epic_mobile", "title": "M"}]
    auto = [{"id": "m1", "store": "epic", "title": "M", "source": "itad"}]
    payload = synth.synthesize_approved(landing, auto_items=auto)
    assert payload["store_overrides"] == {"m1": "epic_mobile"}


def test_synthesize_cli_writes_file(tmp_path: Path) -> None:
    landing = tmp_path / "landing.json"
    out = tmp_path / "approved.json"
    landing.write_text(
        json.dumps({"items": [{"id": "x", "store": "epic", "premium_only": True}]}),
        encoding="utf-8",
    )
    code = synth.main(
        ["--landing", str(landing), "--output", str(out), "--no-auto"]
    )
    assert code == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["ids"] == ["x"]
    assert doc["premium_only_ids"] == ["x"]


def test_fingerprint_ignores_enrich_churn() -> None:
    a = {
        "id": "epic-1",
        "store": "epic",
        "title": "Game",
        "claim_url": "https://example.com/a",
        "ends_at": "2026-09-01T00:00:00Z",
        "source": "epic",
        "header_image": "https://cdn/old.jpg",
        "review_percent": 80,
        "generated_at": "2026-01-01T00:00:00Z",
    }
    b = {
        **a,
        "header_image": "https://cdn/new.jpg",
        "review_percent": 90,
        "blurb": "new blurb",
        "generated_at": "2026-08-24T00:00:00Z",
    }
    assert cff.item_fingerprint(a) == cff.item_fingerprint(b)


def test_fingerprint_detects_ends_at_change() -> None:
    a = {"id": "epic-1", "store": "epic", "title": "Game", "ends_at": "2026-09-01T00:00:00Z"}
    b = {"id": "epic-1", "store": "epic", "title": "Game", "ends_at": "2026-09-02T00:00:00Z"}
    assert cff.item_fingerprint(a) != cff.item_fingerprint(b)


def test_diff_fingerprints_added_removed_changed() -> None:
    before = cff.fingerprint_items(
        [
            {"id": "keep", "store": "epic", "title": "Keep", "ends_at": "a"},
            {"id": "gone", "store": "epic", "title": "Gone"},
            {"id": "chg", "store": "epic", "title": "Old"},
        ]
    )
    after = cff.fingerprint_items(
        [
            {"id": "keep", "store": "epic", "title": "Keep", "ends_at": "a"},
            {"id": "new", "store": "epic", "title": "New"},
            {"id": "chg", "store": "epic", "title": "NewTitle"},
        ]
    )
    diff = cff.diff_fingerprints(before, after)
    assert diff["added"] == ["new"]
    assert diff["removed"] == ["gone"]
    assert diff["changed"] == ["chg"]
    assert cff.changed(diff)


def test_fingerprint_cli_exit_codes(tmp_path: Path, capsys) -> None:
    before = tmp_path / "before.json"
    after_same = tmp_path / "after_same.json"
    after_diff = tmp_path / "after_diff.json"
    payload = {
        "generated_at": "2026-08-01T00:00:00Z",
        "items": [{"id": "a", "store": "epic", "title": "A", "claim_url": "https://x"}],
    }
    before.write_text(json.dumps(payload), encoding="utf-8")
    after_same.write_text(
        json.dumps({**payload, "generated_at": "2026-08-24T00:00:00Z"}),
        encoding="utf-8",
    )
    after_diff.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "a",
                        "store": "epic",
                        "title": "A2",
                        "claim_url": "https://x",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert cff.main(["--before", str(before), "--after", str(after_same)]) == 3
    assert cff.main(["--before", str(before), "--after", str(after_diff)]) == 0
    out = capsys.readouterr().out
    assert "fingerprint diff" in out.lower() or "Changed" in out
