"""Regression guard for the Steam Connect navigation loop.

Beta testers reported the Steam sign-in window "tabbing between two windows"
and Steam returning "You've made too many requests recently". Root cause: the
poll loop navigated the visible window every ~0.5s (apikey page -> /my/profile
to read the SteamID -> back to apikey ...), which both flips the visible tab and
floods Steam with requests until it rate-limits.

These tests drive the real ``auth.api_keys`` extraction with a fake CDP
page/context that records every navigation, so the loop behaviour is verified
deterministically without a browser or a live Steam login.

They also cover the no-API-key path (the real trigger behind the report): a
signed-in user with no registered key. Auto-registration must tick the Steam
Web API Terms-of-Use box (Steam refuses to issue a key otherwise), and if a key
still can't be obtained the user gets an actionable error, not a silent timeout.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from auth import api_keys

APIKEY_URL = "https://steamcommunity.com/dev/apikey"
PROFILE_URL = "https://steamcommunity.com/my/profile"
STEAMID = "76561198000000001"


class FakeLocator:
    def __init__(self, count: int = 0) -> None:
        self._count = count

    @property
    def first(self) -> FakeLocator:
        return self

    def count(self) -> int:
        return self._count

    def fill(self, *_a, **_k) -> None:
        pass

    def click(self, *_a, **_k) -> None:
        pass


class FakePage:
    """Minimal CdpPage stand-in that records navigations."""

    def __init__(self, *, inline_steamid: bool = False, has_key: bool = False,
                 rate_limit_after: int = 4) -> None:
        self.url = APIKEY_URL
        self.inline_steamid = inline_steamid
        self.has_key = has_key
        self.rate_limit_after = rate_limit_after
        self.nav_log: list[str] = []

    def goto(self, url: str, **_k) -> None:
        self.nav_log.append(url)
        self.url = url

    def evaluate(self, expr: str, **_k):
        if "g_steamID" in expr:
            return STEAMID if self.inline_steamid else ""
        return ""

    def content(self) -> str:
        if len(self.nav_log) > self.rate_limit_after:
            return "<html><body>Access Denied. You've made too many requests recently.</body></html>"
        if "apikey" in self.url and self.has_key:
            return "<html>Key: 0123456789ABCDEF0123456789ABCDEF</html>"
        if "profile" in self.url:
            return f"<html><body>{STEAMID}</body></html>"
        return "<html><body>register a domain to get a key</body></html>"

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def locator(self, _sel: str) -> FakeLocator:
        return FakeLocator(0)

    def get_by_role(self, _role: str, *, name=None) -> FakeLocator:
        return FakeLocator(0)


class FakeContext:
    def __init__(self, steamid: str = STEAMID) -> None:
        self._steamid = steamid

    def cookies(self):
        token = quote("||token-abc", safe="")
        return [
            {"name": "sessionid", "value": "x", "domain": "steamcommunity.com"},
            {
                "name": "steamLoginSecure",
                "value": f"{self._steamid}{token}",
                "domain": "steamcommunity.com",
            },
        ]


def _drive(page: FakePage, context: FakeContext, polls: int) -> None:
    """Call the real per-poll extractor ``polls`` times (no real sleeps)."""
    for _ in range(polls):
        api_keys._steam_extract_from_page(page, context)


def test_steam_connect_does_not_pingpong_navigate() -> None:
    """No registered key yet: the loop must NOT keep navigating the window."""
    page = FakePage(inline_steamid=False, has_key=False)
    context = FakeContext()
    _drive(page, context, polls=8)
    profile_navs = [u for u in page.nav_log if "profile" in u]
    assert profile_navs == [], f"should never navigate to /my/profile, got {page.nav_log}"
    assert len(page.nav_log) <= 1, f"window should settle, got {len(page.nav_log)} navs: {page.nav_log}"


def test_steam_connect_reads_steamid_from_cookie() -> None:
    """With a key on the page, SteamID comes from the cookie (no navigation)."""
    page = FakePage(inline_steamid=False, has_key=True)
    context = FakeContext()
    creds = api_keys._steam_extract_from_page(page, context)
    assert creds == {
        "STEAM_API_KEY": "0123456789ABCDEF0123456789ABCDEF",
        "STEAM_ID": STEAMID,
    }
    assert [u for u in page.nav_log if "profile" in u] == []


class FakeSession:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def emit(self, _event: str, payload: dict) -> None:
        self.messages.append(payload.get("message", ""))


class RegFakePage:
    """Fake dev/apikey page that shows the 'register a key' form.

    Registration only succeeds once the Terms-of-Use checkbox is ticked, exactly
    like the real Steam form. ``register_works=False`` simulates a form that
    never yields a key (the no-key fallback path).
    """

    def __init__(self, *, register_works: bool = True) -> None:
        self.url = APIKEY_URL
        self.register_works = register_works
        self.agreed = False
        self.has_key = False
        self.register_clicks = 0
        self.nav_log: list[str] = []

    def goto(self, url: str, **_k) -> None:
        self.nav_log.append(url)
        self.url = url

    def evaluate(self, expr: str, **_k):
        if "g_steamID" in expr:
            return ""
        if "checkbox" in expr:  # the agreement-tick helper
            self.agreed = True
            return True
        return ""

    def content(self) -> str:
        if self.has_key:
            return "<html>Key: 0123456789ABCDEF0123456789ABCDEF</html>"
        return "<html><body>Register a domain to get a key</body></html>"

    def wait_for_timeout(self, _ms: int) -> None:
        pass

    def locator(self, sel: str) -> FakeLocator:
        # Domain field present only while no key has been issued.
        if "domain" in sel and not self.has_key:
            return FakeLocator(1)
        return FakeLocator(0)

    def _register(self) -> None:
        self.register_clicks += 1
        if self.register_works and self.agreed:
            self.has_key = True

    def get_by_role(self, _role: str, *, name=None):
        page = self

        class _Btn:
            @property
            def first(self):
                return self

            def count(self) -> int:
                return 1

            def click(self, *_a, **_k) -> None:
                page._register()

        return _Btn()


def test_steam_auto_registers_after_ticking_agreement(monkeypatch) -> None:
    """No key yet: extract_steam ticks the Terms box, registers, returns creds."""
    monkeypatch.setattr(api_keys, "_validate_steam", lambda _creds: None)
    monkeypatch.setattr(api_keys, "POLL_SEC", 0)
    page = RegFakePage(register_works=True)
    context = FakeContext()
    session = FakeSession()

    creds = api_keys.extract_steam(page, context, session)

    assert creds == {
        "STEAM_API_KEY": "0123456789ABCDEF0123456789ABCDEF",
        "STEAM_ID": STEAMID,
    }
    assert page.agreed, "must tick the Steam Web API Terms-of-Use checkbox"
    assert [u for u in page.nav_log if "profile" in u] == []


def test_steam_no_key_fallback_is_actionable(monkeypatch) -> None:
    """Registration that never yields a key fails with manual-register guidance."""
    monkeypatch.setattr(api_keys, "_validate_steam", lambda _creds: None)
    monkeypatch.setattr(api_keys, "POLL_SEC", 0)
    monkeypatch.setattr(api_keys, "SUCCESS_WAIT_SEC", 0.2)
    page = RegFakePage(register_works=False)
    context = FakeContext()
    session = FakeSession()

    with pytest.raises(RuntimeError) as exc:
        api_keys.extract_steam(page, context, session)

    msg = str(exc.value).lower()
    assert "dev/apikey" in msg and "agree" in msg, f"unhelpful fallback: {exc.value}"
    # Register is capped so a wedged form can't thrash Steam.
    assert page.register_clicks <= api_keys.MAX_STEAM_REGISTER_ATTEMPTS
    assert any("registering one" in m.lower() for m in session.messages)
