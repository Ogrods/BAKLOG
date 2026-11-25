"""Unit tests for Humble library + wishlist parsing."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from fetchers._progress import EXIT_CODE_AUTH

from auth.connect_extractors import (
    HUMBLE_LIBRARY_URL,
    HUMBLE_SUCCESS_URL_PATTERN,
    dump_humble_session_cookies,
    extract_humble_session,
    humble_connect_hint,
    humble_has_durable_session_cookies,
    humble_is_durable_session_cookie_name,
    humble_page_is_confirmed_library_or_store,
    humble_session_cookie_names,
    humble_session_status_authenticated,
    restore_humble_session_cookies,
)
from fetchers.fetch_humble import (
    FILTER_USER_LIBRARY_ACTION,
    LIBRARY_URL,
    LibraryItem,
    _CHROME_STUCK_MSG,
    _build_row,
    _discover_filter_user_library_action,
    _extract_filter_user_library_payload,
    _goto_humble_library,
    _item_from_library_result,
    _looks_like_filter_user_library_payload,
    _page_looks_signed_out,
    _parse_order_detail,
    _pick_humble_library_page,
    _subproduct_is_game,
)
from fetchers.fetch_humble_wishlist import (
    WishlistItem,
    _discover_wishlist_action_ids,
    _extract_wishlist_payload,
    _item_from_lookup,
    _item_from_wishlist_row,
    _looks_like_wishlist_payload,
    _merge_lookup_into_items,
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
    assert pat.search("https://www.humblebundle.com/store/wishlist")
    assert not pat.search("https://auth.humblebundle.com/login?flow=abc")


def test_humble_page_is_confirmed_library_or_store() -> None:
    assert humble_page_is_confirmed_library_or_store(
        "https://www.humblebundle.com/home/library"
    )
    assert humble_page_is_confirmed_library_or_store(
        "https://www.humblebundle.com/store/wishlist"
    )
    assert not humble_page_is_confirmed_library_or_store(
        "https://auth.humblebundle.com/login?flow=abc"
    )
    assert not humble_page_is_confirmed_library_or_store(
        "https://www.humblebundle.com/login"
    )
    assert not humble_page_is_confirmed_library_or_store("")


def test_humble_session_status_authenticated() -> None:
    assert not humble_session_status_authenticated({"status": "anonymous"})
    assert not humble_session_status_authenticated({})
    assert humble_session_status_authenticated({"status": "authenticated"})
    assert humble_session_status_authenticated({"authenticated": True})


class _FakeResp:
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self._body = body

    def text(self) -> str:
        return self._body


class _FakeRequest:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def get(self, url: str, timeout: int = 0) -> _FakeResp:  # noqa: ARG002
        return _FakeResp(200, json.dumps(self._payload))


_DURABLE_HUMBLE_COOKIES = [
    {
        "name": "__Host-ory_kratos_session",
        "value": "session-token",
        "domain": "www.humblebundle.com",
        "path": "/",
        "secure": True,
        "httpOnly": True,
    }
]


class _FakeContext:
    def __init__(
        self,
        status_payload: dict,
        *,
        cookies: list | None = None,
    ) -> None:
        self.request = _FakeRequest(status_payload)
        self._cookies = list(_DURABLE_HUMBLE_COOKIES if cookies is None else cookies)
        self.set_cookie_calls: list[dict] = []

    def cookies(self) -> list:
        return list(self._cookies)

    def raw_cookies(self) -> list:
        return list(self._cookies)

    def set_cookies(self, cookies: list) -> int:
        self.set_cookie_calls.extend(cookies)
        self._cookies.extend(cookies)
        return len(cookies)


class _FakePage:
    def __init__(
        self,
        url: str,
        *,
        fail_goto: bool = False,
        html: str = "",
    ) -> None:
        self.url = url
        self._fail_goto = fail_goto
        self._html = html
        self.goto_calls = 0
        self.reload_calls = 0
        self.wait_ms: list[int] = []

    def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:  # noqa: ARG002
        self.goto_calls += 1
        if self._fail_goto:
            raise RuntimeError("goto failed")
        self.url = url

    def reload(self, wait_until: str = "", timeout: int = 0) -> None:  # noqa: ARG002
        self.reload_calls += 1

    def wait_for_timeout(self, ms: int) -> None:
        self.wait_ms.append(ms)

    def content(self) -> str:
        return self._html

    def title(self) -> str:
        return getattr(self, "_title", "") or ""


def test_humble_durable_session_cookie_helpers() -> None:
    assert humble_is_durable_session_cookie_name("__Host-ory_kratos_session")
    assert humble_is_durable_session_cookie_name("ory_kratos_session")
    assert humble_is_durable_session_cookie_name("ory_session_stoiccohens510ht9xek")
    assert humble_is_durable_session_cookie_name("__Host-ory_session_abc")
    assert not humble_is_durable_session_cookie_name(
        "__Host-ory_kratos_browser_abc123"
    )
    assert not humble_is_durable_session_cookie_name("ory_kratos_continuity")
    names = humble_session_cookie_names(
        [
            {"name": "__Host-ory_kratos_browser_x", "value": "1", "domain": "auth.humblebundle.com"},
            {"name": "__Host-ory_kratos_session", "value": "1", "domain": "www.humblebundle.com"},
            {"name": "csrf_token_x", "value": "1", "domain": ".humblebundle.com"},
        ]
    )
    assert names == ["__Host-ory_kratos_session"]
    assert humble_has_durable_session_cookies(_FakeContext({"status": "authenticated"}))
    assert not humble_has_durable_session_cookies(
        _FakeContext(
            {"status": "authenticated"},
            cookies=[
                {
                    "name": "__Host-ory_kratos_browser_x",
                    "value": "1",
                    "domain": "auth.humblebundle.com",
                }
            ],
        )
    )


def test_humble_connect_hint_uses_parsed_host() -> None:
    assert "Sign in" in humble_connect_hint(_FakePage("https://www.humblebundle.com/login"))
    assert "Finish sign-in" in humble_connect_hint(
        _FakePage("https://auth.humblebundle.com/self-service/login/browser")
    )
    assert "Open humblebundle.com" in humble_connect_hint(
        _FakePage("https://evil.example/?q=auth.humblebundle.com")
    )
    assert "library finishes loading" in humble_connect_hint(
        _FakePage("https://www.humblebundle.com/home/library")
    )


def test_extract_humble_session_rejects_auth_host_only() -> None:
    ctx = _FakeContext({"status": "authenticated"})
    page = _FakePage("https://auth.humblebundle.com/login?flow=abc")
    # Stays on auth host — extract must not mark ready mid-Ory.
    assert extract_humble_session(ctx, page) is None
    assert page.goto_calls == 0
    assert page.reload_calls == 0


def test_extract_humble_session_leaves_login_alone_while_anonymous() -> None:
    """Poll must not goto/reload library before sign-in (flashes the login page)."""
    import auth.connect_extractors as ce

    ce._HUMBLE_LIBRARY_MINT_COUNT = 0
    ce._HUMBLE_LIBRARY_MINT_LAST = 0.0
    ctx = _FakeContext(
        {"status": "anonymous"},
        cookies=[
            {"name": "__cf_bm", "value": "1", "domain": ".humblebundle.com"},
            {"name": "sift_session_id", "value": "1", "domain": ".humblebundle.com"},
        ],
    )
    login = _FakePage("https://www.humblebundle.com/login?next=/home/library")
    assert extract_humble_session(ctx, login) is None
    assert login.goto_calls == 0
    assert login.reload_calls == 0

    home = _FakePage("https://www.humblebundle.com/")
    assert extract_humble_session(ctx, home) is None
    assert home.goto_calls == 0
    assert home.reload_calls == 0


def test_extract_humble_session_mints_library_ui_without_durable_cookie() -> None:
    """On library UI without ory session cookie, allow a quiet rate-limited reload."""
    import auth.connect_extractors as ce

    ce._HUMBLE_LIBRARY_MINT_COUNT = 0
    ce._HUMBLE_LIBRARY_MINT_LAST = 0.0
    ctx = _FakeContext(
        {"status": "authenticated"},
        cookies=[
            {
                "name": "__Host-ory_kratos_browser_abc",
                "value": "1",
                "domain": "auth.humblebundle.com",
            }
        ],
    )
    page = _FakePage("https://www.humblebundle.com/home/library")
    assert extract_humble_session(ctx, page) is None
    assert page.reload_calls == 1
    assert page.goto_calls == 0


def test_extract_humble_session_rejects_browser_only_cookies() -> None:
    ctx = _FakeContext(
        {"status": "authenticated"},
        cookies=[
            {
                "name": "__Host-ory_kratos_browser_abc",
                "value": "1",
                "domain": "auth.humblebundle.com",
            },
            {"name": "ory_kratos_continuity", "value": "1", "domain": ".humblebundle.com"},
        ],
    )
    page = _FakePage("https://www.humblebundle.com/home/library")
    assert extract_humble_session(ctx, page) is None


def test_extract_humble_session_accepts_www_library() -> None:
    ctx = _FakeContext({"status": "authenticated"})
    page = _FakePage("https://www.humblebundle.com/")
    creds = extract_humble_session(ctx, page)
    assert creds == {"HUMBLE_PROFILE": "ready"}
    assert page.url == HUMBLE_LIBRARY_URL
    assert page.goto_calls >= 1
    assert any(ms >= 4000 for ms in page.wait_ms)


def test_extract_humble_session_rejects_anonymous_after_library() -> None:
    calls = {"n": 0}

    class FlipRequest:
        def get(self, url: str, timeout: int = 0) -> _FakeResp:  # noqa: ARG002
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResp(200, json.dumps({"status": "authenticated"}))
            return _FakeResp(200, json.dumps({"status": "anonymous"}))

    class FlipContext:
        def __init__(self) -> None:
            self.request = FlipRequest()
            self._cookies = list(_DURABLE_HUMBLE_COOKIES)

        def cookies(self) -> list:
            return list(self._cookies)

    ctx = FlipContext()
    page = _FakePage("https://www.humblebundle.com/")
    assert extract_humble_session(ctx, page) is None


def test_extract_humble_session_rejects_goto_failure() -> None:
    ctx = _FakeContext({"status": "authenticated"})
    page = _FakePage("https://www.humblebundle.com/", fail_goto=True)
    assert extract_humble_session(ctx, page) is None


def test_humble_cookie_sidecar_roundtrip(tmp_path) -> None:
    ctx = _FakeContext({"status": "authenticated"})
    n = dump_humble_session_cookies(ctx, tmp_path)
    assert n >= 1
    empty = _FakeContext({"status": "authenticated"}, cookies=[])
    restored = restore_humble_session_cookies(empty, tmp_path)
    assert restored >= 1
    assert humble_has_durable_session_cookies(empty)


def test_page_looks_signed_out_url_detection() -> None:
    from fetchers.fetch_humble import _page_on_cloudflare

    assert _page_looks_signed_out(
        _FakePage("https://auth.humblebundle.com/login?flow=abc")
    )
    assert _page_looks_signed_out(_FakePage("https://www.humblebundle.com/login"))
    assert not _page_looks_signed_out(
        _FakePage("https://www.humblebundle.com/home/library")
    )
    login_title = _FakePage("https://www.humblebundle.com/home/library")
    login_title._title = "Login | Humble Bundle"
    assert _page_looks_signed_out(login_title)
    cf_page = _FakePage(
        "https://www.humblebundle.com/home/library",
        html="<html><title>Just a moment...</title><div id='cf_challenge_container'></div></html>",
    )
    assert _page_on_cloudflare(cf_page)
    assert not _page_looks_signed_out(cf_page)


def test_extract_humble_session_rejects_login_title() -> None:
    ctx = _FakeContext({"status": "authenticated"})
    page = _FakePage("https://www.humblebundle.com/home/library")
    page._title = "Login | Humble Bundle"
    assert extract_humble_session(ctx, page) is None


def test_probe_humble_session_routes_and_missing_profile(tmp_path, monkeypatch) -> None:
    from auth.session_probe import PROBEABLE_BROWSER, probe_browser_session, probe_humble_session

    assert "humble" in PROBEABLE_BROWSER
    monkeypatch.setattr(
        "auth.secrets.profile_dir",
        lambda _p: tmp_path / "missing-humble-profile",
    )
    err = probe_humble_session({"HUMBLE_PROFILE": "ready"})
    assert err is not None
    assert "No saved Humble browser profile" in err
    with patch("auth.session_probe.probe_humble_session", return_value=None) as mock:
        assert probe_browser_session("humble", {"HUMBLE_PROFILE": "ready"}) is None
        mock.assert_called_once()


def test_pick_humble_library_page_skips_chrome_ntp() -> None:
    ntp = _FakePage("chrome://new-tab-page/")
    library = _FakePage("https://www.humblebundle.com/home/library")

    class Ctx:
        pages = [ntp, library]

        def new_page(self):
            raise AssertionError("should reuse existing library tab")

    assert _pick_humble_library_page(Ctx()) is library


def test_goto_humble_library_skips_when_already_on_library() -> None:
    class Ctx:
        def new_page(self):
            raise AssertionError("should not open a new tab")

    page = _FakePage("https://www.humblebundle.com/home/library")
    out = _goto_humble_library(page, Ctx())
    assert out is page
    assert page.goto_calls == 0


def test_goto_humble_library_does_not_treat_chrome_ntp_as_success() -> None:
    class StuckChrome(_FakePage):
        def goto(self, url: str, wait_until: str = "", timeout: int = 0) -> None:  # noqa: ARG002
            self.goto_calls += 1
            self.url = "chrome://new-tab-page/"

    class Ctx:
        def __init__(self) -> None:
            self.pages: list = []

        def new_page(self):
            p = StuckChrome("chrome://new-tab-page/")
            self.pages.append(p)
            return p

    first = StuckChrome("chrome://new-tab-page/")
    ctx = Ctx()
    with pytest.raises(RuntimeError, match=_CHROME_STUCK_MSG):
        _goto_humble_library(first, ctx)
    assert first.goto_calls == 0
    assert any(p.goto_calls >= 1 for p in ctx.pages)


def test_goto_humble_library_retries_on_new_page() -> None:
    class Ctx:
        def __init__(self) -> None:
            self.pages: list = []

        def new_page(self):
            p = _FakePage("about:blank")
            self.pages.append(p)
            return p

    first = _FakePage("about:blank", fail_goto=True)
    ctx = Ctx()
    page = _goto_humble_library(first, ctx)
    assert page is not first
    assert page.url == LIBRARY_URL
    assert page.goto_calls == 1


def test_fetch_library_close_bounded_passes_profile(tmp_path, monkeypatch) -> None:
    import fetchers.fetch_humble as fetch_mod

    profile = tmp_path / "humble-profile"
    profile.mkdir()
    monkeypatch.setattr("fetchers.fetch_humble.profile_dir", lambda _p: profile)
    closed: list = []

    def _close(_ctx, *, profile=None, **kwargs):  # noqa: ARG001
        closed.append(profile)

    class BarePage(_FakePage):
        def on(self, _event: str, _handler) -> None:
            return None

    class BareCtx:
        pages: list = []

        def __init__(self) -> None:
            self.request = _FakeRequest({"status": "authenticated"})

        def new_page(self):
            return BarePage(LIBRARY_URL)

    monkeypatch.setattr("auth.cdp_browser.close_browser_bounded", _close)
    monkeypatch.setattr(
        "auth.cdp_browser.launch_persistent_profile",
        lambda *_a, **_k: BareCtx(),
    )

    def _boom(*_a, **_k):
        raise RuntimeError("stop after open")

    monkeypatch.setattr(fetch_mod, "_goto_humble_library", _boom)

    with pytest.raises(RuntimeError, match="stop after open"):
        fetch_mod.fetch_library_items()

    assert closed == [profile]


def test_main_auth_failure_signed_out_exit_4(monkeypatch) -> None:
    import fetchers.fetch_humble as fetch_mod

    msg = fetch_mod._session_expired_message(
        _FakePage("https://auth.humblebundle.com/login?flow=x")
    )
    marked: list[tuple[str, str]] = []

    monkeypatch.setattr(
        fetch_mod,
        "run_with_heartbeat",
        lambda fn, _label: (_ for _ in ()).throw(RuntimeError(msg)),
    )
    monkeypatch.setattr(
        fetch_mod,
        "mark_invalid",
        lambda provider, *, error="": marked.append((provider, error)),
    )
    monkeypatch.setattr(sys, "argv", ["fetch_humble"])
    assert fetch_mod.main() == EXIT_CODE_AUTH
    assert marked and marked[0][0] == "humble"
    assert "session expired" in marked[0][1].lower()


def test_main_chrome_stuck_remains_exit_1(monkeypatch) -> None:
    import fetchers.fetch_humble as fetch_mod

    monkeypatch.setattr(
        fetch_mod,
        "run_with_heartbeat",
        lambda fn, _label: (_ for _ in ()).throw(RuntimeError(_CHROME_STUCK_MSG)),
    )
    monkeypatch.setattr(
        fetch_mod,
        "mark_invalid",
        lambda *_a, **_k: pytest.fail("mark_invalid must not run for chrome stuck"),
    )
    monkeypatch.setattr(sys, "argv", ["fetch_humble"])
    assert fetch_mod.main() == 1


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


def test_empty_wishlist_results_envelope_is_valid() -> None:
    empty = {"results": [], "pagination": {"page": 1, "totalPages": 0}, "success": True}
    assert _looks_like_wishlist_payload(empty)
    assert _extract_wishlist_payload(json.dumps(empty)) == empty
    assert not _looks_like_wishlist_payload({"results": []})


def test_extract_wishlist_payload_handles_braces_in_titles() -> None:
    data = {
        "results": [{"machine_name": "weird", "human_name": "Game } Edition", "title": "Game } Edition"}],
        "success": True,
    }
    flight = f'0:["$@1"]\n1:{json.dumps(data)}'
    extracted = _extract_wishlist_payload(flight)
    assert extracted is not None
    assert extracted["results"][0]["human_name"] == "Game } Edition"


def test_merge_lookup_keeps_rows_missing_from_partial_lookup() -> None:
    rows = [
        WishlistItem("a", "A", None, "https://www.humblebundle.com/store/a", None, None, None, None),
        WishlistItem("b", "B", None, "https://www.humblebundle.com/store/b", None, None, None, None),
    ]
    looked = [
        WishlistItem(
            "a",
            "A",
            "https://img/a.jpg",
            "https://www.humblebundle.com/store/a",
            "$1.00",
            "$2.00",
            50,
            "USD",
        ),
    ]
    merged = _merge_lookup_into_items(rows, looked)
    by_id = {it.product_id: it for it in merged}
    assert set(by_id) == {"a", "b"}
    assert by_id["a"].price == "$1.00"
    assert by_id["a"].image_url == "https://img/a.jpg"
    assert by_id["b"].title == "B"


