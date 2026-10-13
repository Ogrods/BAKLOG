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


def test_synthesize_field_overrides_when_auto_differs() -> None:
    landing = [
        {
            "id": "m1",
            "store": "epic",
            "title": "Edited Title",
            "claim_url": "https://edited.example/claim",
            "ends_at": "2026-10-01T00:00:00Z",
            "claim_urls": {"ios": "https://apps.apple.com/x"},
        }
    ]
    auto = [
        {
            "id": "m1",
            "store": "epic",
            "title": "Original",
            "claim_url": "https://auto.example/claim",
            "ends_at": "2026-09-01T00:00:00Z",
        }
    ]
    payload = synth.synthesize_approved(landing, auto_items=auto)
    assert payload["field_overrides"] == {
        "m1": {
            "title": "Edited Title",
            "claim_url": "https://edited.example/claim",
            "ends_at": "2026-10-01T00:00:00Z",
            "claim_urls": {"ios": "https://apps.apple.com/x"},
        }
    }


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
    json_out = tmp_path / "diff.json"
    assert cff.main(
        ["--before", str(before), "--after", str(after_diff), "--json-out", str(json_out)]
    ) == 0
    out = capsys.readouterr().out
    assert "- A2 <sub>(a)</sub>" in out
    doc = json.loads(json_out.read_text(encoding="utf-8"))
    assert doc["changed"] == ["a"] and doc["added"] == []
    assert doc["titles"] == {"a": "A2"}


def test_diff_markdown_shows_titles_escaped_with_id_fallback() -> None:
    diff = {"added": ["gamerpower-3322", "epic-x"], "removed": ["gone"], "changed": []}
    md = cff.format_diff_markdown(
        diff,
        titles={"gamerpower-3322": "Sausage Hunter", "gone": "Bad_[link](x)\nFixes #1 @me"},
    )
    assert "- Sausage Hunter <sub>(gamerpower-3322)</sub>" in md
    assert "- epic-x\n" in md
    assert "- Bad\\_\\[link\\]\\(x\\) Fixes \\#1 &#64;me <sub>(gone)</sub>" in md
