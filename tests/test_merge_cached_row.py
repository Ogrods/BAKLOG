"""Tests for fetcher cache merge (enrichment preservation)."""

from __future__ import annotations

from fetch_gog import merge_gog_cached_row
from fetchers._authoritative import AMAZON, GOG, HUMBLE, PSN
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


def test_merge_preserves_enriched_images_when_fresh_is_empty() -> None:
    """An Amazon refetch with no native cover URL must not clobber the Steam-CDN
    URLs that enrich_cross_store_images.py wrote on a previous run."""
    cached = {
        "store": "amazon",
        "id": "abc",
        "amazon_id": "abc",
        "name": "RAD",
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/2307350/header.jpg",
        "library_image": "https://cdn.akamai.steamstatic.com/steam/apps/2307350/library_600x900_2x.jpg",
        "steam_appid": 2307350,
        "image_source": "steam_search",
    }
    fresh = {
        "store": "amazon",
        "id": "abc",
        "amazon_id": "abc",
        "name": "RAD",
        "header_image": None,
        "library_image": None,
    }
    merged = merge_cached_row(fresh, cached, authoritative=AMAZON, hltb_updated=False)
    assert merged["header_image"].startswith("https://cdn.akamai.steamstatic.com")
    assert merged["library_image"].endswith("/library_600x900_2x.jpg")
    assert merged["image_source"] == "steam_search"
    assert merged["steam_appid"] == 2307350


def test_merge_lets_fresh_image_override_enrichment() -> None:
    """If the store fetcher later publishes a real cover URL, it wins."""
    cached = {
        "store": "amazon",
        "id": "abc",
        "amazon_id": "abc",
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/2307350/header.jpg",
        "library_image": "https://cdn.akamai.steamstatic.com/steam/apps/2307350/library_600x900_2x.jpg",
        "image_source": "steam_search",
    }
    fresh = {
        "store": "amazon",
        "id": "abc",
        "amazon_id": "abc",
        "header_image": "https://images-na.ssl-images-amazon.com/rad-header.jpg",
        "library_image": "https://images-na.ssl-images-amazon.com/rad-library.jpg",
    }
    merged = merge_cached_row(fresh, cached, authoritative=AMAZON, hltb_updated=False)
    assert merged["header_image"] == fresh["header_image"]
    assert merged["library_image"] == fresh["library_image"]


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


def test_merge_preserves_playtime_when_fresh_is_zero() -> None:
    cached = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "playtime_minutes": 120,
        "last_played": "2024-06-01",
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "playtime_minutes": 0,
        "last_played": None,
    }
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=False)
    assert merged["playtime_minutes"] == 120
    assert merged["last_played"] == "2024-06-01"


def test_merge_overwrites_playtime_when_fresh_has_real_value() -> None:
    cached = {"store": "gog", "id": 1, "gog_id": 1, "playtime_minutes": 120}
    fresh = {"store": "gog", "id": 1, "gog_id": 1, "playtime_minutes": 240}
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=False)
    assert merged["playtime_minutes"] == 240


def test_merge_hltb_partial_update_keeps_cached_for_empty_fresh_keys() -> None:
    cached = {
        "store": "gog",
        "id": 1,
        "hltb_main_hours": 10.0,
        "hltb_main_extra_hours": 15.0,
        "hltb_name": "Old",
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "hltb_main_hours": 20.0,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
    }
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=True)
    assert merged["hltb_main_hours"] == 20.0
    assert merged["hltb_main_extra_hours"] == 15.0
    assert merged["hltb_name"] == "Old"


def test_merge_preserves_coop_when_fresh_is_false() -> None:
    auth = GOG | frozenset({"coop_online", "coop_local"})
    cached = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "coop_online": True,
        "coop_local": True,
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "coop_online": False,
        "coop_local": False,
    }
    merged = merge_cached_row(fresh, cached, authoritative=auth, hltb_updated=False)
    assert merged["coop_online"] is True
    assert merged["coop_local"] is True


def test_merge_preserves_psn_first_played_and_trophy_when_fresh_empty() -> None:
    cached = {
        "store": "psn",
        "id": "CUSA12345_00",
        "psn_id": "CUSA12345_00",
        "first_played": "2020-01-15T10:00:00Z",
        "trophy_progress": 42,
        "playtime_minutes": 300,
    }
    fresh = {
        "store": "psn",
        "id": "CUSA12345_00",
        "psn_id": "CUSA12345_00",
        "first_played": None,
        "trophy_progress": None,
        "playtime_minutes": 0,
        "last_played": None,
    }
    merged = merge_cached_row(fresh, cached, authoritative=PSN, hltb_updated=False)
    assert merged["first_played"] == "2020-01-15T10:00:00Z"
    assert merged["trophy_progress"] == 42
    assert merged["playtime_minutes"] == 300


