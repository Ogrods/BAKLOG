"""Unit tests for Nintendo wishlist HTML/JSON parsing."""
from __future__ import annotations

from pathlib import Path

from fetchers.fetch_nintendo_wishlist import (
    _build_row,
    _parse_wishlist_html_href_scrape,
    _signed_out,
    _wishlist_capture_complete,
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


def test_import_omits_dlc_items_from_written_list() -> None:
    """DLC stays on the Nintendo wishlist but is not written into BAKLOG."""
    from fetchers.fetch_nintendo_wishlist import WishlistItem, _build_row

    game = WishlistItem(
        product_id="71000000012345",
        title="Test Adventure",
        image_url=None,
        store_url="https://www.nintendo.com/us/store/products/test-adventure-switch/",
        release_date=None,
        genres=[],
        price="$49.99",
        price_initial=None,
        discount_percent=None,
        currency="USD",
        is_dlc=False,
    )
    dlc = WishlistItem(
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
    items = [game, dlc]
    kept = [it for it in items if not it.is_dlc]
    assert len(kept) == 1
    assert kept[0].title == "Test Adventure"
    rows = [_build_row(it, None) for it in kept]
    assert all(r["type"] == "game" for r in rows)
    assert not any(r.get("nintendo_is_dlc") for r in rows)


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


def test_nintendo_wishlist_session_ready_rejects_guest_empty_graphql() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    guest_empty = {
        "data": {
            "customer": {
                "wishList": {"items": [], "hasNextPage": False},
            }
        }
    }
    html = '<script>{"__typename":"GuestAuthorization"}</script>'
    url = "https://www.nintendo.com/us/wish-list/"
    assert not _nintendo_wishlist_session_ready(html, url, [guest_empty])
    assert not _nintendo_wishlist_session_ready("", url, [guest_empty])


def test_nintendo_wishlist_session_ready_accepts_authenticated_empty() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    authed_empty = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {"items": [], "hasNextPage": False},
            }
        }
    }
    url = "https://www.nintendo.com/us/wish-list/"
    assert _nintendo_wishlist_session_ready("", url, [authed_empty])


def test_nintendo_wishlist_session_ready_rejects_signed_out_html() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    assert not _nintendo_wishlist_session_ready(
        "<html>Sign in</html>",
        "https://accounts.nintendo.com/login",
        [],
    )


def test_nintendo_wishlist_session_ready_rejects_ssr_html_without_auth() -> None:
    """SSR / __NEXT_DATA__ tiles alone must not complete Connect before sign-in."""
    from auth.runner import _nintendo_wishlist_session_ready

    html = FIXTURE.read_text(encoding="utf-8")
    url = "https://www.nintendo.com/us/wish-list/"
    assert parse_wishlist_sources(html, [])  # parser still finds items
    assert not _nintendo_wishlist_session_ready(html, url, [])


def test_nintendo_wishlist_session_ready_rejects_marketing_tiles() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    marketing = (
        "<html><body>"
        '<a href="/us/store/products/zelda-switch/">The Legend of Zelda</a>'
        '<a href="/us/store/products/mario-71000000012345/">Super Mario</a>'
        "</body></html>"
    )
    url = "https://www.nintendo.com/us/wish-list/"
    assert parse_wishlist_sources(marketing, []) == []
    assert not _nintendo_wishlist_session_ready(marketing, url, [])


def test_nintendo_wishlist_session_ready_rejects_customer_id_alone() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    customer_only = {"data": {"customer": {"id": "cust-1"}}}
    url = "https://www.nintendo.com/us/wish-list/"
    assert not _nintendo_wishlist_session_ready("", url, [customer_only])


def test_nintendo_wishlist_session_ready_accepts_storefront_tokens() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    url = "https://www.nintendo.com/us/wish-list/"
    assert _nintendo_wishlist_session_ready(
        "",
        url,
        [],
        storefront_ok=True,
        page_session={"__typename": "CustomerAuthorization"},
    )


def test_nintendo_wishlist_session_ready_rejects_guest_storefront() -> None:
    from auth.runner import _nintendo_wishlist_session_ready

    url = "https://www.nintendo.com/us/wish-list/"
    assert not _nintendo_wishlist_session_ready(
        "",
        url,
        [],
        storefront_ok=True,
        page_session={"__typename": "GuestAuthorization"},
    )


def test_parse_wishlist_graphql_precedence_over_ssr() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    payload = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {
                    "items": [
                        {
                            "product": {
                                "nsUid": "71000000099999",
                                "title": "GraphQL Only Title",
                                "url": "/us/store/products/graphql-only-switch/",
                            }
                        }
                    ],
                    "hasNextPage": False,
                },
            }
        }
    }
    items = parse_wishlist_sources(html, [payload])
    assert len(items) == 1
    assert items[0].title == "GraphQL Only Title"
    assert items[0].product_id == "71000000099999"


def test_parse_wishlist_empty_graphql_blocks_ssr_backfill() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    empty_auth = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {"items": [], "hasNextPage": False},
            }
        }
    }
    assert parse_wishlist_sources(html, [])  # SSR alone still works
    assert parse_wishlist_sources(html, [empty_auth]) == []


def test_parse_wishlist_marketing_href_not_on_import_path() -> None:
    marketing = (
        "<html><body>"
        '<a href="/us/store/products/zelda-switch/">The Legend of Zelda</a>'
        '<a href="/us/store/products/mario-71000000012345/">Super Mario</a>'
        "</body></html>"
    )
    assert parse_wishlist_sources(marketing, []) == []
    scraped = _parse_wishlist_html_href_scrape(marketing)
    assert scraped  # dump/debug helper still extracts tiles


def test_toast_only_graphql_does_not_suppress_ssr_fallback() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    toast = {"data": {"toast": {"message": "ok"}}, "errors": None}
    assert not _wishlist_graphql_ok(toast)
    items = parse_wishlist_sources(html, [toast])
    assert len(items) == 2
    titles = {it.title for it in items}
    assert "Test Adventure" in titles


def test_wishlist_capture_complete_requires_graphql() -> None:
    html = FIXTURE.read_text(encoding="utf-8")
    assert not _wishlist_capture_complete(html, [])
    empty_auth = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {"items": [], "hasNextPage": False},
            }
        }
    }
    assert _wishlist_capture_complete(html, [empty_auth])
    with_items = {
        "data": {
            "customer": {
                "id": "cust-1",
                "wishList": {
                    "items": [
                        {
                            "product": {
                                "nsUid": "71000000012345",
                                "title": "GraphQL Adventure",
                            }
                        }
                    ],
                    "hasNextPage": False,
                },
            }
        }
    }
    assert _wishlist_capture_complete("", [with_items])
