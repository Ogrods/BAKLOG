"""Tests for itch_client.py (no network)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clients.itch_client import ItchApiError, ItchAuthError, ItchClient


def test_init_requires_api_key() -> None:
    with pytest.raises(ItchAuthError, match="ITCH_API_KEY"):
        ItchClient("")


def test_init_strips_key() -> None:
    client = ItchClient("  abc123  ")
    assert client.api_key == "abc123"


def test_get_sanitizes_html_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ItchClient("key")
    html = "<!doctype html><html><title>Just a moment...</title><body>cf</body></html>"
    bad = SimpleNamespace(
        status_code=502,
        text=html,
        headers={"Content-Type": "text/html"},
        json=MagicMock(side_effect=ValueError("no json")),
    )
    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr(client.session, "get", lambda *a, **k: bad)
    # 502 retries once; both attempts return HTML so the final raise is sanitized.
    monkeypatch.setattr("clients.itch_client.time.sleep", lambda *_: None)
    with pytest.raises(ItchApiError, match="HTML error page from host"):
        client._get("me")


def test_get_retries_once_on_429(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ItchClient("key")
    calls: list[int] = []

    def fake_get(*_a, **_k):
        calls.append(1)
        if len(calls) == 1:
            return SimpleNamespace(
                status_code=429,
                text="slow down",
                headers={"Content-Type": "text/plain"},
            )
        return SimpleNamespace(
            status_code=200,
            text='{"user":{"id":1}}',
            headers={"Content-Type": "application/json"},
            json=lambda: {"user": {"id": 1}},
        )

    monkeypatch.setattr(client, "_throttle", lambda: None)
    monkeypatch.setattr(client.session, "get", fake_get)
    monkeypatch.setattr("clients.itch_client.time.sleep", lambda *_: None)
    assert client._get("me") == {"user": {"id": 1}}
    assert len(calls) == 2
