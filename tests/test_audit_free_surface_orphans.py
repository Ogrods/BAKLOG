"""Audit severity for approved-not-in-built (ingest --fail-on high gate)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_audit():
    path = ROOT / "scripts" / "audit_free_surface_data.py"
    spec = importlib.util.spec_from_file_location("audit_free_surface_data", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_audit_built_expiry_uses_claims_expiry_with_auto_last_seen() -> None:
    """Published GP rows omit last_seen; audit must join auto before first_seen+14d."""
    from datetime import UTC, datetime

    audit = _load_audit()
    now = datetime(2026, 11, 4, 22, 0, 0, tzinfo=UTC)
    built_row = {
        "id": "gamerpower-live",
        "store": "indiegala",
        "title": "Still Live",
        "source": "gamerpower",
        "claim_url": "https://www.gamerpower.com/open/x",
        "ends_at": None,
        "first_seen": "2026-10-01T00:00:00Z",
        "last_seen": None,
    }
    live_by_id = {
        "gamerpower-live": {
            **built_row,
            "last_seen": "2026-11-04T19:00:00Z",
        }
    }
    assert audit._is_expired(built_row, now) is True
    assert audit._is_expired(built_row, now, live_by_id=live_by_id) is False
    issues = audit._row_issues(
        built_row, now=now, feed_name="built", live_by_id=live_by_id
    )
    assert "expired" not in issues


def test_audit_built_itad_null_ends_at_past_first_seen_is_expired() -> None:
    from datetime import UTC, datetime

    audit = _load_audit()
    now = datetime(2026, 11, 4, 22, 0, 0, tzinfo=UTC)
    row = {
        "id": "itad-stale",
        "store": "steam",
        "title": "Stale",
        "source": "itad",
        "claim_url": "https://isthereanydeal.com/giveaway/x",
        "ends_at": None,
        "first_seen": "2026-10-01T00:00:00Z",
    }
    assert audit._is_expired(row, now) is True
    assert "expired" in audit._row_issues(row, now=now, feed_name="built")


def test_audit_held_live_listing_is_not_high() -> None:
    audit = _load_audit()
    approved = {"ids": ["gamerpower-1"]}
    auto = {
        "items": [
            {
                "id": "gamerpower-1",
                "title": "Held",
                "source": "gamerpower",
                "ends_at": None,
                "store": "other",
                "claim_url": "https://www.gamerpower.com/open/x",
            }
        ]
    }
    built = {"items": []}
    report = {"approved": audit._approved_audit(approved, auto, built, None)}
    findings = audit._compile_findings(report)
    high = [f for f in findings if f["severity"] == "high"]
    low_held = [
        f
        for f in findings
        if f["severity"] == "low" and f.get("row") == "gamerpower-1"
    ]
    assert report["approved"]["orphans_held_live_listing"] == ["gamerpower-1"]
    assert report["approved"]["orphans_not_in_built"] == []
    assert high == []
    assert low_held


def test_audit_gamerpower_absent_without_row_stays_high() -> None:
    """No auto/input row: cannot prove undated hold; keep high (matches build)."""
    audit = _load_audit()
    approved = {"ids": ["gamerpower-99"]}
    report = {"approved": audit._approved_audit(approved, {"items": []}, {"items": []}, None)}
    findings = audit._compile_findings(report)
    assert report["approved"]["orphans_held_live_listing"] == []
    assert report["approved"]["orphans_not_in_built"] == ["gamerpower-99"]
    assert any(f["severity"] == "high" and f.get("row") == "gamerpower-99" for f in findings)


def test_audit_key_matched_sibling_in_built_is_not_high() -> None:
    """ITAD-approved id may ship as an Epic row; audit must not flag a high orphan."""
    audit = _load_audit()
    approved = {
        "ids": ["itad-073a56345192"],
        "field_overrides": {"itad-073a56345192": {"title": "Songs of Conquest"}},
    }
    auto = {
        "items": [
            {
                "id": "epic-songs-of-conquest",
                "store": "epic",
                "title": "Songs of Conquest",
                "claim_url": "https://store.epicgames.com/en-US/p/songs-of-conquest",
                "ends_at": "2099-01-01T00:00:00Z",
                "source": "epic",
            }
        ]
    }
    built = {
        "items": [
            {
                "id": "epic-songs-of-conquest",
                "store": "epic",
                "title": "Songs of Conquest",
                "claim_url": "https://store.epicgames.com/en-US/p/songs-of-conquest",
                "ends_at": "2099-01-01T00:00:00Z",
                "source": "epic",
            }
        ]
    }
    report = {"approved": audit._approved_audit(approved, auto, built, None)}
    findings = audit._compile_findings(report)
    assert report["approved"]["orphans_not_in_built"] == []
    assert report["approved"]["orphans_represented_by_stable_key"]
    assert not [f for f in findings if f["severity"] == "high"]


def test_audit_expired_absent_orphan_is_high_until_pruned() -> None:
    audit = _load_audit()
    approved = {"ids": ["epic-gone"]}
    report = {"approved": audit._approved_audit(approved, {"items": []}, {"items": []}, None)}
    findings = audit._compile_findings(report)
    assert report["approved"]["orphans_not_in_built"] == ["epic-gone"]
    assert report["approved"]["orphans_held_live_listing"] == []
    high = [f for f in findings if f["severity"] == "high" and f.get("row") == "epic-gone"]
    assert len(high) == 1
