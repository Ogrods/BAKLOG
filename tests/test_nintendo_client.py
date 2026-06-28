import json
from unittest.mock import MagicMock

import pytest

from clients.nintendo_client import (
    NintendoAuthError,
    NintendoCaptureError,
    NintendoClient,
    _drain_graphql_candidates,
    _map_graphql_item,
    probe_session_id_token,
)


def test_map_graphql_item_maps_switch_platform():
    row = _map_graphql_item(
        {
            "title": "Bleak Sword DX",
            "datetime": "2026-04-08T00:14:57-07:00",
            "transactionId": 52378618743,
            "labelPlatform": "HAC",
            "itemType": "APPLICATION",
            "transactionType": "PURCHASE",
        }
    )
    assert row["title"] == "Bleak Sword DX"
    assert row["date"] == "2026-04-08"
    assert row["transaction_id"] == "52378618743"
    assert row["device_type"] == "Nintendo Switch"
    assert row["content_type"] == "application"
    assert row["transaction_type"] == "purchase"


def test_cookie_only_without_profile_raises_helpful_auth_error():
    client = NintendoClient("session=abc", profile_path=None)
    with pytest.raises(NintendoAuthError, match="browser profile"):
        client.fetch_all_transactions()


def test_drain_graphql_candidates_parses_on_main_thread():
    sample_payload = {
        "data": {
            "account": {
                "transactionHistories": {
                    "transactionHistories": [
                        {
                            "title": "Iconoclasts",
                            "datetime": "2025-09-05T12:00:00-07:00",
                            "transactionId": 51988550814,
                            "labelPlatform": "HAC",
                            "itemType": "APPLICATION",
                            "transactionType": "PURCHASE",
                        }
                    ]
                }
            }
        }
    }

    class FakeResp:
        url = "https://wb.lp1.savanna.srv.nintendo.net/graphql?operationName=TransactionsClientRootClient"
        status = 200

        def text(self):
            return json.dumps(sample_payload)

    collected = []
    seen = set()
    candidates = [FakeResp()]
    added = _drain_graphql_candidates(candidates, collected, seen)
    assert added == 1
    assert collected[0]["title"] == "Iconoclasts"
    assert not candidates


def test_fetch_via_browser_queues_then_drains(monkeypatch, tmp_path):
    sample_payload = {
        "data": {
            "account": {
                "transactionHistories": {
                    "transactionHistories": [
                        {
                            "title": "Iconoclasts",
                            "datetime": "2025-09-05T12:00:00-07:00",
                            "transactionId": 51988550814,
                            "labelPlatform": "HAC",
                            "itemType": "APPLICATION",
                            "transactionType": "PURCHASE",
                        }
                    ]
                }
            }
        }
    }

    class FakeResp:
        url = "https://wb.lp1.savanna.srv.nintendo.net/graphql?operationName=TransactionsClientRootClient"
        status = 200

        def text(self):
            return json.dumps(sample_payload)

    class FakePage:
        def on(self, event, handler):
            if event == "response":
                handler(FakeResp())

        def goto(self, *_a, **_k):
            pass

        def content(self):
            return "Purchase History"

        def evaluate(self, _expr):
            return []

        @property
        def url(self):
            return "https://ec.nintendo.com/my/transactions/"

        def title(self):
            return "Transactions"

    class FakeRequest:
        def get(self, url, timeout=30):
            _ = (url, timeout)
            body = MagicMock()
            body.status = 200
            body.text = json.dumps({"idToken": "tok"})
            return body

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]
            self.request = FakeRequest()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

    def fake_launch(_path, *, headless=True):
        return FakeContext()

    monkeypatch.setattr("auth.cdp_browser.launch_persistent_profile", fake_launch)
    monkeypatch.setattr("clients.nintendo_client.time.sleep", lambda _s: None)
    profile = tmp_path / "nintendo"
    profile.mkdir()
    client = NintendoClient(profile_path=profile)
    rows = client.fetch_all_transactions()
    assert len(rows) == 1
    assert rows[0]["title"] == "Iconoclasts"


