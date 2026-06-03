"""Unit tests for Nintendo wishlist HTML/JSON parsing."""
from __future__ import annotations

from pathlib import Path

from fetch_nintendo_wishlist import (
    _build_row,
    _signed_out,
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
    from fetch_nintendo_wishlist import WishlistItem

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


def test_signed_out_login_page() -> None:
    assert _signed_out("", "https://accounts.nintendo.com/login")
    assert not _signed_out(FIXTURE.read_text(encoding="utf-8"), "https://www.nintendo.com/us/wish-list/")
