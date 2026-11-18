"""Unit tests for Humble library + wishlist parsing."""
from __future__ import annotations

import json
import re
from pathlib import Path

from auth.connect_extractors import (
    HUMBLE_LIBRARY_URL,
    HUMBLE_SUCCESS_URL_PATTERN,
    humble_session_status_authenticated,
)
from fetchers.fetch_humble import (
    FILTER_USER_LIBRARY_ACTION,
    LIBRARY_URL,
    LibraryItem,
    _build_row,
    _discover_filter_user_library_action,
    _extract_filter_user_library_payload,
    _item_from_library_result,
    _looks_like_filter_user_library_payload,
    _parse_order_detail,
    _subproduct_is_game,
)
from fetchers.fetch_humble_wishlist import (
    WishlistItem,
    _discover_wishlist_action_ids,
    _extract_wishlist_payload,
    _item_from_lookup,
    _item_from_wishlist_row,
    _looks_like_wishlist_payload,
    _slugs_from_payload,
    text_shows_wishlist_unavailable,
)
from fetchers.fetch_humble_wishlist import (
    _build_row as _build_wishlist_row,
)

ORDER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "humble_order_detail.json"
LOOKUP_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "humble_wishlist_lookup.json"
WISHLIST_ACTION_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "humble_wishlist_action_page.json"
)
WISHLIST_INTERSTITIAL_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "humble_wishlist_interstitial.html"
)
LIBRARY_FILTER_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "humble_library_filter_page.json"
)


def test_subproduct_is_game_heuristics() -> None:
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    tpkd = data["tpkd_dict"]
    subs = {s["machine_name"]: s for s in data["subproducts"]}
    assert _subproduct_is_game(subs["sample_game"], tpkd)
    assert not _subproduct_is_game(subs["sample_ebook"], tpkd)
    assert _subproduct_is_game(subs["sample_steam_key"], tpkd)


def test_parse_order_detail_games_only() -> None:
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    items = _parse_order_detail(data, include_nongames=False)
    names = {it.name for it in items}
    assert "Sample Game" in names
    assert "Steam Key Game" in names
    assert "Sample Ebook Only" not in names
    steam = next(it for it in items if it.name == "Steam Key Game")
    assert steam.steam_app_id == "123456"
    assert "steampowered.com" in steam.store_url


def test_parse_order_detail_include_nongames() -> None:
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    items = _parse_order_detail(data, include_nongames=True)
    assert any(it.name == "Sample Ebook Only" for it in items)


def test_build_library_row_schema() -> None:
    item = LibraryItem(
        machine_name="sample_game",
        name="Sample Game",
        image_url="https://cdn.humblebundle.com/images/icons/sample_game.png",
        store_url="https://www.humblebundle.com/store/sample_game",
        gamekey="AbCdEf",
        redeemed=False,
        steam_app_id=None,
    )
    row = _build_row(item, None)
    assert row["store"] == "humble"
    assert row["id"] == "humble-sample_game"
    assert row["humble_id"] == "sample_game"
    assert "unredeemed key" in row["tags"]


def test_item_from_lookup_fixture() -> None:
    data = json.loads(LOOKUP_FIXTURE.read_text(encoding="utf-8"))
    items = [it for it in (_item_from_lookup(o) for o in data["result"]) if it]
    assert len(items) == 2
    titles = {it.title for it in items}
    assert "Hollow Knight" in titles
    assert "Celeste" in titles
    celeste = next(it for it in items if it.title == "Celeste")
    assert celeste.discount_percent == 75
    assert celeste.price == "$4.99"
    assert celeste.store_url == "https://www.humblebundle.com/store/celeste"


def test_item_from_lookup_requires_title_and_machine() -> None:
    assert _item_from_lookup({}) is None
    assert _item_from_lookup({"machine_name": "x"}) is None
    assert _item_from_lookup({"human_name": "X"}) is None


def test_humble_library_landing_constants() -> None:
    assert LIBRARY_URL == HUMBLE_LIBRARY_URL == "https://www.humblebundle.com/home/library"
    assert FILTER_USER_LIBRARY_ACTION
    pat = re.compile(HUMBLE_SUCCESS_URL_PATTERN)
    assert pat.search("https://www.humblebundle.com/home/library")
    assert pat.search("https://auth.humblebundle.com/login?flow=abc")
    assert pat.search("https://www.humblebundle.com/store/wishlist")


def test_humble_session_status_authenticated() -> None:
    assert not humble_session_status_authenticated({"status": "anonymous"})
    assert not humble_session_status_authenticated({})
    assert humble_session_status_authenticated({"status": "authenticated"})
    assert humble_session_status_authenticated({"authenticated": True})


