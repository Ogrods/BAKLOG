"""Tests for shared Epic wishlist session helpers."""

from __future__ import annotations

from pathlib import Path

from auth.epic_wishlist_session import (
    cloudflare_interstitial,
    enrich_wishlist_elements_with_catalog,
    extract_catalog_offers_from_html,
    extract_wishlist_payloads_from_html,
    is_epic_graphql_url,
    storefront_auth_blocked,
    storefront_bounced_to_home,
    storefront_signed_out,
    wishlist_capture_complete_from_html,
    wishlist_graphql_ok,
)

DUMP_HTML = Path(__file__).resolve().parents[1] / "cache" / "epic" / "wishlist_dump.html"


def test_wishlist_graphql_ok_ignores_toast_only_graphql() -> None:
    toast = {"data": {"Wishlist": {"wishlistToast": {"offers": {"onSale": []}}}}}
    assert not wishlist_graphql_ok(toast)
    empty_wl = {"data": {"Wishlist": {"wishlistItems": {"elements": []}}}}
    assert wishlist_graphql_ok(empty_wl)


def test_wishlist_graphql_ok_accepts_batched_array() -> None:
    batch = [
        {"data": {"Wishlist": {"wishlistToast": {"offers": {"onSale": []}}}}},
        {"data": {"Wishlist": {"wishlistItems": {"elements": [{"id": "wish-1"}]}}}},
    ]
    assert wishlist_graphql_ok(batch)
    toast_only_batch = [{"data": {"Wishlist": {"wishlistToast": {}}}}]
    assert not wishlist_graphql_ok(toast_only_batch)


_DEHYDRATED_SNIPPET = (
    '{"state":{"data":{"Wishlist":{"wishlistItems":{"elements":[{"id":"wish-1",'
    '"offerId":"offer-aaa","namespace":"ns-1"}]}}},"status":"success"},'
    '"queryKey":["getWishlist",["accountId","acct"],"hash"]},'
    '{"state":{"data":[{"Catalog":{"catalogOffer":{"title":"Batman","id":"offer-aaa",'
    '"namespace":"ns-1","keyImages":[{"type":"OfferImageWide","url":"https://cdn/w.jpg"}]}}}]}'
)


def test_extract_wishlist_payloads_from_dehydrated_html() -> None:
    payloads = extract_wishlist_payloads_from_html(_DEHYDRATED_SNIPPET)
    assert len(payloads) == 1
    assert wishlist_graphql_ok(payloads[0])
    assert wishlist_capture_complete_from_html(_DEHYDRATED_SNIPPET)


def test_enrich_wishlist_elements_with_catalog_offer() -> None:
    payloads = extract_wishlist_payloads_from_html(_DEHYDRATED_SNIPPET)
    elements = payloads[0]["data"]["Wishlist"]["wishlistItems"]["elements"]
    offers = extract_catalog_offers_from_html(_DEHYDRATED_SNIPPET)
    assert offers["offer-aaa"]["title"] == "Batman"
    enriched = enrich_wishlist_elements_with_catalog(_DEHYDRATED_SNIPPET, elements)
    assert enriched[0]["offer"]["title"] == "Batman"


def test_is_epic_graphql_url_matches_known_hosts() -> None:
    assert is_epic_graphql_url("https://store.epicgames.com/graphql")
    assert is_epic_graphql_url("https://graphql.epicgames.com/graphql")
    assert is_epic_graphql_url("https://www.epicgames.com/graphql?operationName=wishlist")
    assert not is_epic_graphql_url("https://store.epicgames.com/en-US/wishlist")
    assert not is_epic_graphql_url("https://example.com/graphql")


def test_cloudflare_interstitial_real_challenge() -> None:
    cf_html = (
        "<html><head><title>Just a moment...</title></head>"
        "<body><div class='cf_challenge_container'>Checking your browser</div></body></html>"
    )
    wishlist_url = "https://store.epicgames.com/en-US/wishlist"
    assert cloudflare_interstitial(cf_html, wishlist_url)
    assert storefront_auth_blocked(cf_html, wishlist_url)


def test_cloudflare_interstitial_not_store_home_js_bundle() -> None:
    snippet = (
        "<html><body><script>"
        "a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';"
        "</script>Sign in<button>Wishlist</button></body></html>"
    )
    store_home = "https://store.epicgames.com/?lang=en-US"
    assert not cloudflare_interstitial(snippet, store_home)
    assert storefront_bounced_to_home(store_home)
    assert storefront_signed_out(snippet, store_home)


def test_store_home_dump_html_not_cloudflare_false_positive() -> None:
    if not DUMP_HTML.exists():
        return
    html = DUMP_HTML.read_text(encoding="utf-8", errors="replace")
    url = "https://store.epicgames.com/?lang=en-US"
    assert not cloudflare_interstitial(html, url)
    assert storefront_bounced_to_home(url)
    assert storefront_signed_out(html, url)
