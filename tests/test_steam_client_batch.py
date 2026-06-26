"""Steam store batch appdetails client tests."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from clients.steam_client import SteamClient


@pytest.fixture()
def steam_client(tmp_path: Path) -> SteamClient:
    return SteamClient("key", "76561198000000000", cache_dir=tmp_path / "steam")


def test_get_app_details_batch_fetches_each_appid(
    steam_client: SteamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    appids = [1, 2, 3, 4, 5]
    calls: list[int] = []

    def fake_get_app_details(self, appid: int, refresh: bool = False):
        calls.append(appid)
        return {"success": True, "data": {"name": f"Game {appid}", "type": "game"}}

    monkeypatch.setattr(SteamClient, "get_app_details", fake_get_app_details)
    out = steam_client.get_app_details_batch(appids)

    assert len(out) == len(appids)
    assert out[1]["data"]["name"] == "Game 1"
    assert calls == appids


def test_get_app_details_batch_uses_cache(steam_client: SteamClient) -> None:
    steam_client._write_cache("appdetails", "7", {"success": True, "data": {"name": "Cached"}})
    with patch.object(steam_client, "get_app_details") as mock_get:
        out = steam_client.get_app_details_batch([7])
    mock_get.assert_not_called()
    assert out[7]["data"]["name"] == "Cached"
