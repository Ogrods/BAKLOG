"""Unit tests for Nintendo wishlist HTML/JSON parsing."""
from __future__ import annotations

from pathlib import Path

from fetchers.fetch_nintendo_wishlist import (
    _build_row,
    _signed_out,
    _wishlist_graphql_ok,
    _wishlist_session_authenticated,
    parse_wishlist_sources,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nintendo_wishlist_next_data.html"


def test_parse_wishlist_from_next_data_fixture() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    items = parse_wishlist_sources(html, [])
    assert len(items) == 2
    titles = {it.title for it in items}
    assert "Test Adventure" in titles
    assert "Demo Platformer" in titles
    assert all(it.product_id.startswith("7") for it in items)
    assert all("nintendo.com" in it.store_url for it in items)


def test_build_row_schema() -> None:
    from fetchers.fetch_nintendo_wishlist import WishlistItem

    item = WishlistItem(
        product_id="71000000012345",
        title="Test Adventure",
        image_url="https://assets.nintendo.com/test.jpg",
        store_url="https://www.nintendo.com/us/store/products/test-adventure-switch/",
        release_date=None,
        genres=["Adventure"],
        price="$49.99",
        price_initial="$59.99",
        discount_percent=17,
        currency="USD",
    )
    row = _build_row(item, None)
    assert row["store"] == "wishlist"
    assert row["wishlist_store"] == "nintendo"
    assert row["id"] == "nintendo-71000000012345"
    assert row["nintendo_product_id"] == "71000000012345"


def test_build_row_tags_dlc() -> None:
    from fetchers.fetch_nintendo_wishlist import WishlistItem

    item = WishlistItem(
        product_id="71000000099999",
        title="Adventure Expansion Pass",
        image_url=None,
        store_url="https://www.nintendo.com/us/store/products/adventure-dlc-switch/",
        release_date=None,
        genres=[],
        price="$19.99",
        price_initial=None,
        discount_percent=None,
        currency="USD",
        is_dlc=True,
    )
    row = _build_row(item, None)
    assert row["type"] == "dlc"
    assert row["tags"] == ["dlc"]
    assert row["nintendo_is_dlc"] is True


def test_wishlist_item_is_dlc_from_product_type() -> None:
    from fetchers.fetch_nintendo_wishlist import _item_from_dict

    item = _item_from_dict(
        {
            "nsUid": "71000000088888",
            "title": "Bonus Tracks Pack",
            "productType": "DLC",
            "url": "/us/store/products/bonus-tracks-switch/",
        }
    )
    assert item is not None
    assert item.is_dlc is True


def test_signed_out_login_page() -> None:
    assert _signed_out("", "https://accounts.nintendo.com/login")
    assert not _signed_out(FIXTURE.read_text(encoding="utf-8"), "https://www.nintendo.com/us/wish-list/")


def test_parse_wishlist_from_graphql_payload() -> None:
    payload = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {
                    "items": [
                        {
                            "id": "wl-1",
                            "product": {
                                "nsUid": "71000000012345",
                                "title": "GraphQL Adventure",
                                "url": "/us/store/products/graphql-adventure-switch/",
                                "image": {"url": "https://assets.nintendo.com/test.jpg"},
                            },
                        }
                    ],
                    "hasNextPage": False,
                },
            }
        }
    }
    items = parse_wishlist_sources("", [payload])
    assert len(items) == 1
    assert items[0].title == "GraphQL Adventure"
    assert _wishlist_graphql_ok(payload)
    assert _wishlist_session_authenticated([payload])


def test_empty_authenticated_wishlist_counts_as_session() -> None:
    payload = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {"items": [], "hasNextPage": False},
            }
        }
    }
    assert _wishlist_graphql_ok(payload)
    assert _wishlist_session_authenticated([payload])
    assert parse_wishlist_sources("", [payload]) == []
