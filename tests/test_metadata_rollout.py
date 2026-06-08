"""Tests for metadata enrichment rollout phases 3–7."""

from __future__ import annotations

import argparse

import fetch_ea as fe
import fetch_gog as fg
import fetch_itch as fi
import fetch_nintendo as fn
import fetch_xbox as fx
from fetch_epic import _acquired_at_from_record, _build_game_row_from_record


class TestGamePassRows:
    def test_xbox_sets_game_pass_flag(self) -> None:
        row = fx._build_row(
            {
                "titleId": "abc",
                "name": "Halo",
                "gamePass": {"isGamePass": True},
            },
            None,
        )
        assert row["game_pass"] is True
        assert "game-pass" in row["tags"]

    def test_ea_normalizes_game_pass_tag(self) -> None:
        item = {
            "originOfferId": "offer-1",
            "product": {
                "name": "GP Title",
                "id": "p1",
                "gameProductUser": {"ownershipMethods": ["XGP_VAULT"]},
            },
        }
        tags = fe._tags_for(item)
        assert tags == ["game-pass"]
        row = fe._build_row(item, hltb=None, play_by_slug={})
        assert row["game_pass"] is True


class TestGogNeedsDetails:
    def test_empty_genres_cached_row_triggers_details(self) -> None:
        args = argparse.Namespace(refresh=False, gog_id=None)
        cached = {"genres": [], "name": "GOG Exclusive"}
        assert fg._needs_product_details(args, cached) is True

    def test_populated_genres_skips_details(self) -> None:
        args = argparse.Namespace(refresh=False, gog_id=None)
        cached = {"genres": ["RPG"], "name": "Has Genres"}
        assert fg._needs_product_details(args, cached) is False


class TestNintendoPlatform:
    def test_build_row_persists_device_type(self) -> None:
        row = fn._build_row(
            {
                "id": "tx-1",
                "name": "Zelda",
                "device_type": "HAC",
                "tags": [],
            },
            None,
        )
        assert row["nintendo_platform"] == "HAC"


class TestItchEnrichDetails:
    def test_enrich_merges_description_and_tags(self) -> None:
        row = {
            "store": "itch",
            "id": 99,
            "genres": ["shooter"],
            "short_text": "old",
        }
        doc = {
            "description": "Full description body",
            "tags": ["platformer", "shooter"],
        }
        out = fi._enrich_row_from_game_doc(row, doc)
        assert out["short_text"] == "Full description body"
        assert set(out["genres"]) == {"shooter", "platformer"}


class TestEpicAcquiredAt:
    def test_acquired_at_from_record(self) -> None:
        rec = {"acquisitionDate": "2024-05-01T12:00:00.000Z"}
        assert _acquired_at_from_record(rec) == "2024-05-01T12:00:00.000Z"

    def test_build_row_from_record_keeps_release_date_separate(self) -> None:
        rec = {
            "namespace": "fn",
            "catalogItemId": "item-1",
            "sandboxName": "Fallback Game",
            "acquisitionDate": "2023-01-15T00:00:00.000Z",
        }
        row = _build_game_row_from_record(rec, None, None)
        assert row is not None
        assert row["acquired_at"] == "2023-01-15T00:00:00.000Z"
        assert row["release_date"] is None

    def test_catalog_row_gets_acquired_at_without_touching_release(self) -> None:
        rec = {
            "namespace": "fn",
            "catalogItemId": "cat-1",
            "acquisitionDate": "2022-06-01T00:00:00.000Z",
        }
        catalog = {
            "title": "Catalog Game",
            "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
            "categories": [{"path": "games"}],
            "releaseInfo": [{"date": "2020-01-01T00:00:00.000Z"}],
        }
        row = _build_game_row_from_record(rec, catalog, None)
        assert row is not None
        assert row["acquired_at"] == "2022-06-01T00:00:00.000Z"
        assert row["release_date"] == "2020-01-01T00:00:00.000Z"
