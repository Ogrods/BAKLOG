"""Tests for Steam store API retry behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from steam_client import SteamClient, _get_with_retry


def test_get_with_retry_succeeds_after_connection_errors() -> None:
    ok = MagicMock()
    ok.status_code = 200
    ok.raise_for_status = MagicMock()
    errors = [requests.ConnectionError("dns"), requests.ConnectionError("dns"), ok]
    with patch("steam_client.requests.get", side_effect=errors) as get:
        with patch("steam_client.time.sleep"):
            resp = _get_with_retry("https://store.steampowered.com/api/appdetails", {"appids": 1})
    assert resp is ok
    assert get.call_count == 3


def test_get_with_retry_raises_after_exhausted_retries() -> None:
    with patch("steam_client.requests.get", side_effect=requests.ConnectionError("dns")) as get:
        with patch("steam_client.time.sleep"):
            with pytest.raises(requests.ConnectionError):
                _get_with_retry(
                    "https://store.steampowered.com/api/appdetails",
                    {"appids": 1},
                    retries=2,
                )
    assert get.call_count == 2


def test_get_app_details_uses_retry(tmp_path) -> None:
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path)
    ok = MagicMock()
    ok.status_code = 200
    ok.json.return_value = {"70": {"success": True, "data": {"type": "game", "name": "Half-Life"}}}
    ok.raise_for_status = MagicMock()
    with patch("steam_client._get_with_retry", return_value=ok):
        result = client.get_app_details(70, refresh=True)
    assert result is not None
    assert result["success"] is True
    assert result["data"]["name"] == "Half-Life"
