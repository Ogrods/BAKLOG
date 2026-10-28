"""Unit tests for Prime Gaming web connect navigation helpers (no browser)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from clients.amazon_web_client import (
    COLLECTION_URLS,
    GAMING_HOME_URL,
    LUNA_CLAIMS_URL,
    AmazonWebAuthError,
    amazon_signin_url,
    classify_sniff_capture,
    collection_page_ready,
    collection_urls,
    filter_codeless_claims,
    graphical_display_available,
    is_luna_error_page,
    is_luna_hub,
    is_signin_url,
    needs_collection_redirect,
    on_collection_page,
    signed_in,
    sniff_claims,
    try_parse_claims_from_html,
    try_parse_claims_from_text,
)
from fetchers.fetch_amazon import _read_raw_dump_claims, _web_outcome_kind_from_capture


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
    assert is_signin_url("https://www.amazon.com/ap/cvf/request?arb=abc")
    assert is_signin_url("https://www.amazon.com/ap/mfa")
    assert is_signin_url("https://www.amazon.com/ap/challenge")
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
    ctx = _FakeCookieJar([{"name": "at-main", "value": "abc", "domain": ".amazon.com"}])
    assert needs_collection_redirect("https://luna.amazon.com/", ctx)


def test_signed_in_requires_auth_cookies_and_non_signin_url():
    weak = _FakeCookieJar([{"name": "session-id", "value": "abc", "domain": ".amazon.com"}])
    strong = _FakeCookieJar([{"name": "at-main", "value": "tok", "domain": ".amazon.com"}])
    assert signed_in("https://gaming.amazon.com/home", strong)
    assert not signed_in("https://gaming.amazon.com/home", weak)
    assert not signed_in("https://www.amazon.com/ap/signin", strong)
    assert not signed_in("https://gaming.amazon.com/home", _FakeCookieJar([]))


def test_signed_in_false_on_cvf_even_with_session_id():
    """Password step often sets session-id before OTP; must not look signed-in."""
    ctx = _FakeCookieJar([{"name": "session-id", "value": "abc", "domain": ".amazon.com"}])
    assert is_signin_url("https://www.amazon.com/ap/cvf/request?arb=1")
    assert not signed_in("https://www.amazon.com/ap/cvf/request?arb=1", ctx)
    # Even with a strong cookie, challenge URLs stay "signing in".
    strong = _FakeCookieJar([{"name": "at-main", "value": "tok", "domain": ".amazon.com"}])
    assert not signed_in("https://www.amazon.com/ap/cvf/request?arb=1", strong)


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


def test_empty_collection_success_mapping() -> None:
    outcome = {"capture_ok": True, "signed_in": True}
    kind = _web_outcome_kind_from_capture(raw_claims=[], outcome=outcome)
    assert kind == "signed_in_empty"


def test_signed_out_auth_path_classification() -> None:
    assert (
        classify_sniff_capture(capture_ok=False, signed_in=False) == "signed_out"
    )


def test_raw_dump_fallback_builds_records() -> None:
    # Minimal Amazon-fulfilled claim (passes codeless filter).
    raw_claim = {
        "itemTitle": "Lake",
        "itemId": "amzn1.pg.item.lake",
        "orderId": "amzn1.pg.order.1",
        "orderState": "FULFILLED",
    }

    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "amazon_web_raw.json"
        path.write_text(
            json.dumps(
                {
                    "raw_claim_count": 1,
                    "raw_claims": [raw_claim],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        fallback_claims = _read_raw_dump_claims(path=path)
        assert fallback_claims == [raw_claim]

        sniff_outcome = {"capture_ok": False, "signed_in": True}
        kind = _web_outcome_kind_from_capture(
            raw_claims=[],
            outcome=sniff_outcome,
            fallback_claims=fallback_claims,
        )
        assert kind == "raw_dump_fallback"

        records = filter_codeless_claims(fallback_claims)
        assert len(records) == 1
        assert records[0]["name"] == "Lake"


def test_graphical_display_available_linux_needs_display_or_wayland(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("clients.amazon_web_client.sys.platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert graphical_display_available() is False

    monkeypatch.setenv("DISPLAY", ":0")
    assert graphical_display_available() is True

    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    assert graphical_display_available() is True


def test_graphical_display_available_win32_without_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("clients.amazon_web_client.sys.platform", "win32")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert graphical_display_available() is True


def test_sniff_claims_skips_headed_when_no_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signed-in headless no_claims must not launch headed Chrome without X."""
    profile = tmp_path / "amazon_web"
    profile.mkdir()
    monkeypatch.setattr(
        "auth.secrets.profile_dir",
        lambda _key: profile,
    )
    monkeypatch.setattr(
        "clients.amazon_web_client.graphical_display_available",
        lambda: False,
    )

    launches: list[dict] = []

    class _FakePage:
        url = "https://luna.amazon.com/claims/my-collection"

        def on(self, *_a, **_k) -> None:
            return None

        def wait_for_timeout(self, *_a, **_k) -> None:
            return None

    class _FakeCtx:
        pages = [_FakePage()]

        def add_init_script(self, *_a, **_k) -> None:
            return None

        def new_page(self) -> _FakePage:
            return _FakePage()

    def fake_launch(user_data_dir, **kwargs):  # type: ignore[no-untyped-def]
        launches.append({"user_data_dir": str(user_data_dir), **kwargs})
        return _FakeCtx()

    def fake_poll(
        page,
        ctx,
        *,
        deadline,
        candidates,
        raw_claims,
        captured,
        **_kwargs,
    ) -> None:
        # Headless path: signed in, but no claims payload.
        captured["done"] = True
        captured["claims_captured"] = False
        captured["session_only_captured"] = False

    monkeypatch.setattr("auth.cdp_browser.launch_persistent_profile", fake_launch)
    monkeypatch.setattr("auth.cdp_browser.close_browser_bounded", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "clients.amazon_web_client._poll_prime_collection",
        fake_poll,
    )
    monkeypatch.setattr(
        "clients.amazon_web_client.signed_in",
        lambda *_a, **_k: True,
    )

    with pytest.raises(AmazonWebAuthError, match="graphical display") as exc:
        sniff_claims(timeout_s=5)

    assert "Start BAKLOG" in str(exc.value) or "desktop" in str(exc.value).lower()
    assert len(launches) == 1
    assert launches[0].get("headless") is True
    assert all(launch.get("headless") is not False for launch in launches)
