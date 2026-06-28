"""Tests for itch_client.py (no network)."""

from __future__ import annotations

import pytest

from clients.itch_client import ItchAuthError, ItchClient


def test_init_requires_api_key() -> None:
    with pytest.raises(ItchAuthError, match="ITCH_API_KEY"):
        ItchClient("")


def test_init_strips_key() -> None:
    client = ItchClient("  abc123  ")
    assert client.api_key == "abc123"
