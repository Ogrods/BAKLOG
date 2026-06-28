import json
import sys

import pytest

import fetchers.fetch_claim_sources as fcs


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
    monkeypatch.setattr(fcs, "collect_claims", lambda sources, **kw: (items, counts or {"gamerpower": len(items)}))
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_claim_sources.py", "--output", str(out_path), *extra_args])
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
    assert doc["attribution"]


def test_first_run_no_prior_writes(monkeypatch, out_path):
    code = _run(monkeypatch, [_claim("a")], out_path)
    assert code == 0
    assert out_path.exists()


def test_failed_source_carries_prior_rows_forward(monkeypatch, out_path):
    _write_prior(out_path, 0)
    prior = {"items": [_claim("gamerpower-old", "gamerpower"), _claim("itad-old", "itad")]}
    out_path.write_text(json.dumps(prior), encoding="utf-8")
    fresh = [_claim("itad-new", "itad")]

    def fake_collect(sources, **kw):
        return (fresh, {"itad": 1})

    monkeypatch.setattr(fcs, "collect_claims", fake_collect)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_claim_sources.py", "--output", str(out_path)])
    code = fcs.main()
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    ids = {row["id"] for row in doc["items"]}
    assert ids == {"itad-new", "gamerpower-old"}


def test_genuine_zero_source_not_carried_forward(monkeypatch, out_path):
    prior = {"items": [_claim("gamerpower-old", "gamerpower")]}
    out_path.write_text(json.dumps(prior), encoding="utf-8")

    def fake_collect(sources, **kw):
        return ([_claim("itad-new", "itad")], {"gamerpower": 0, "itad": 1, "epic": 0})

    monkeypatch.setattr(fcs, "collect_claims", fake_collect)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_claim_sources.py", "--output", str(out_path)])
    code = fcs.main()
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    ids = {row["id"] for row in doc["items"]}
    assert ids == {"itad-new"}


def test_vanished_source_refuses_exit_3_without_allow_drift(monkeypatch, out_path):
    prior = {"sources": {"gamerpower": 5, "itad": 2}, "items": [_claim("itad-old", "itad")]}
    out_path.write_text(json.dumps(prior), encoding="utf-8")

    def fake_collect(sources, **kw):
        return ([_claim("itad-new", "itad")], {"itad": 1})

    monkeypatch.setattr(fcs, "collect_claims", fake_collect)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_claim_sources.py", "--output", str(out_path)])
    code = fcs.main()
    assert code == 3
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(doc["items"]) == 1


def test_vanished_source_allowed_when_rows_carried_forward(monkeypatch, out_path):
    prior = {
        "sources": {"gamerpower": 1, "itad": 1},
        "items": [_claim("gamerpower-old", "gamerpower"), _claim("itad-old", "itad")],
    }
    out_path.write_text(json.dumps(prior), encoding="utf-8")

    def fake_collect(sources, **kw):
        return ([_claim("itad-new", "itad")], {"itad": 1})

    monkeypatch.setattr(fcs, "collect_claims", fake_collect)
    monkeypatch.setattr(sys, "argv", ["fetchers.fetch_claim_sources.py", "--output", str(out_path)])
    code = fcs.main()
    assert code == 0
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    ids = {row["id"] for row in doc["items"]}
    assert "gamerpower-old" in ids
    assert "itad-new" in ids


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
