"""Tests for enrich_cross_store_images.py (Steam CDN covers for non-Steam rows)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import enrich_cross_store_images as enrich


ARMATUS_ROW = {
    "store": "wishlist",
    "wishlist_store": "xbox",
    "id": "xbox-9NQPJ4M6SMDF",
    "xbox_product_id": "9NQPJ4M6SMDF",
    "name": "Armatus",
    "header_image": None,
    "library_image": None,
}


def test_needs_images_true_when_both_missing() -> None:
    assert enrich.needs_images({"header_image": None, "library_image": None}) is True


def test_needs_images_true_for_eprt_placeholder() -> None:
    assert enrich.needs_images({"header_image": "x.eprt", "library_image": ""}) is True


def test_needs_images_false_when_urls_present() -> None:
    g = {
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg",
        "library_image": "https://cdn.akamai.steamstatic.com/steam/apps/1/library_600x900_2x.jpg",
    }
    assert enrich.needs_images(g) is False


def test_normalize_strips_trademark_symbols() -> None:
    assert enrich.normalize("Armatus™") == "armatus"


def test_store_files_includes_wishlist_xbox_and_itch() -> None:
    names = {row[0].name for row in enrich.STORE_FILES}
    assert "games_wishlist_xbox.json" in names
    assert "games_itch.json" in names
    assert "games_wishlist_gog.json" in names


def test_steam_search_appid_exact_name_match(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResp:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"items": [{"id": 3660710, "name": "Armatus"}]}

    monkeypatch.setattr(enrich.requests, "get", lambda *a, **k: FakeResp())
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    assert enrich.steam_search_appid("Armatus") == 3660710


def test_enriches_armatus_wishlist_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    wishlist_path = tmp_path / "games_wishlist_xbox.json"
    wishlist_path.write_text(
        json.dumps({"games": [dict(ARMATUS_ROW)]}, indent=2),
        encoding="utf-8",
    )
    meta_path = tmp_path / "cross_store_images_meta.json"

    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_wishlist_xbox.json":
            return wishlist_path
        return tmp_path / f"missing-{rel.name}"

    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(
        enrich,
        "write_catalog_text",
        lambda rel, text: wishlist_path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(enrich, "meta_file", lambda: meta_path)
    monkeypatch.setattr(enrich, "steam_search_appid", lambda name: 3660710 if name == "Armatus" else None)
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["enrich_cross_store_images.py"])

    enrich.main()

    data = json.loads(wishlist_path.read_text(encoding="utf-8"))
    row = data["games"][0]
    assert row["steam_appid"] == 3660710
    assert "3660710" in row["header_image"]
    assert "3660710" in row["library_image"]
    assert row["image_source"] == "steam_search"


def test_itch_non_game_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    itch_path = tmp_path / "games_itch.json"
    itch_path.write_text(
        json.dumps(
            {
                "games": [
                    {
                        "id": "tool-1",
                        "name": "Map Editor",
                        "classification": "tool",
                        "header_image": None,
                        "library_image": None,
                    },
                    {
                        "id": "game-1",
                        "name": "Indie Game",
                        "classification": "game",
                        "header_image": None,
                        "library_image": None,
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    meta_path = tmp_path / "cross_store_images_meta.json"
    searches: list[str] = []

    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_itch.json":
            return itch_path
        return tmp_path / f"missing-{rel.name}"

    def fake_search(name: str) -> int:
        searches.append(name)
        return 42

    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(
        enrich,
        "write_catalog_text",
        lambda rel, text: itch_path.write_text(text, encoding="utf-8"),
    )
    monkeypatch.setattr(enrich, "meta_file", lambda: meta_path)
    monkeypatch.setattr(enrich, "steam_search_appid", fake_search)
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["enrich_cross_store_images.py"])

    enrich.main()

    assert searches == ["Indie Game"]
    data = json.loads(itch_path.read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in data["games"]}
    assert "header_image" not in by_id["tool-1"] or by_id["tool-1"].get("header_image") is None
    assert "42" in by_id["game-1"]["header_image"]
