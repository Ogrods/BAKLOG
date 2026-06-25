"""Steam store batch appdetails client tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from clients.steam_client import APP_DETAILS_BATCH_SIZE, SteamClient


@pytest.fixture()
def steam_client(tmp_path: Path) -> SteamClient:
    return SteamClient("key", "76561198000000000", cache_dir=tmp_path / "steam")


def test_get_app_details_batch_chunks_and_caches(steam_client: SteamClient) -> None:
    appids = list(range(1, APP_DETAILS_BATCH_SIZE + 5))
    calls: list[str] = []

    def fake_get(url, params, **kwargs):
        calls.append(str(params.get("appids")))
        raw = {}
        for part in str(params["appids"]).split(","):
            aid = int(part)
            raw[str(aid)] = {"success": True, "data": {"name": f"Game {aid}", "type": "game"}}
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = raw
        resp.raise_for_status = MagicMock()
        return resp

    with patch("clients.steam_client._get_with_retry", side_effect=fake_get):
        with patch.object(steam_client, "_throttle_store"):
            out = steam_client.get_app_details_batch(appids)

    assert len(out) == len(appids)
    assert out[1]["data"]["name"] == "Game 1"
    assert len(calls) == 2
    assert len(calls[0].split(",")) == APP_DETAILS_BATCH_SIZE
    cache_path = steam_client._cache_path("appdetails", "42")
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["success"] is True


def test_get_app_details_batch_uses_cache(steam_client: SteamClient) -> None:
    steam_client._write_cache("appdetails", "7", {"success": True, "data": {"name": "Cached"}})
    with patch("clients.steam_client._get_with_retry") as mock_get:
        out = steam_client.get_app_details_batch([7])
    mock_get.assert_not_called()
    assert out[7]["data"]["name"] == "Cached"
