import pytest

from clients.itch_client import ItchAuthError, ItchClient


def test_init_requires_api_key():
    with pytest.raises(ItchAuthError, match="ITCH_API_KEY"):
        ItchClient("")


def test_init_strips_key():
    client = ItchClient("  abc123  ")
    assert client.api_key == "abc123"
