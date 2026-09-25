"""Tray deal alerts: notification text, poll cycle, snooze, frozen-only loop."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

import tray_app
from shared import deal_alert_tray as dat


def _drop(title="Elden Ring", **kw):
    return {"id": f"drop:{title}", "kind": "price_drop", "title": title, **kw}


def _claim(title="Astrea: Six Sided Oracles", **kw):
    return {"id": f"claim:{title}", "kind": "free_claim", "title": title, **kw}


def test_single_drop_message():
    [(title, body)] = dat.compose_notifications([_drop(cut=40, shop="GOG", price_str="$29.99")])
    assert title == "Wishlist price drop"
    assert body == "Elden Ring is 40% off at GOG ($29.99). Open BAKLOG for details."


def test_single_drop_without_cut_or_price_str():
    [(_, body)] = dat.compose_notifications([_drop(price=5, currency="EUR")])
    assert body == "Elden Ring dropped in price (5.00 EUR). Open BAKLOG for details."


def test_several_drops_are_one_notification():
    alerts = [_drop("Elden Ring"), _drop("Hades"), _drop("Celeste"), _drop("Tunic")]
    [(title, body)] = dat.compose_notifications(alerts)
    assert title == "4 wishlist price drops"
    assert body == "Elden Ring, Hades, Celeste and 1 more. Open BAKLOG for details."


def test_single_claim_message():
    [(title, body)] = dat.compose_notifications([_claim(store="epic", ends_at="2026-10-01T15:00:00")])
    assert title == "New free game"
    assert body == "Astrea: Six Sided Oracles is free on Epic until Oct 1. Open BAKLOG to claim."


def test_both_kinds_prices_first():
    out = dat.compose_notifications([_claim(store="gog"), _drop(), _claim("Other")])
    assert [t for t, _ in out] == ["Wishlist price drop", "2 new free games"]


def test_limits_and_no_em_dashes():
    long = "X" * 400
    out = dat.compose_notifications([_drop(long, shop="S" * 100), _claim(long)])
    for title, body in out:
        assert len(title) <= dat.TITLE_MAX
        assert len(body) <= dat.BODY_MAX
        assert "\u2014" not in title + body


def test_unknown_kinds_ignored():
    assert dat.compose_notifications([{"id": "x", "kind": "other"}, "junk"]) == []


def test_snooze_is_for_today_only(tmp_path):
    today = date(2026, 9, 26)
    assert not dat.is_snoozed(tmp_path, today)
    dat.set_snoozed(tmp_path, True, today)
    assert dat.is_snoozed(tmp_path, today)
    assert not dat.is_snoozed(tmp_path, date(2026, 9, 27))
    dat.set_snoozed(tmp_path, False)
    assert not dat.is_snoozed(tmp_path, today)


@pytest.fixture
def tray_env(monkeypatch, tmp_path):
    calls: list[tuple[str, dict | None]] = []
    responses: dict[str, dict | None] = {}

    def fake_request(path, body=None):
        calls.append((path, body))
        return responses.get(path)

    monkeypatch.setattr(tray_app, "_deal_alerts_request", fake_request)
    monkeypatch.setattr(tray_app, "data_root", lambda: tmp_path)
    monkeypatch.setattr(tray_app, "_deal_alerts_enabled", False)
    return calls, responses, tmp_path


def test_cycle_notifies_once_and_acks(tray_env):
    calls, responses, _ = tray_env
    responses["/api/deal-alerts/pending"] = {"enabled": True, "alerts": [_drop(), _drop("Hades")]}
    icon = MagicMock()
    assert tray_app._deal_alerts_cycle(icon) == 2
    icon.notify.assert_called_once()
    assert calls[-1] == ("/api/deal-alerts/ack", {"ids": ["drop:Elden Ring", "drop:Hades"]})
    assert tray_app._deal_alerts_enabled is True


def test_cycle_acks_even_when_notify_fails(tray_env):
    calls, responses, _ = tray_env
    responses["/api/deal-alerts/pending"] = {"enabled": True, "alerts": [_claim()]}
    icon = MagicMock()
    icon.notify.side_effect = RuntimeError("no toasts")
    assert tray_app._deal_alerts_cycle(icon) == 1
    assert calls[-1][0] == "/api/deal-alerts/ack"


def test_cycle_disabled_or_empty_is_silent(tray_env):
    calls, responses, _ = tray_env
    icon = MagicMock()
    responses["/api/deal-alerts/pending"] = {"enabled": False, "alerts": [_drop()]}
    assert tray_app._deal_alerts_cycle(icon) == 0
    responses["/api/deal-alerts/pending"] = {"enabled": True, "alerts": []}
    assert tray_app._deal_alerts_cycle(icon) == 0
    icon.notify.assert_not_called()
    assert all(path != "/api/deal-alerts/ack" for path, _ in calls)


def test_cycle_server_error_is_silent(tray_env):
    _, responses, _ = tray_env
    responses["/api/deal-alerts/pending"] = None
    icon = MagicMock()
    assert tray_app._deal_alerts_cycle(icon) == 0
    icon.notify.assert_not_called()


def test_cycle_skipped_while_snoozed(tray_env):
    calls, responses, root = tray_env
    responses["/api/deal-alerts/pending"] = {"enabled": True, "alerts": [_drop()]}
    dat.set_snoozed(root, True)
    icon = MagicMock()
    assert tray_app._deal_alerts_cycle(icon) == 0
    assert calls == []
    icon.notify.assert_not_called()


def test_request_swallows_http_500(monkeypatch):
    import urllib.error

    def boom(*_a, **_k):
        raise urllib.error.HTTPError("u", 500, "err", {}, None)

    monkeypatch.setattr(tray_app.urllib.request, "urlopen", boom)
    assert tray_app._deal_alerts_request("/api/deal-alerts/pending") is None


def test_request_sends_local_header(monkeypatch):
    seen = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"enabled": false, "alerts": []}'

    def fake_urlopen(req, timeout=0):
        seen["headers"] = dict(req.header_items())
        seen["method"] = req.get_method()
        return _Resp()

    monkeypatch.setattr(tray_app.urllib.request, "urlopen", fake_urlopen)
    assert tray_app._deal_alerts_request("/api/deal-alerts/pending") == {"enabled": False, "alerts": []}
    assert seen["headers"].get("X-baklog-local") == "1"
    assert seen["method"] == "GET"


def test_loop_does_not_poll_when_not_frozen(monkeypatch):
    monkeypatch.setattr(tray_app, "is_frozen", lambda: False)
    polled = []
    monkeypatch.setattr(tray_app, "_deal_alerts_cycle", lambda icon: polled.append(icon))
    started = []

    class _Thread:
        def __init__(self, target, name, daemon):
            started.append(name)
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(tray_app.threading, "Thread", _Thread)
    tray_app._start_deal_alerts(MagicMock())
    assert started == ["tray-deal-alerts"]
    assert polled == []
