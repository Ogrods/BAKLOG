"""Tests for fetcher cache merge (enrichment preservation)."""

from __future__ import annotations

from fetchers._authoritative import GOG
from fetchers._base import merge_cached_row


def test_merge_preserves_steam_reviews() -> None:
    cached = {
        "store": "gog",
        "id": 1,
        "name": "Old Name",
        "steam_review_percent": 93.4,
        "steam_review_count": 1000,
        "steam_review_desc": "Very Positive",
        "hltb_main_hours": 12.0,
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "name": "New Name",
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
    }
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=False)
    assert merged["name"] == "New Name"
    assert merged["steam_review_percent"] == 93.4
    assert merged["steam_review_count"] == 1000
    assert merged["steam_review_desc"] == "Very Positive"
    assert merged["hltb_main_hours"] == 12.0


def test_merge_overwrites_hltb_when_updated() -> None:
    cached = {"store": "gog", "id": 1, "hltb_main_hours": 10.0, "hltb_name": "Old"}
    fresh = {
        "store": "gog",
        "id": 1,
        "hltb_main_hours": 20.0,
        "hltb_main_extra_hours": 30.0,
        "hltb_completionist_hours": 40.0,
        "hltb_match_confidence": 1.0,
        "hltb_name": "New",
    }
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=True)
    assert merged["hltb_main_hours"] == 20.0
    assert merged["hltb_name"] == "New"