def test_extract_filter_user_library_payload_plain_json() -> None:
    data = json.loads(LIBRARY_FILTER_FIXTURE.read_text(encoding="utf-8"))
    extracted = _extract_filter_user_library_payload(json.dumps(data))
    assert extracted is not None
    assert len(extracted["results"]) == 3
    assert extracted["pagination"]["totalPages"] == 2
    assert _looks_like_filter_user_library_payload(extracted)


def test_extract_filter_user_library_payload_flight_embedded() -> None:
    data = json.loads(LIBRARY_FILTER_FIXTURE.read_text(encoding="utf-8"))
    flight = f'0:["$@1"]\n1:{json.dumps(data)}'
    extracted = _extract_filter_user_library_payload(flight)
    assert extracted is not None
    assert extracted["results"][0]["title"] == "Celeste"


def test_discover_filter_user_library_action_from_bundle_snippet() -> None:
    action = "60199147c9d010842d98602b018a506278c5317f8e"
    snippet = (
        f'e.s("next-flight-loader","{action}",rn.callServer,void 0,'
        'rn.findSourceMapURL,"filterUserLibrary");'
    )
    assert _discover_filter_user_library_action(snippet) == action
    assert _discover_filter_user_library_action("nope") is None
    assert not _looks_like_filter_user_library_payload({"results": "bad"})
    assert _looks_like_filter_user_library_payload({"results": [{"title": "X"}]})


def test_item_from_library_result_games_only() -> None:
    data = json.loads(LIBRARY_FILTER_FIXTURE.read_text(encoding="utf-8"))
    items = [
        it
        for it in (
            _item_from_library_result(row, include_nongames=False)
            for row in data["results"]
        )
        if it
    ]
    names = {it.name for it in items}
    assert "Celeste" in names
    assert "Hollow Knight" in names
    assert "Sample Ebook Only" not in names
    from urllib.parse import urlparse

    celeste = next(it for it in items if it.name == "Celeste")
    assert celeste.steam_app_id == "504230"
    assert urlparse(celeste.store_url).hostname == "store.steampowered.com"


def test_build_wishlist_row_schema() -> None:
    item = WishlistItem(
        product_id="hollow_knight",
        title="Hollow Knight",
        image_url="https://cdn.humblebundle.com/images/hollow_knight.jpg",
        store_url="https://www.humblebundle.com/store/hollow_knight",
        price="$14.99",
        price_initial="$14.99",
        discount_percent=None,
        currency="USD",
    )
    row = _build_wishlist_row(item, None)
    assert row["store"] == "wishlist"
    assert row["wishlist_store"] == "humble"
    assert row["id"] == "humble-hollow_knight"
    assert row["humble_product_id"] == "hollow_knight"


def test_wishlist_interstitial_detection() -> None:
    html = WISHLIST_INTERSTITIAL_FIXTURE.read_text(encoding="utf-8")
    assert text_shows_wishlist_unavailable(html)
    assert not text_shows_wishlist_unavailable("<html><body>Your Wishlist</body></html>")


def test_extract_wishlist_action_payload() -> None:
    data = json.loads(WISHLIST_ACTION_FIXTURE.read_text(encoding="utf-8"))
    extracted = _extract_wishlist_payload(json.dumps(data))
    assert extracted is not None
    assert _looks_like_wishlist_payload(extracted)
    slugs = _slugs_from_payload(extracted)
    assert "hollow_knight" in slugs
    assert "celeste" in slugs
    items = [it for it in (_item_from_wishlist_row(r) for r in extracted["results"]) if it]
    names = {it.title for it in items}
    assert "Hollow Knight" in names
    assert "Celeste" in names
    hollow = next(it for it in items if it.title == "Hollow Knight")
    assert hollow.price == "$14.99"


def test_extract_wishlist_payload_flight_embedded() -> None:
    data = json.loads(WISHLIST_ACTION_FIXTURE.read_text(encoding="utf-8"))
    flight = f'0:["$@1"]\n1:{json.dumps(data)}'
    extracted = _extract_wishlist_payload(flight)
    assert extracted is not None
    assert extracted["results"][0]["machine_name"] == "hollow_knight"


def test_discover_wishlist_action_ids() -> None:
    snippet = (
        'e.s("x","60aabbccddeeff00112233445566778899aabbccdd",rn.callServer,void 0,'
        'rn.findSourceMapURL,"filterUserWishlist");'
    )
    ids = _discover_wishlist_action_ids(snippet)
    assert "60aabbccddeeff00112233445566778899aabbccdd" in ids
    assert _discover_wishlist_action_ids("nope") == []


