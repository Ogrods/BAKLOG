"""steam_appid persistence from Steam review enrichment."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import enrichers.enrich_steam_reviews as enrich


def _install_catalog_fakes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, gog_path: Path, map_path: Path
) -> None:
    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_gog.json":
            return gog_path
        if rel.name == "games_steam.json":
            return tmp_path / "games_steam.json"
        return tmp_path / f"missing-{rel.name}"

    (tmp_path / "games_steam.json").write_text(
        json.dumps({"games": []}, indent=2), encoding="utf-8"
    )
    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(
        enrich, "write_catalog_text", lambda rel, text: gog_path.write_text(text, encoding="utf-8")
    )
    monkeypatch.setattr(enrich, "mapping_file", lambda: map_path)
    monkeypatch.setattr(enrich, "steam_appids_by_id", lambda: set())
    monkeypatch.setattr(enrich, "resolve_env", lambda *a, **k: "")
    monkeypatch.setattr(enrich, "load_dotenv", lambda: None)
    monkeypatch.setattr(sys, "argv", ["enrich_steam_reviews.py", "--stores", "gog"])


def test_reviews_enrich_writes_steam_appid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gog_path = tmp_path / "games_gog.json"
    gog_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "id": "1207659013",
                        "name": "Treasure Adventure Game",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    map_path = tmp_path / "steam_review_map.json"
    map_path.write_text(json.dumps({"gog:1207659013": 863940}, indent=2), encoding="utf-8")
    _install_catalog_fakes(monkeypatch, tmp_path, gog_path, map_path)

    class FakeSteam:
        def get_review_summary(self, appid: int, refresh: bool = False) -> dict:
            assert appid == 863940
            return {
                "percent_positive": 88.7,
                "total_reviews": 53,
                "review_score_desc": "Very Positive",
            }

    with patch.object(enrich, "SteamClient", lambda **k: FakeSteam()):
        rc = enrich.main()
    assert rc == 0
    row = json.loads(gog_path.read_text(encoding="utf-8"))["games"][0]
    assert row["steam_appid"] == 863940
    assert row["steam_review_percent"] == 88.7


def test_reviews_enrich_backfills_appid_when_reviews_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gog_path = tmp_path / "games_gog.json"
    gog_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "id": "1207659013",
                        "name": "Treasure Adventure Game",
                        "steam_review_percent": 88.7,
                        "steam_review_count": 53,
                        "steam_review_desc": "Very Positive",
                    }
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    map_path = tmp_path / "steam_review_map.json"
    map_path.write_text(json.dumps({"gog:1207659013": 863940}, indent=2), encoding="utf-8")
    _install_catalog_fakes(monkeypatch, tmp_path, gog_path, map_path)

    class FakeSteam:
        def get_review_summary(self, appid: int, refresh: bool = False) -> dict:
            raise AssertionError("should not fetch reviews when already present")

    with patch.object(enrich, "SteamClient", lambda **k: FakeSteam()):
        rc = enrich.main()
    assert rc == 0
    row = json.loads(gog_path.read_text(encoding="utf-8"))["games"][0]
    assert row["steam_appid"] == 863940
