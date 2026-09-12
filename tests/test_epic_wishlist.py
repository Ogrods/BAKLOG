"""Unit tests for Epic wishlist GraphQL parsing."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from auth.epic_wishlist_session import storefront_auth_error_message
from fetchers._progress import EXIT_CODE_AUTH
from fetchers.fetch_epic_wishlist import (
    _build_row,
    parse_wishlist_sources,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "epic_wishlist_graphql.json"


def test_parse_wishlist_from_graphql_fixture() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    elements = parse_wishlist_sources("", [payload])
    assert len(elements) == 2


def test_parse_wishlist_from_dehydrated_html() -> None:
    html = (
        '{"state":{"data":{"Wishlist":{"wishlistItems":{"elements":[{"id":"wish-1",'
        '"offerId":"offer-aaa","namespace":"ns-1"}]}}},"status":"success"},'
        '"queryKey":["getWishlist",["accountId","acct"],"hash"]},'
        '{"state":{"data":[{"Catalog":{"catalogOffer":{"title":"Test Epic Game","id":"offer-aaa",'
        '"namespace":"ns-1","productSlug":"test-epic-game","keyImages":[],'
        '"price":{"totalPrice":{"discountPrice":1999,"originalPrice":3999,"currencyCode":"USD",'
        '"fmtPrice":{"originalPrice":"$39.99","discountPrice":"$19.99"}}}}}}}]}}'
    )
    elements = parse_wishlist_sources(html, [])
    assert len(elements) == 1
    assert (elements[0].get("offer") or {}).get("title") == "Test Epic Game"


def test_build_row_schema() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    el = parse_wishlist_sources("", [payload])[0]
    row = _build_row(el, None)
    assert row is not None
    assert row["store"] == "wishlist"
    assert row["wishlist_store"] == "epic"
    assert row["id"] == "epic-fn:offer-aaa"
    assert row["epic_namespace"] == "fn"
    assert row["epic_offer_id"] == "offer-aaa"
    assert "epicgames.com" in row["store_url"]
    assert row["price"] == "$19.99"


def test_main_auth_abort_cf_page_exit_4(monkeypatch) -> None:
    import fetchers.fetch_epic_wishlist as fetch_mod

    cf_html = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><div class='cf_challenge_container'>Checking your browser</div></body></html>"
    )
    wishlist_url = "https://store.epicgames.com/en-US/wishlist"
    marked: list[tuple[str, str]] = []

    monkeypatch.setattr(
        fetch_mod,
        "run_with_heartbeat",
        lambda fn, _label: (cf_html, wishlist_url, []),
    )
    monkeypatch.setattr(
        fetch_mod,
        "mark_invalid",
        lambda provider, *, error="": marked.append((provider, error)),
    )
    monkeypatch.setattr(sys, "argv", ["fetch_epic_wishlist"])
    assert fetch_mod.main() == EXIT_CODE_AUTH
    assert marked and marked[0][0] == "epic_wishlist"
    assert "Cloudflare" in marked[0][1]
    assert "Cloudflare" in storefront_auth_error_message(cf_html, wishlist_url)


def test_main_auth_abort_signed_out_exit_4(monkeypatch) -> None:
    import fetchers.fetch_epic_wishlist as fetch_mod

    html = (
        "<html><body><a href='/login'>Sign in</a>"
        "<button>Continue</button></body></html>"
    )
    home_url = "https://store.epicgames.com/?lang=en-US"
    marked: list[tuple[str, str]] = []

    monkeypatch.setattr(
        fetch_mod,
        "run_with_heartbeat",
        lambda fn, _label: (html, home_url, []),
    )
    monkeypatch.setattr(
        fetch_mod,
        "mark_invalid",
        lambda provider, *, error="": marked.append((provider, error)),
    )
    monkeypatch.setattr(sys, "argv", ["fetch_epic_wishlist"])
    assert fetch_mod.main() == EXIT_CODE_AUTH
    assert marked and marked[0][0] == "epic_wishlist"
    assert "Cloudflare" not in marked[0][1]
    assert "session" in marked[0][1].lower() or "bounced" in marked[0][1].lower()
