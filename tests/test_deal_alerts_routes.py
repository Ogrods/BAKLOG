"""GET /api/deal-alerts/pending and POST /api/deal-alerts/ack (tray, no bearer)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

import server
import shared.deal_alerts as da

NOW = datetime.now(UTC)


@pytest.fixture()
def alerts_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "deal_alerts.json"
    monkeypatch.setattr(da, "state_path", lambda profile_id=None: state)
    monkeypatch.setattr(da, "itad_path", lambda profile_id=None: tmp_path / "itad_prices.json")
    monkeypatch.setattr(da, "free_claims_path", lambda profile_id=None: tmp_path / "free_claims.json")
    monkeypatch.setattr("shared.pro_settings.read_pro_settings", lambda **_k: {"dealAlertsEnabled": True})
    # Pro via local BAKLOG_ADMIN Pro-sim, through the real is_pro_background().
    monkeypatch.setattr("shared.entitlement._admin_enabled", lambda: True)
    # Hosted auth on: the tray has no bearer, so these routes must not need one.
    monkeypatch.setattr("shared.supabase_auth.auth_enabled", lambda: True)
    doc = da.empty_state()
    doc["pending"] = [
        {"id": "drop:wishlist:1:500", "kind": "price_drop", "title": "A", "created_at": da._iso(NOW)},
        {"id": "drop:wishlist:2:500", "kind": "price_drop", "title": "B", "created_at": da._iso(NOW)},
    ]
    da.save_state(doc)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(server.Handler, directory=str(server.ROOT)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def _call(base, path, *, method="GET", local=True, host=None, body=None):
    headers = {}
    if local:
        headers[server._BAKLOG_LOCAL_HEADER] = "1"
    if host:
        headers["Host"] = host
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base}{path}", method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}


def test_pending_returns_alerts_without_bearer(alerts_server):
    status, body = _call(alerts_server, "/api/deal-alerts/pending")
    assert status == 200, body
    assert body["enabled"] is True
    assert [a["id"] for a in body["alerts"]] == ["drop:wishlist:1:500", "drop:wishlist:2:500"]


def test_pending_rejects_missing_local_header(alerts_server):
    status, _ = _call(alerts_server, "/api/deal-alerts/pending", local=False)
    assert status == 403


def test_pending_rejects_non_local_host(alerts_server):
    status, _ = _call(alerts_server, "/api/deal-alerts/pending", host="evil.example")
    assert status == 403


def test_ack_rejects_missing_local_header(alerts_server):
    status, _ = _call(alerts_server, "/api/deal-alerts/ack", method="POST", local=False, body={"ids": ["x"]})
    assert status == 403


def test_free_plan_gets_enabled_false(alerts_server, monkeypatch):
    monkeypatch.setattr("shared.entitlement.is_pro_background", lambda: False)
    status, body = _call(alerts_server, "/api/deal-alerts/pending")
    assert status == 200
    assert body == {"enabled": False, "alerts": []}


def test_opt_in_off_gets_enabled_false(alerts_server, monkeypatch):
    monkeypatch.setattr("shared.pro_settings.read_pro_settings", lambda **_k: {"dealAlertsEnabled": False})
    status, body = _call(alerts_server, "/api/deal-alerts/pending")
    assert body == {"enabled": False, "alerts": []}


def test_hosted_auth_without_recent_pro_plan_is_disabled(alerts_server, monkeypatch):
    import shared.entitlement as ent

    monkeypatch.setattr(ent, "_admin_enabled", lambda: False)
    monkeypatch.setattr(ent, "_auth_enabled", lambda: True)
    monkeypatch.setattr(ent, "_LAST_AUTH_PLAN", None)
    _, body = _call(alerts_server, "/api/deal-alerts/pending")
    assert body["enabled"] is False


def test_ack_empties_pending(alerts_server):
    status, body = _call(
        alerts_server, "/api/deal-alerts/ack", method="POST", body={"ids": ["drop:wishlist:1:500"]}
    )
    assert status == 200, body
    assert body == {"acked": 1}
    _, body = _call(alerts_server, "/api/deal-alerts/pending")
    assert [a["id"] for a in body["alerts"]] == ["drop:wishlist:2:500"]


@pytest.mark.parametrize("payload", [{"ids": "x"}, {"ids": [1]}, ["x"], {}])
def test_ack_validates_body(alerts_server, payload):
    status, _ = _call(alerts_server, "/api/deal-alerts/ack", method="POST", body=payload)
    assert status == 400
