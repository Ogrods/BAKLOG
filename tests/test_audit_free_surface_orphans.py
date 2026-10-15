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


def test_audit_expired_absent_orphan_is_high_until_pruned() -> None:
    audit = _load_audit()
    approved = {"ids": ["epic-gone"]}
    report = {"approved": audit._approved_audit(approved, {"items": []}, {"items": []}, None)}
    findings = audit._compile_findings(report)
    assert report["approved"]["orphans_not_in_built"] == ["epic-gone"]
    assert report["approved"]["orphans_held_live_listing"] == []
    high = [f for f in findings if f["severity"] == "high" and f.get("row") == "epic-gone"]
    assert len(high) == 1