def test_empty_capture_raises_capture_error_not_auth(monkeypatch, tmp_path):

    class FakePage:
        def on(self, _event, _handler):
            pass

        def goto(self, *_a, **_k):
            pass

        def content(self):
            return "Purchase History"

        def evaluate(self, _expr):
            return []

        @property
        def url(self):
            return "https://ec.nintendo.com/my/transactions/"

        def title(self):
            return "Transactions"

    class FakeRequest:
        @staticmethod
        def get(url, timeout=30):
            _ = timeout
            body = MagicMock()
            if "session" in url:
                body.status = 200
                body.text = json.dumps({"idToken": "tok"})
            elif "graphql" in url:
                body.status = 200
                body.text = json.dumps({"data": {"account": {"transactionHistories": {"transactionHistories": []}}}})
            else:
                body.status = 404
                body.text = "{}"
            return body

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]
            self.request = FakeRequest()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            pass

    monkeypatch.setattr("auth.cdp_browser.launch_persistent_profile", lambda _p, *, headless=True: FakeContext())
    monkeypatch.setattr("clients.nintendo_client.time.sleep", lambda _s: None)
    profile = tmp_path / "nintendo"
    profile.mkdir()
    client = NintendoClient(profile_path=profile)
    with pytest.raises(NintendoCaptureError, match="--headed"):
        client.fetch_all_transactions()


def test_direct_graphql_continues_past_duplicate_page(monkeypatch):
    page_one = {
        "data": {
            "account": {
                "transactionHistories": {
                    "transactionHistories": [
                        {
                            "title": "Iconoclasts",
                            "datetime": "2025-09-05T12:00:00-07:00",
                            "transactionId": 51988550814,
                            "labelPlatform": "HAC",
                            "itemType": "APPLICATION",
                            "transactionType": "PURCHASE",
                        }
                    ]
                }
            }
        }
    }
    page_two = {
        "data": {
            "account": {
                "transactionHistories": {
                    "transactionHistories": [
                        {
                            "title": "Wargroove",
                            "datetime": "2025-08-01T12:00:00-07:00",
                            "transactionId": 51999999999,
                            "labelPlatform": "HAC",
                            "itemType": "APPLICATION",
                            "transactionType": "PURCHASE",
                        }
                    ]
                }
            }
        }
    }
    empty_page = {"data": {"account": {"transactionHistories": {"transactionHistories": []}}}}
    graphql_calls = {"n": 0}

    def fake_get(url, headers=None, timeout=30):
        _ = (headers, timeout)
        body = MagicMock()
        if "session" in url:
            body.status = 200
            body.text = lambda: json.dumps({"idToken": "tok"})
            return body
        if "graphql" in url:
            graphql_calls["n"] += 1
            body.status = 200
            if graphql_calls["n"] == 1:
                body.text = lambda: json.dumps(page_one)
            elif graphql_calls["n"] == 2:
                body.text = lambda: json.dumps(page_two)
            else:
                body.text = lambda: json.dumps(empty_page)
            return body
        body.status = 404
        body.text = lambda: "{}"
        return body

    collected = list(page_one["data"]["account"]["transactionHistories"]["transactionHistories"])
    seen_ids = {"51988550814"}
    monkeypatch.setattr("clients.nintendo_client.time.sleep", lambda _s: None)
    client = NintendoClient()
    context = MagicMock()
    context.request.get = fake_get
    added = client._fetch_via_direct_graphql(context, collected, seen_ids)
    assert added == 1
    assert len(collected) == 2
    assert collected[1]["title"] == "Wargroove"
    assert graphql_calls["n"] == 3


def test_probe_session_id_token():

    def fake_get(url, timeout=30):
        _ = timeout
        resp = MagicMock()
        if "session" in url:
            resp.status = 200
            resp.text = json.dumps({"idToken": "abc"})
        else:
            resp.status = 404
            resp.text = "{}"
        return resp

    out = probe_session_id_token(fake_get)
    assert out["ok"] is True
    assert out["id_token_present"] is True
