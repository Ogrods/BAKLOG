"""Tests for fetch_games resilience and credential messaging."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

import fetchers.fetch_games as fetch_games
from fetchers._base import STEAM_CREDENTIALS_HINT


def test_fetch_games_prefetch_uses_heartbeat_guard() -> None:
    """Regression: silent store-metadata prefetch must not trip the 180s stall watchdog."""
    src = Path(fetch_games.__file__).read_text(encoding="utf-8")
    assert "Prefetching store metadata" in src
    assert "HeartbeatTimer" in src
    assert "run_with_heartbeat" in src


def test_missing_credentials_message_mentions_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch_games, "resolve_env", lambda key, **_: "")
    with patch.object(fetch_games, "load_dotenv"):
        with patch.object(fetch_games.sys, "argv", ["fetchers/fetch_games.py", "--skip-hltb"]):
            code = fetch_games.main()
    assert code == 1
    assert "Connections" in STEAM_CREDENTIALS_HINT
    assert ".env" not in STEAM_CREDENTIALS_HINT


def test_fetch_store_data_falls_back_to_cached_reviews() -> None:
    steam = MagicMock()
    steam.get_app_details.side_effect = requests.ConnectionError("dns")
    cached = {
        "steam_review_percent": 95.0,
        "steam_review_count": 1000,
        "steam_review_desc": "Very Positive",
    }
    details, reviews = fetch_games._fetch_store_data(
        steam, 323580, refresh=False, cached_row=cached
    )
    assert details is None
    assert reviews["percent_positive"] == 95.0
    assert reviews["total_reviews"] == 1000


def test_main_survives_store_error_with_cached_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog = tmp_path / "games_steam.json"
    cached_game = {
        "appid": 70,
        "name": "Half-Life",
        "store": "steam",
        "id": 70,
        "type": "game",
        "genres": ["Action"],
        "tags": [],
        "playtime_minutes": 100,
        "last_played": None,
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/70/header.jpg",
        "library_image": "https://cdn.akamai.steamstatic.com/steam/apps/70/library_600x900.jpg",
        "steam_review_percent": 98.0,
        "steam_review_count": 50000,
        "steam_review_desc": "Overwhelmingly Positive",
    }
    catalog.write_text(
        json.dumps({"games": [cached_game], "game_count": 1}),
        encoding="utf-8",
    )

    def _resolve_env(key, **_):
        return "x" if key == "STEAM_API_KEY" else "76561198000000000"

    monkeypatch.setattr(fetch_games, "resolve_env", _resolve_env)
    monkeypatch.setattr(
        fetch_games,
        "catalog_file",
        lambda p: catalog if p == fetch_games.GAMES_STEAM_JSON else tmp_path / p,
    )

    def _write_catalog(_p, text):
        catalog.write_text(text, encoding="utf-8")
        return catalog

    monkeypatch.setattr(fetch_games, "write_catalog_text", _write_catalog)

    steam = MagicMock()
    steam.get_owned_games.return_value = [
        {"appid": 70, "name": "Half-Life", "playtime_forever": 200},
    ]
    steam.get_app_details.side_effect = requests.ConnectionError("dns")
    steam.get_review_summary.side_effect = requests.ConnectionError("dns")

    with patch.object(fetch_games, "load_dotenv"):
        with patch.object(fetch_games, "SteamClient", return_value=steam):
            with patch.object(fetch_games, "HltbClient"):
                with patch.object(
                    fetch_games.sys,
                    "argv",
                    ["fetchers.fetch_games.py", "--skip-hltb", "--allow-empty", "--allow-drift"],
                ):
                    code = fetch_games.main()

    assert code == 0
    out = json.loads(catalog.read_text(encoding="utf-8"))
    assert len(out["games"]) == 1
    assert out["games"][0]["playtime_minutes"] == 200
