"""Pre-release smoke: live store contracts + client behavior that must not regress.

Run before tagging (also in release.yml and test-all.ps1 -Full):

    python -m pytest -q -m release_smoke
"""

from __future__ import annotations

import pytest
import requests

from clients.steam_client import SteamClient


@pytest.mark.release_smoke
def test_steam_store_api_rejects_csv_appids() -> None:
    """Steam store /api/appdetails returns 400 for comma-separated appids."""
    single = requests.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": 70, "l": "english"},
        timeout=15,
    )
    batch = requests.get(
        "https://store.steampowered.com/api/appdetails",
        params={"appids": "70,220,240", "l": "english"},
        timeout=15,
    )
    assert single.status_code == 200, "single-appid probe failed (network or Steam outage)"
    assert batch.status_code == 400, (
        "Steam accepted CSV appids — get_app_details_batch must not batch HTTP calls"
    )


@pytest.mark.release_smoke
def test_steam_get_app_details_batch_one_call_per_appid(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: batch helper must delegate once per appid, not one CSV HTTP call."""
    client = SteamClient("key", "76561198000000000", cache_dir=tmp_path / "steam")
    calls: list[int] = []

    def spy_get_app_details(self, appid: int, refresh: bool = False):
        calls.append(appid)
        return {"success": True, "data": {"name": "Probe"}}

    monkeypatch.setattr(SteamClient, "get_app_details", spy_get_app_details)

    out = client.get_app_details_batch([70, 220, 240], refresh=True)

    assert len(out) == 3
    assert calls == [70, 220, 240]
