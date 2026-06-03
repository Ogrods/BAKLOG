"""Tests for NintendoClient error classification and GraphQL mapping."""
from __future__ import annotations

import json

import pytest

from nintendo_client import NintendoAuthError, NintendoClient, _map_graphql_item


def test_map_graphql_item_maps_switch_platform() -> None:
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


def test_cookie_only_without_profile_raises_helpful_auth_error() -> None:
    client = NintendoClient("session=abc", profile_path=None)
    with pytest.raises(NintendoAuthError, match="browser profile"):
        client.fetch_all_transactions()


def test_fetch_via_browser_parses_graphql_responses(monkeypatch, tmp_path) -> None:
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
        url = (
            "https://wb.lp1.savanna.srv.nintendo.net/graphql"
            "?operationName=TransactionsClientRootClient"
        )
        status = 200

        @staticmethod
        def text() -> str:
            return json.dumps(sample_payload)

    class FakePage:
        _handler = None

        def on(self, event, handler) -> None:
            if event == "response":
                self._handler = handler
                handler(FakeResp())

        def goto(self, *_a, **_k) -> None:
            pass

        def content(self) -> str:
            return "Purchase History"

        def evaluate(self, _expr) -> list:
            return []

    class FakeContext:
        def __init__(self) -> None:
            self.pages = [FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> None:
            pass

    def fake_launch(_path, *, headless=True):
        return FakeContext()

    monkeypatch.setattr(
        "auth.cdp_browser.launch_persistent_profile", fake_launch
    )
    monkeypatch.setattr("nintendo_client.time.sleep", lambda _s: None)
    profile = tmp_path / "nintendo"
    profile.mkdir()
    client = NintendoClient(profile_path=profile)
    rows = client.fetch_all_transactions()
    assert len(rows) == 1
    assert rows[0]["title"] == "Iconoclasts"