def test_merge_price_overwrites_to_zero_when_fresh_is_zero() -> None:
    cached = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "price": 19.99,
        "price_initial": 29.99,
        "discount_percent": 33,
        "currency": "USD",
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "price": 0,
        "price_initial": 0,
        "discount_percent": 0,
        "currency": "",
    }
    merged = merge_cached_row(fresh, cached, authoritative=GOG, hltb_updated=False)
    assert merged["price"] == 0
    assert merged["price_initial"] == 0
    assert merged["discount_percent"] == 0
    assert merged["currency"] == ""


def test_merge_last_played_keeps_newer_date() -> None:
    cached = {
        "store": "psn",
        "id": "x",
        "psn_id": "x",
        "last_played": "2024-06-01T12:00:00Z",
    }
    fresh = {
        "store": "psn",
        "id": "x",
        "psn_id": "x",
        "last_played": "2023-01-01T00:00:00Z",
    }
    merged = merge_cached_row(fresh, cached, authoritative=PSN, hltb_updated=False)
    assert merged["last_played"] == "2024-06-01T12:00:00Z"


def test_merge_first_played_keeps_earlier_date() -> None:
    cached = {
        "store": "psn",
        "id": "x",
        "psn_id": "x",
        "first_played": "2020-01-01T00:00:00Z",
    }
    fresh = {
        "store": "psn",
        "id": "x",
        "psn_id": "x",
        "first_played": "2022-06-15T00:00:00Z",
    }
    merged = merge_cached_row(fresh, cached, authoritative=PSN, hltb_updated=False)
    assert merged["first_played"] == "2020-01-01T00:00:00Z"


def test_merge_humble_preserves_enrichment_on_refetch() -> None:
    """Humble fetch rows default playtime/reviews to empty; merge must keep cache."""
    cached = {
        "store": "humble",
        "id": "humble-game-one",
        "humble_id": "game-one",
        "playtime_minutes": 90,
        "steam_review_percent": 88.0,
        "header_image": "https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg",
        "hltb_main_hours": 12.0,
    }
    fresh = {
        "store": "humble",
        "id": "humble-game-one",
        "humble_id": "game-one",
        "humble_gamekey": "gk1",
        "name": "Game One",
        "playtime_minutes": 0,
        "last_played": None,
        "header_image": None,
        "library_image": None,
        "steam_review_percent": None,
        "steam_review_count": None,
        "steam_review_desc": None,
        "hltb_main_hours": None,
        "hltb_main_extra_hours": None,
        "hltb_completionist_hours": None,
        "hltb_match_confidence": None,
        "hltb_name": None,
        "store_url": "https://www.humblebundle.com/store/game-one",
        "type": "game",
    }
    merged = merge_cached_row(fresh, cached, authoritative=HUMBLE, hltb_updated=False)
    assert merged["playtime_minutes"] == 90
    assert merged["steam_review_percent"] == 88.0
    assert merged["header_image"].startswith("https://cdn.akamai")
    assert merged["hltb_main_hours"] == 12.0
    assert merged["name"] == "Game One"


def test_merge_gog_cross_source_preserves_metadata() -> None:
    """Web → local source flip must not wipe release_date/genres/images."""
    cached = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "source": "web",
        "name": "Example Game",
        "release_date": "Oct 7, 2025",
        "genres": ["RPG", "Action"],
        "header_image": "https://images.gog.com/header.jpg",
        "library_image": "https://images.gog.com/library.jpg",
        "tags": ["story rich"],
        "steam_review_percent": 91.0,
        "hltb_main_hours": 14.0,
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "source": "local",
        "name": "Example Game",
        "release_date": None,
        "genres": [],
        "header_image": None,
        "library_image": None,
        "tags": [],
        "playtime_minutes": 120,
        "steam_review_percent": None,
        "hltb_main_hours": None,
        "price": None,
        "price_initial": None,
        "discount_percent": None,
        "currency": None,
    }
    merged = merge_gog_cached_row(fresh, cached, source="local", hltb_updated=False)
    assert merged["source"] == "local"
    assert merged["playtime_minutes"] == 120
    assert merged["release_date"] == "Oct 7, 2025"
    assert merged["genres"] == ["RPG", "Action"]
    assert merged["header_image"] == "https://images.gog.com/header.jpg"
    assert merged["library_image"] == "https://images.gog.com/library.jpg"
    assert merged["tags"] == ["story rich"]
    assert merged["steam_review_percent"] == 91.0
    assert merged["hltb_main_hours"] == 14.0


def test_merge_sets_coop_when_fresh_is_true() -> None:
    auth = GOG | frozenset({"coop_online", "coop_local"})
    cached = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "coop_online": False,
        "coop_local": False,
    }
    fresh = {
        "store": "gog",
        "id": 1,
        "gog_id": 1,
        "coop_online": True,
        "coop_local": True,
    }
    merged = merge_cached_row(fresh, cached, authoritative=auth, hltb_updated=False)
    assert merged["coop_online"] is True
    assert merged["coop_local"] is True
