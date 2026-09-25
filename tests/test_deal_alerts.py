"""shared/deal_alerts.py: seed-without-emit, drop/claim diffs, dedupe, caps, self-heal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import shared.deal_alerts as da

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Path]:
    paths = {
        "state": tmp_path / "cache" / "deal_alerts.json",
        "itad": tmp_path / "itad_prices.json",
        "claims": tmp_path / "free_claims.json",
    }
    monkeypatch.setattr(da, "state_path", lambda profile_id=None: paths["state"])
    monkeypatch.setattr(da, "itad_path", lambda profile_id=None: paths["itad"])
    monkeypatch.setattr(da, "free_claims_path", lambda profile_id=None: paths["claims"])
    monkeypatch.setattr(da, "alerts_enabled", lambda profile_id=None: True)
    return paths


def _row(price: float, *, match: str = "appid", title: str = "Elden Ring", cut: int = 40) -> dict:
    return {"shop": "GOG", "price": price, "currency": "USD", "cut": cut, "match": match, "title": title}


def _itad(files, **rows: dict) -> None:
    files["itad"].write_text(json.dumps({"by_key": rows}), encoding="utf-8")


def _claims(files, *items: dict) -> None:
    files["claims"].write_text(json.dumps({"items": list(items)}), encoding="utf-8")


def _claim(title: str, **extra) -> dict:
    return {"id": f"feed-{title}", "store": "epic", "title": title, **extra}


def _pending_ids() -> list[str]:
    return [e["id"] for e in da.take_pending()]


def test_first_scan_seeds_without_emitting(files):
    _itad(files, **{"wishlist:570": _row(49.99)})
    _claims(files, _claim("Astrea"))
    assert da.scan(pro=True, now=NOW) == 0
    state = da.load_state()
    assert state["seeded_at"]
    assert state["price_snapshot"]["wishlist:570"]["price"] == 49.99
    assert state["seen_claim_keys"]
    assert da.take_pending() == []


def test_price_drop_emits_once(files):
    _itad(files, **{"wishlist:570": _row(49.99)})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:570": _row(29.99)})
    assert da.scan(pro=True, now=NOW) == 1
    [event] = da.take_pending()
    assert event["id"] == "drop:wishlist:570:2999"
    assert event["kind"] == "price_drop"
    assert event["title"] == "Elden Ring"
    assert (event["price"], event["was"], event["shop"]) == (29.99, 49.99, "GOG")
    assert da.scan(pro=True, now=NOW) == 0
    assert len(da.take_pending()) == 1


def test_rise_and_tiny_change_do_not_emit(files):
    _itad(files, **{"wishlist:1": _row(10.0), "wishlist:2": _row(10.0)})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:1": _row(12.0), "wishlist:2": _row(9.995)})
    assert da.scan(pro=True, now=NOW) == 0


def test_title_matched_rows_never_emit(files):
    _itad(files, **{"wishlist:gog-1": _row(20.0, match="title")})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:gog-1": _row(5.0, match="title")})
    assert da.scan(pro=True, now=NOW) == 0
    assert "wishlist:gog-1" not in da.load_state()["price_snapshot"]


def test_new_key_after_seed_is_snapshotted_not_alerted(files):
    _itad(files, **{"wishlist:1": _row(10.0)})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:1": _row(10.0), "wishlist:2": _row(3.0)})
    assert da.scan(pro=True, now=NOW) == 0
    assert "wishlist:2" in da.load_state()["price_snapshot"]


def test_new_claim_emits_and_feed_id_churn_is_ignored(files):
    _claims(files, _claim("Old Game"))
    da.scan(pro=True, now=NOW)
    _claims(files, _claim("Old Game", id="new-feed-id"), _claim("Astrea", steam_appid=1755830))
    assert da.scan(pro=True, now=NOW) == 1
    [event] = da.take_pending()
    assert event["kind"] == "free_claim"
    assert event["title"] == "Astrea"
    assert event["id"].startswith("claim:") and "appid:1755830" in event["id"]


def test_claim_matched_by_appid_under_new_title_is_not_new(files):
    _claims(files, _claim("Portal 2", steam_appid=620))
    da.scan(pro=True, now=NOW)
    _claims(files, _claim("Portal 2 Giveaway Edition", steam_appid=620))
    assert da.scan(pro=True, now=NOW) == 0


def test_premium_only_claims_respect_plan(files):
    _claims(files, _claim("Seed"))
    da.scan(pro=False, now=NOW)
    _claims(files, _claim("Seed"), _claim("Prime Game", premium_only=True))
    assert da.scan(pro=False, now=NOW) == 0
    assert da.take_pending() == []


def test_premium_only_claims_emit_for_pro(files):
    _claims(files, _claim("Seed"))
    da.scan(pro=True, now=NOW)
    _claims(files, _claim("Seed"), _claim("Prime Game", premium_only=True))
    assert da.scan(pro=True, now=NOW) == 1


def test_expired_claims_are_not_queued_and_expire_from_pending(files):
    _claims(files, _claim("Seed"))
    da.scan(pro=True, now=NOW)
    past = (NOW - timedelta(hours=1)).isoformat()
    soon = (NOW + timedelta(hours=1)).isoformat()
    _claims(files, _claim("Seed"), _claim("Gone", ends_at=past), _claim("Soon", ends_at=soon))
    assert da.scan(pro=True, now=NOW) == 1
    da.scan(pro=True, now=NOW + timedelta(hours=2))
    assert da.load_state()["pending"] == []


def test_price_events_expire_after_ttl(files):
    _itad(files, **{"wishlist:1": _row(10.0)})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:1": _row(5.0)})
    da.scan(pro=True, now=NOW)
    da.scan(pro=True, now=NOW + da.PRICE_EVENT_TTL + timedelta(minutes=1))
    assert da.load_state()["pending"] == []


def test_pending_and_emitted_caps(files, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(da, "MAX_PENDING", 3)
    monkeypatch.setattr(da, "MAX_EMITTED", 4)
    _itad(files, **{f"wishlist:{i}": _row(100.0, title=f"G{i}") for i in range(6)})
    da.scan(pro=True, now=NOW)
    for step in range(1, 3):
        _itad(files, **{f"wishlist:{i}": _row(100.0 - step * 10, title=f"G{i}") for i in range(6)})
        da.scan(pro=True, now=NOW + timedelta(minutes=step))
    state = da.load_state()
    assert len(state["pending"]) == 3
    assert len(state["emitted"]) == 4


def test_ack_removes_pending(files):
    _itad(files, **{"wishlist:1": _row(10.0), "wishlist:2": _row(10.0)})
    da.scan(pro=True, now=NOW)
    _itad(files, **{"wishlist:1": _row(5.0), "wishlist:2": _row(5.0)})
    da.scan(pro=True, now=NOW)
    ids = _pending_ids()
    assert da.ack([ids[0], "unknown"]) == 1
    assert _pending_ids() == ids[1:]
    assert da.ack([]) == 0


def test_claims_seed_independently_of_prices(files):
    _itad(files, **{"wishlist:1": _row(10.0)})
    da.scan(pro=True, now=NOW)
    _claims(files, _claim("Already Free"))
    assert da.scan(pro=True, now=NOW) == 0


def test_corrupt_state_self_heals(files):
    files["state"].parent.mkdir(parents=True)
    files["state"].write_text("{not json", encoding="utf-8")
    _itad(files, **{"wishlist:1": _row(10.0)})
    assert da.scan(pro=True, now=NOW) == 0
    assert da.load_state()["price_snapshot"]["wishlist:1"]["price"] == 10.0


def test_wrong_version_state_resets(files):
    files["state"].parent.mkdir(parents=True)
    files["state"].write_text(json.dumps({"version": 99, "pending": [{"id": "x"}]}), encoding="utf-8")
    assert da.load_state()["pending"] == []


def test_entry_points_never_raise(files, monkeypatch: pytest.MonkeyPatch):
    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(da, "load_state", boom)
    assert da.scan(pro=True) == 0
    assert da.take_pending() == []
    assert da.ack(["x"]) == 0


def test_disabled_refreshes_snapshot_without_queueing(files):
    _itad(files, **{"wishlist:1": _row(10.0)})
    _claims(files, _claim("Seed"))
    da.scan(pro=True, enabled=False, now=NOW)
    _itad(files, **{"wishlist:1": _row(5.0)})
    _claims(files, _claim("Seed"), _claim("New"))
    assert da.scan(pro=True, enabled=False, now=NOW) == 0
    assert da.load_state()["price_snapshot"]["wishlist:1"]["price"] == 5.0
    assert da.scan(pro=True, enabled=True, now=NOW) == 0
    assert da.take_pending() == []


def test_alerts_enabled_requires_opt_in_and_pro(monkeypatch: pytest.MonkeyPatch):
    import shared.pro_settings as ps

    monkeypatch.setattr(ps, "read_pro_settings", lambda **_k: {"dealAlertsEnabled": True})
    monkeypatch.setattr(da, "_default_pro", lambda: True)
    assert da.alerts_enabled() is True
    monkeypatch.setattr(da, "_default_pro", lambda: False)
    assert da.alerts_enabled() is False
    monkeypatch.setattr(da, "_default_pro", lambda: True)
    monkeypatch.setattr(ps, "read_pro_settings", lambda **_k: {"cloudMirrorEnabled": True})
    assert da.alerts_enabled() is False


def test_missing_sources_are_a_noop(files):
    assert da.scan(pro=True, now=NOW) == 0
    assert da.load_state()["seeded_at"] is None
