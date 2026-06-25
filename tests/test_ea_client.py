"""Tests for EaClient cookie and bearer modes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clients.ea_client import EaAuthError, EaClient, OWNED_GAMES_HASH, USER_SUBSCRIPTION_HASH

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_cookie_mode_posts_subscription_apq_probe(monkeypatch) -> None:
    calls: list[dict] = []

    class Resp:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"data": {"me": {"subscription": {"active": False}}}}

    def fake_post(url, json=None, timeout=60):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return Resp()

    session = MagicMock()
    session.post = fake_post
    session.headers = {}
    session.cookies = MagicMock()

    client = EaClient(cookies={"remid": "abc"})
    client.session = session
    client.probe_user_subscription()

    assert len(calls) == 1
    assert calls[0]["json"]["operationName"] == "GetUserSubscription"
    assert (
        calls[0]["json"]["extensions"]["persistedQuery"]["sha256Hash"]
        == USER_SUBSCRIPTION_HASH
    )
    assert "Authorization" not in session.headers


def test_bearer_mode_requires_token_without_cookies() -> None:
    try:
        EaClient("")
        raised = False
    except EaAuthError:
        raised = True
    assert raised


def test_cookie_mode_raises_on_unauthenticated(monkeypatch) -> None:
    class Resp:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {
                "data": None,
                "errors": [
                    {
                        "message": "Not authenticated.",
                        "extensions": {"code": "UNAUTHENTICATED"},
                    }
                ],
            }

    session = MagicMock()
    session.post = lambda *a, **k: Resp()
    session.headers = {}
    session.cookies = MagicMock()

    client = EaClient(cookies={"remid": "bad"})
    client.session = session
    try:
        client.probe_user_subscription()
        raised = False
    except EaAuthError as exc:
        raised = "not authenticated" in str(exc).lower()
    assert raised


def test_get_owned_games_falls_back_when_apq_hash_stale() -> None:
    owned_fixture = _load_fixture("ea_graphql_owned_items.json")
    not_found = _load_fixture("ea_graphql_persisted_query_not_found.json")
    calls: list[dict] = []

    class Resp:
        def __init__(self, payload: dict, *, status: int = 200) -> None:
            self.status_code = status
            self._payload = payload

        def json(self) -> dict:
            return self._payload

        @property
        def text(self) -> str:
            return json.dumps(self._payload)

    def fake_post(url, json=None, timeout=60):
        body = json or {}
        op = body.get("operationName") or ""
        calls.append({"op": op, "has_query": "query" in body})
        if op == "getPreloadedOwnedGames" and "query" not in body:
            return Resp(not_found, status=400)
        if op == "getPreloadedOwnedGames" and "query" in body:
            assert body.get("variables", {}).get("limit") == 500
            assert body.get("variables", {}).get("next") == "0"
            return Resp(owned_fixture)
        raise AssertionError(f"unexpected post {op}")

    session = MagicMock()
    session.post = fake_post
    session.headers = {}
    session.cookies = MagicMock()

    client = EaClient(cookies={"remid": "abc"})
    client.session = session
    items = client.get_owned_games()

    assert [c["op"] for c in calls] == [
        "getPreloadedOwnedGames",
        "getPreloadedOwnedGames",
    ]
    assert calls[0]["has_query"] is False
    assert calls[1]["has_query"] is True
    assert len(items) >= 1
    assert items[0].get("product", {}).get("name")
