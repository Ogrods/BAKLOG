"""Tests for the hosted free-claims downloader (fetch_free_claims.py).

Covers the exit-code refusal contract (empty feed), validated-rows-only
payloads, and attribution passthrough — all offline (no real HTTP).
"""

from __future__ import annotations

import json
import sys

import pytest

import fetchers.fetch_free_claims as ffc


@pytest.fixture
def out_path(tmp_path, monkeypatch):
    out = tmp_path / "free_claims.json"
    monkeypatch.setattr(ffc, "free_claims_path", lambda: out)
    return out


def _run(monkeypatch, data, *extra_args):
    monkeypatch.setattr(ffc, "_fetch_url", lambda url, **kw: data)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_free_claims.py", *extra_args])
    return ffc.main()


def _valid_item(item_id="g1"):
    return {"id": item_id, "store": "steam", "claim_url": "https://example.com/g1"}


def test_writes_valid_items(monkeypatch, out_path):
    code = _run(monkeypatch, {"items": [_valid_item()], "generated_at": "2026-06-08T00:00:00Z"})
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(doc["items"]) == 1
    assert doc["generated_at"] == "2026-06-08T00:00:00Z"


def test_empty_feed_refuses_with_exit_2(monkeypatch, out_path):
    code = _run(monkeypatch, {"items": []})
    assert code == 2
    assert not out_path.exists()


def test_empty_feed_allowed_with_flag(monkeypatch, out_path):
    code = _run(monkeypatch, {"items": []}, "--allow-empty")
    assert code == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["items"] == []


def test_malformed_rows_are_dropped(monkeypatch, out_path):
    data = {
        "items": [
            _valid_item("good"),
            {"id": "no-url", "store": "steam"},  # missing claim_url
            "not-a-dict",
        ]
    }
    code = _run(monkeypatch, data)
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert [i["id"] for i in doc["items"]] == ["good"]


def test_attribution_passed_through(monkeypatch, out_path):
    attribution = [{"label": "GamerPower", "url": "https://www.gamerpower.com/"}]
    code = _run(monkeypatch, {"items": [_valid_item()], "attribution": attribution})
    assert code == 0
    assert json.loads(out_path.read_text(encoding="utf-8"))["attribution"] == attribution


def test_fetch_error_exits_1(monkeypatch, out_path):
    def boom(url, **kw):
        raise ValueError("bad feed")

    monkeypatch.setattr(ffc, "_fetch_url", boom)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_free_claims.py"])
    assert ffc.main() == 1
    assert not out_path.exists()


def test_drift_refuses_with_exit_3(monkeypatch, out_path):
    prior = {"items": [_valid_item(f"g{i}") for i in range(10)]}
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    code = _run(monkeypatch, {"items": [_valid_item("only")]})
    assert code == 3
    assert json.loads(out_path.read_text(encoding="utf-8")) == prior


def test_drift_allowed_with_flag(monkeypatch, out_path):
    prior = {"items": [_valid_item(f"g{i}") for i in range(10)]}
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    code = _run(monkeypatch, {"items": [_valid_item("only")]}, "--allow-drift")
    assert code == 0
    assert len(json.loads(out_path.read_text(encoding="utf-8"))["items"]) == 1


def test_older_hosted_refuses_with_exit_3(monkeypatch, out_path):
    prior = {
        "generated_at": "2026-09-08T22:10:49Z",
        "fetched_at": "2026-09-08T22:10:49Z",
        "items": [_valid_item(f"g{i}") for i in range(7)],
    }
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    hosted = {
        "generated_at": "2026-09-08T18:29:37Z",
        "items": [_valid_item(f"h{i}") for i in range(5)],
    }
    code = _run(monkeypatch, hosted)
    assert code == 3
    assert json.loads(out_path.read_text(encoding="utf-8")) == prior


def test_older_hosted_allowed_with_allow_drift(monkeypatch, out_path):
    prior = {
        "generated_at": "2026-09-08T22:10:49Z",
        "items": [_valid_item(f"g{i}") for i in range(7)],
    }
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    hosted = {
        "generated_at": "2026-09-08T18:29:37Z",
        "items": [_valid_item(f"h{i}") for i in range(5)],
    }
    code = _run(monkeypatch, hosted, "--allow-drift")
    assert code == 0
    assert len(json.loads(out_path.read_text(encoding="utf-8"))["items"]) == 5


def test_newer_hosted_overwrites_local(monkeypatch, out_path):
    prior = {
        "generated_at": "2026-09-08T18:29:37Z",
        "items": [_valid_item(f"g{i}") for i in range(5)],
    }
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    hosted = {
        "generated_at": "2026-09-08T22:10:49Z",
        "items": [_valid_item(f"h{i}") for i in range(7)],
    }
    code = _run(monkeypatch, hosted)
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(doc["items"]) == 7
    assert doc["generated_at"] == "2026-09-08T22:10:49Z"


def test_equal_hosted_generated_at_allowed(monkeypatch, out_path):
    prior = {
        "generated_at": "2026-09-08T22:10:49Z",
        "items": [_valid_item("a"), _valid_item("b")],
    }
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    hosted = {
        "generated_at": "2026-09-08T22:10:49Z",
        "items": [_valid_item("a"), _valid_item("b"), _valid_item("c")],
    }
    code = _run(monkeypatch, hosted)
    assert code == 0
    assert len(json.loads(out_path.read_text(encoding="utf-8"))["items"]) == 3
