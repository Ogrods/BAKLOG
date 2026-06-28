"""Unit tests for Epic library row filtering in fetch_epic.py."""

from __future__ import annotations

import argparse

from fetchers.fetch_epic import (
    _can_reuse_cached_epic_row,
    _is_epic_catalog_excluded,
    _is_game_item,
    _is_non_game_title,
    _needs_catalog_fetch,
)
from shared.library_noise import is_catalog_noise_row, maybe_tag_library_noise_row


def test_non_game_title_soundtrack_wallpaper_editor() -> None:
    assert _is_non_game_title("DEATH STRANDING DIGITAL SOUNDTRACK")
    assert _is_non_game_title("HD Wallpaper")
    assert _is_non_game_title("Football Manager 2024 Resource archiver")
    assert _is_non_game_title("Football Manager 2024 Pre-game editor")
    assert _is_non_game_title("Q.U.B.E. 2 Soundtrack")
    assert _is_non_game_title("SELECTIONS OF TITAN ART BOOK")
    assert _is_non_game_title("Glove Skin")
    assert _is_non_game_title("Puzzle Pack 1")
    assert _is_non_game_title("Death Stranding Content")
    assert _is_non_game_title("Fortnite_StWContent")
    assert _is_non_game_title("Chivalry 2 - Public Testing")
    assert _is_non_game_title("Galactic Civilizations III (Test branch)")


def test_playable_dlc_titles_are_kept() -> None:
    assert not _is_non_game_title("ARK Ragnarok")
    assert not _is_non_game_title("Dying Light The Following")
    assert not _is_non_game_title("Europa Universalis IV: Common Sense Expansion Pack")
    assert not _is_non_game_title("Fallout: New Vegas")
    assert not _is_non_game_title("Botany Manor")


def test_is_game_item_accepts_noise_soundtrack_for_tagging() -> None:
    item = {
        "title": "HD Wallpaper",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [],
    }
    assert _is_game_item(item)


def test_is_epic_catalog_excluded_addon_only() -> None:
    item = {
        "title": "Sand Patch Grade",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "addons"}],
    }
    assert _is_epic_catalog_excluded(item)
    assert _is_game_item(item)


def test_build_game_row_tags_excluded_catalog_as_noise() -> None:
    from fetchers.fetch_epic import _build_game_row

    item = {
        "title": "Sand Patch Grade",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "addons"}],
    }
    row = _build_game_row("cid", "ns", item, None)
    assert row is not None
    assert is_catalog_noise_row(row)


def test_is_game_item_accepts_games_category_dlc() -> None:
    item = {
        "title": "ARK Ragnarok",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "games/edition/base|games/edition/addons|addons/durable"}],
    }
    assert _is_game_item(item)


def test_maybe_tag_library_noise_row_epic_slug() -> None:
    row = {"name": "Fortnite_StWContent", "store": "epic", "tags": []}
    assert maybe_tag_library_noise_row(row, "epic")
    assert is_catalog_noise_row(row)


def test_is_game_item_accepts_addon_only_catalog_for_noise_row() -> None:
    item = {
        "title": "Sand Patch Grade",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "addons"}],
    }
    assert _is_game_item(item)


def test_can_reuse_cached_row_rejects_live_placeholder_mismatch() -> None:
    cached = {
        "name": "Live",
        "hltb_main_hours": 0,
        "library_image": "https://example/cover.jpg",
    }
    catalog_item = {
        "title": "Sand Patch Grade",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "addons"}],
    }
    assert not _can_reuse_cached_epic_row(cached, catalog_item)
    assert not _can_reuse_cached_epic_row(cached, catalog_item, skip_hltb=True)


def test_can_reuse_cached_row_allows_skip_hltb_without_hltb_fields() -> None:
    cached = {
        "name": "Botany Manor",
        "library_image": "https://example/cover.jpg",
    }
    catalog_item = {
        "title": "Botany Manor",
        "keyImages": [{"type": "OfferImageWide", "url": "https://example/x.jpg"}],
        "categories": [{"path": "games/edition/base"}],
    }
    assert _can_reuse_cached_epic_row(cached, catalog_item, skip_hltb=True)


def _args(**kwargs):
    base = {"refresh": False, "skip_hltb": True}
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_needs_catalog_fetch_skips_warm_cached_row_with_skip_hltb() -> None:
    rec = {"namespace": "fn", "catalogItemId": "abc"}
    existing = {
        "fn:abc": {
            "id": "fn:abc",
            "name": "Botany Manor",
            "library_image": "https://example/cover.jpg",
        }
    }
    assert not _needs_catalog_fetch(rec, existing, _args())


def test_needs_catalog_fetch_for_new_entitlement() -> None:
    rec = {"namespace": "fn", "catalogItemId": "new"}
    assert _needs_catalog_fetch(rec, {}, _args())


def test_needs_catalog_fetch_for_refresh_flag() -> None:
    rec = {"namespace": "fn", "catalogItemId": "abc"}
    existing = {
        "fn:abc": {
            "id": "fn:abc",
            "name": "Botany Manor",
            "library_image": "https://example/cover.jpg",
        }
    }
    assert _needs_catalog_fetch(rec, existing, _args(refresh=True))


def test_needs_catalog_fetch_reuses_warm_cached_noise_row() -> None:
    rec = {"namespace": "fn", "catalogItemId": "junk"}
    existing = {
        "fn:junk": {
            "id": "fn:junk",
            "name": "HD Wallpaper",
            "library_image": "https://example/cover.jpg",
        }
    }
    assert not _needs_catalog_fetch(rec, existing, _args())


class _PlaytimeResp:
    status_code = 200

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> object:
        return self._payload


def _playtime_client(payload: object, account_id: str | None = "acc"):
    from clients.epic_client import EpicClient

    client = object.__new__(EpicClient)
    client._account_id = account_id
    client._access_token = "tok"
    client._throttle = lambda: None  # type: ignore[method-assign]

    class _Sess:
        def get(self, *a, **k):
            return _PlaytimeResp(payload)

    client.session = _Sess()
    return client


def test_get_playtime_parses_and_filters_zero_and_junk() -> None:
    client = _playtime_client([
        {"artifactId": "a", "totalTime": 3600},
        {"artifactId": "b", "totalTime": 0},
        {"artifactId": "c"},
        {"noId": True},
        "junk",
    ])
    assert client.get_playtime() == {"a": 3600}


def test_get_playtime_without_account_returns_empty() -> None:
    client = _playtime_client([{"artifactId": "a", "totalTime": 99}], account_id=None)
    assert client.get_playtime() == {}
