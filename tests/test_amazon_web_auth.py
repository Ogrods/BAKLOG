"""Unit tests for Prime Gaming web connect navigation helpers (no browser)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

from amazon_web_client import (
    COLLECTION_URLS,
    GAMING_HOME_URL,
    LUNA_CLAIMS_URL,
    amazon_signin_url,
    collection_page_ready,
    collection_urls,
    is_luna_error_page,
    is_luna_hub,
    is_signin_url,
    needs_collection_redirect,
    on_collection_page,
    signed_in,
    try_parse_claims_from_html,
    try_parse_claims_from_text,
)


class _FakeCookieJar:
    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies

    def cookies(self) -> list[dict]:
        return self._cookies


def test_collection_urls_order():
    urls = collection_urls()
    assert urls[0] == LUNA_CLAIMS_URL
    assert GAMING_HOME_URL in urls
    assert len(urls) == len(COLLECTION_URLS)


def test_amazon_signin_url_return_to_my_collection_no_sso_response():
    url = amazon_signin_url()
    assert url.startswith("https://www.amazon.com/ap/signin?")
    assert "ssoResponse" not in url
    qs = parse_qs(urlparse(url).query)
    assert qs["openid.return_to"] == [LUNA_CLAIMS_URL]
    assert qs["openid.assoc_handle"] == ["tempo_us"]


def test_is_signin_url_detects_ap_signin():
    assert is_signin_url("https://www.amazon.com/ap/signin?openid.pape.max_auth_age=0")
    assert is_signin_url("https://www.amazon.com/ap/register")
    assert not is_signin_url("https://luna.amazon.com/claims/my-collection")


def test_is_luna_hub():
    assert is_luna_hub("https://luna.amazon.com/")
    assert is_luna_hub("https://luna.amazon.com")
    assert not is_luna_hub("https://luna.amazon.com/claims/my-collection")


def test_on_collection_page_luna_and_gaming():
    assert on_collection_page("https://luna.amazon.com/claims/my-collection")
    assert on_collection_page("https://gaming.amazon.com/home")
    assert not on_collection_page("https://luna.amazon.com/")
    assert not on_collection_page("https://www.amazon.com/")


def test_needs_collection_redirect_on_luna_hub_when_signed_in():
    ctx = _FakeCookieJar([{"name": "session-id", "value": "abc", "domain": ".amazon.com"}])
    assert needs_collection_redirect("https://luna.amazon.com/", ctx)


def test_signed_in_requires_cookies_and_non_signin_url():
    ctx = _FakeCookieJar([{"name": "session-id", "value": "abc", "domain": ".amazon.com"}])
    assert signed_in("https://gaming.amazon.com/home", ctx)
    assert not signed_in("https://www.amazon.com/ap/signin", ctx)
    assert not signed_in("https://gaming.amazon.com/home", _FakeCookieJar([]))


def test_is_luna_error_page():
    assert is_luna_error_page("<h1>We're having technical difficulties.</h1>")
    assert not is_luna_error_page("<html>My Collection</html>")


def test_collection_page_ready_rejects_error_page():
    url = "https://luna.amazon.com/claims/my-collection"
    assert not collection_page_ready(
        "<p>We're having technical difficulties.</p>", url,
    )
    assert collection_page_ready("<html>My Collection</html>", url)


def test_try_parse_claims_from_text_empty_list_is_success():
    payload = {"data": {"claims": {"claims": []}}}
    items = try_parse_claims_from_text(json.dumps(payload))
    assert items is not None
    assert items == []


def test_try_parse_claims_from_html_embedded_json():
    payload = {
        "data": {
            "claims": {
                "claims": [{"itemTitle": "Lake", "itemId": "amzn1.pg.item.lake"}],
            }
        }
    }
    html = f"<html><script>window.__STATE__ = {json.dumps(payload)};</script></html>"
    items = try_parse_claims_from_html(html)
    assert items is not None
    assert len(items) == 1
    assert items[0]["itemTitle"] == "Lake"
