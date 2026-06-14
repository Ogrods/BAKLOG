"""Regression guard for the Steam Connect navigation loop.

Beta testers reported the Steam sign-in window "tabbing between two windows"
and Steam returning "You've made too many requests recently". Root cause: the
poll loop navigated the visible window every ~0.5s (apikey page -> /my/profile
to read the SteamID -> back to apikey ...), which both flips the visible tab and
floods Steam with requests until it rate-limits.

These tests drive the real ``auth.api_keys`` extraction with a fake CDP
page/context that records every navigation, so the loop behaviour is verified
deterministically without a browser or a live Steam login.
"""

from __future__ import annotations

from urllib.parse import quote

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
