"""Tests for enrich_cross_store_images.py (Steam CDN covers for non-Steam rows)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import enrich_cross_store_images as enrich

from shared.steam_match import normalize_title

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


def test_needs_lowres_upgrade_true_for_native_store_art() -> None:
    g = {
        "header_image": "https://images-eds-ssl.xboxlive.com/image/foo",
        "library_image": "https://images-eds-ssl.xboxlive.com/image/bar",
    }
    assert enrich.needs_lowres_upgrade(g) is True


def test_needs_lowres_upgrade_false_for_steamstatic() -> None:
    g = {
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg",
        "library_image": "https://cdn.akamai.steamstatic.com/steam/apps/1/library_600x900_2x.jpg",
        "image_source": "steam_search",
    }
    assert enrich.needs_lowres_upgrade(g) is False


def test_should_process_upgrade_only_when_flag_set() -> None:
    g = {
        "header_image": "https://images-eds-ssl.xboxlive.com/image/foo",
        "library_image": "https://images-eds-ssl.xboxlive.com/image/bar",
    }
    assert enrich.should_process(g, upgrade_lowres=False) is False
    assert enrich.should_process(g, upgrade_lowres=True) is True


def test_normalize_strips_trademark_symbols() -> None:
    assert normalize_title("Armatus™") == "armatus"


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


NATIVE_ROW = {
    "store": "xbox",
    "id": "xbox-native-1",
    "name": "Native Capsule Game",
    "header_image": "https://images-eds-ssl.xboxlive.com/image/small-capsule",
    "library_image": "https://images-eds-ssl.xboxlive.com/image/small-cover",
}


def test_upgrade_lowres_skipped_without_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xbox_path = tmp_path / "games_xbox.json"
    xbox_path.write_text(json.dumps({"games": [dict(NATIVE_ROW)]}, indent=2), encoding="utf-8")
    meta_path = tmp_path / "cross_store_images_meta.json"
    searches: list[str] = []

    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_xbox.json":
            return xbox_path
        return tmp_path / f"missing-{rel.name}"

    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(enrich, "write_catalog_text", lambda rel, text: xbox_path.write_text(text, encoding="utf-8"))
    monkeypatch.setattr(enrich, "meta_file", lambda: meta_path)
    monkeypatch.setattr(enrich, "steam_search_appid", lambda name: searches.append(name) or 99)
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["enrich_cross_store_images.py"])

    enrich.main()

    assert searches == []
    row = json.loads(xbox_path.read_text(encoding="utf-8"))["games"][0]
    assert row["header_image"] == NATIVE_ROW["header_image"]


def test_upgrade_lowres_replaces_native_art(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xbox_path = tmp_path / "games_xbox.json"
    xbox_path.write_text(json.dumps({"games": [dict(NATIVE_ROW)]}, indent=2), encoding="utf-8")
    meta_path = tmp_path / "cross_store_images_meta.json"

    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_xbox.json":
            return xbox_path
        return tmp_path / f"missing-{rel.name}"

    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(enrich, "write_catalog_text", lambda rel, text: xbox_path.write_text(text, encoding="utf-8"))
    monkeypatch.setattr(enrich, "meta_file", lambda: meta_path)
    monkeypatch.setattr(enrich, "steam_search_appid", lambda name: 4242 if name == "Native Capsule Game" else None)
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["enrich_cross_store_images.py", "--upgrade-lowres"])

    enrich.main()

    row = json.loads(xbox_path.read_text(encoding="utf-8"))["games"][0]
    assert row["steam_appid"] == 4242
    assert "4242" in row["header_image"]
    assert "steamstatic.com" in row["library_image"]
    assert row["image_source"] == "steam_search_upgrade"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "xbox:xbox-native-1" in meta["lowres_checked"]


def test_upgrade_lowres_skips_cached_checked_rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    xbox_path = tmp_path / "games_xbox.json"
    xbox_path.write_text(json.dumps({"games": [dict(NATIVE_ROW)]}, indent=2), encoding="utf-8")
    meta_path = tmp_path / "cross_store_images_meta.json"
    meta_path.write_text(
        json.dumps({"lowres_checked": ["xbox:xbox-native-1"], "no_steam_match": []}, indent=2),
        encoding="utf-8",
    )
    searches: list[str] = []

    def fake_catalog(rel: Path) -> Path:
        if rel.name == "games_xbox.json":
            return xbox_path
        return tmp_path / f"missing-{rel.name}"

    monkeypatch.setattr(enrich, "catalog_file", fake_catalog)
    monkeypatch.setattr(enrich, "write_catalog_text", lambda rel, text: xbox_path.write_text(text, encoding="utf-8"))
    monkeypatch.setattr(enrich, "meta_file", lambda: meta_path)
    monkeypatch.setattr(enrich, "steam_search_appid", lambda name: searches.append(name) or 4242)
    monkeypatch.setattr(enrich.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["enrich_cross_store_images.py", "--upgrade-lowres"])

    enrich.main()

    assert searches == []
