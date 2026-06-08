"""Tests for the auto claim-source aggregator (fetch_claim_sources.py).

Covers the exit-code refusal contract: empty (exit 2) when all sources fail and
drift (exit 3) when a partial outage sharply shrinks the feed. Fully offline —
``collect_claims`` is stubbed so no real HTTP is performed.
"""

from __future__ import annotations

import json
import sys

import pytest

import fetch_claim_sources as fcs


@pytest.fixture
def out_path(tmp_path):
    return tmp_path / "free_claims.auto.json"


def _claim(item_id, source="gamerpower"):
    return {
        "id": item_id,
        "store": "steam",
        "claim_url": f"https://example.com/{item_id}",
        "title": item_id,
        "source": source,
    }


def _run(monkeypatch, items, out_path, *extra_args, counts=None):
    monkeypatch.setattr(
        fcs, "collect_claims", lambda sources, **kw: (items, counts or {"gamerpower": len(items)})
    )
    monkeypatch.setattr(
        sys, "argv", ["fetch_claim_sources.py", "--output", str(out_path), *extra_args]
    )
    return fcs.main()


def _write_prior(out_path, n):
    rows = [_claim(f"old{i}") for i in range(n)]
    out_path.write_text(json.dumps({"items": rows}), encoding="utf-8")


def test_all_sources_empty_refuses_exit_2(monkeypatch, out_path):
    code = _run(monkeypatch, [], out_path)
    assert code == 2
    assert not out_path.exists()


def test_empty_allowed_with_flag(monkeypatch, out_path):
    code = _run(monkeypatch, [], out_path, "--allow-empty")
    assert code == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["items"] == []


def test_drift_shrink_refuses_exit_3(monkeypatch, out_path):
    _write_prior(out_path, 10)
    code = _run(monkeypatch, [_claim("a"), _claim("b")], out_path)
    assert code == 3
    # Prior feed must be left untouched.
    assert len(json.loads(out_path.read_text(encoding="utf-8"))["items"]) == 10


def test_drift_allowed_with_flag(monkeypatch, out_path):
    _write_prior(out_path, 10)
    code = _run(monkeypatch, [_claim("a"), _claim("b")], out_path, "--allow-drift")
    assert code == 0
    assert len(json.loads(out_path.read_text(encoding="utf-8"))["items"]) == 2


def test_normal_run_writes_feed_with_attribution(monkeypatch, out_path):
    code = _run(monkeypatch, [_claim("a"), _claim("b"), _claim("c")], out_path)
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(doc["items"]) == 3
    assert doc["attribution"]  # GamerPower attribution present


def test_first_run_no_prior_writes(monkeypatch, out_path):
    code = _run(monkeypatch, [_claim("a")], out_path)
    assert code == 0
    assert out_path.exists()


def test_collect_claims_keeps_cross_source_same_title(monkeypatch):
    def fake_epic(**kw):
        return [
            {
                "id": "epic-brocco",
                "store": "other",
                "title": "Mr.Brocco & Co",
                "claim_url": "https://example.com/epic",
                "source": "epic",
            }
        ]

    def fake_gamerpower():
        return [
            {
                "id": "gamerpower-brocco",
                "store": "other",
                "title": "Mr.Brocco And Co (IndieGala) Giveaway",
                "claim_url": "https://example.com/gp",
                "source": "gamerpower",
            }
        ]

    monkeypatch.setattr(fcs, "fetch_epic_claims", fake_epic)
    monkeypatch.setattr(fcs, "fetch_gamerpower_claims", fake_gamerpower)
    items, counts = fcs.collect_claims({"epic", "gamerpower"})
    assert counts["epic"] == 1
    assert counts["gamerpower"] == 1
    assert len(items) == 2
    ids = {item["id"] for item in items}
    assert ids == {"epic-brocco", "gamerpower-brocco"}
