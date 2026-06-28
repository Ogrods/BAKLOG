from urllib.parse import quote

import pytest

from auth import api_keys

APIKEY_URL = "https://steamcommunity.com/dev/apikey"
PROFILE_URL = "https://steamcommunity.com/my/profile"
STEAMID = "76561198000000001"


class FakeLocator:
    def __init__(self, count=0):
        self._count = count

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def fill(self, *_a, **_k):
        pass

    def click(self, *_a, **_k):
        pass


class FakePage:
    def __init__(self, *, inline_steamid=False, has_key=False, rate_limit_after=4):
        self.url = APIKEY_URL
        self.inline_steamid = inline_steamid
        self.has_key = has_key
        self.rate_limit_after = rate_limit_after
        self.nav_log = []

    def goto(self, url, **_k):
        self.nav_log.append(url)
        self.url = url

    def evaluate(self, expr, **_k):
        if "g_steamID" in expr:
            return STEAMID if self.inline_steamid else ""
        return ""

    def content(self):
        if len(self.nav_log) > self.rate_limit_after:
            return "<html><body>Access Denied. You've made too many requests recently.</body></html>"
        if "apikey" in self.url and self.has_key:
            return "<html>Key: 0123456789ABCDEF0123456789ABCDEF</html>"
        if "profile" in self.url:
            return f"<html><body>{STEAMID}</body></html>"
        return "<html><body>register a domain to get a key</body></html>"

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, _sel):
        return FakeLocator(0)

    def get_by_role(self, _role, *, name=None):
        return FakeLocator(0)


class FakeContext:
    def __init__(self, steamid=STEAMID):
        self._steamid = steamid

    def cookies(self):
        token = quote("||token-abc", safe="")
        return [
            {"name": "sessionid", "value": "x", "domain": "steamcommunity.com"},
            {"name": "steamLoginSecure", "value": f"{self._steamid}{token}", "domain": "steamcommunity.com"},
        ]


def _drive(page, context, polls):
    for _ in range(polls):
        api_keys._steam_extract_from_page(page, context)


def test_steam_connect_does_not_pingpong_navigate():
    page = FakePage(inline_steamid=False, has_key=False)
    context = FakeContext()
    _drive(page, context, polls=8)
    profile_navs = [u for u in page.nav_log if "profile" in u]
    assert profile_navs == [], f"should never navigate to /my/profile, got {page.nav_log}"
    assert len(page.nav_log) <= 1, f"window should settle, got {len(page.nav_log)} navs: {page.nav_log}"


def test_steam_connect_reads_steamid_from_cookie():
    page = FakePage(inline_steamid=False, has_key=True)
    context = FakeContext()
    creds = api_keys._steam_extract_from_page(page, context)
    assert creds == {"STEAM_API_KEY": "0123456789ABCDEF0123456789ABCDEF", "STEAM_ID": STEAMID}
    assert [u for u in page.nav_log if "profile" in u] == []


class FakeSession:
    def __init__(self):
        self.messages = []

    def emit(self, _event, payload):
        self.messages.append(payload.get("message", ""))


class RegFakePage:
    def __init__(self, *, register_works=True):
        self.url = APIKEY_URL
        self.register_works = register_works
        self.agreed = False
        self.has_key = False
        self.register_clicks = 0
        self.nav_log = []

    def goto(self, url, **_k):
        self.nav_log.append(url)
        self.url = url

    def evaluate(self, expr, **_k):
        if "g_steamID" in expr:
            return ""
        if "checkbox" in expr:
            self.agreed = True
            return True
        return ""

    def content(self):
        if self.has_key:
            return "<html>Key: 0123456789ABCDEF0123456789ABCDEF</html>"
        return "<html><body>Register a domain to get a key</body></html>"

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, sel):
        if "domain" in sel and (not self.has_key):
            return FakeLocator(1)
        return FakeLocator(0)

    def _register(self):
        self.register_clicks += 1
        if self.register_works and self.agreed:
            self.has_key = True

    def get_by_role(self, _role, *, name=None):
        page = self

        class _Btn:
            @property
            def first(self):
                return self

            def count(self):
                return 1

            def click(self, *_a, **_k):
                page._register()

        return _Btn()


def test_steam_auto_registers_after_ticking_agreement(monkeypatch):
    monkeypatch.setattr(api_keys, "_validate_steam", lambda _creds: None)
    monkeypatch.setattr(api_keys, "POLL_SEC", 0)
    page = RegFakePage(register_works=True)
    context = FakeContext()
    session = FakeSession()
    creds = api_keys.extract_steam(page, context, session)
    assert creds == {"STEAM_API_KEY": "0123456789ABCDEF0123456789ABCDEF", "STEAM_ID": STEAMID}
    assert page.agreed, "must tick the Steam Web API Terms-of-Use checkbox"
    assert [u for u in page.nav_log if "profile" in u] == []


def test_steam_no_key_fallback_is_actionable(monkeypatch):
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
    assert page.register_clicks <= api_keys.MAX_STEAM_REGISTER_ATTEMPTS
    assert any("registering one" in m.lower() for m in session.messages)
