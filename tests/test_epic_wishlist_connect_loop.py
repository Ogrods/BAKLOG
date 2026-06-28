from __future__ import annotations
from urllib.parse import urlparse
import pytest
import auth.runner as runner

class _FakeTime:

    def __init__(self, step_s: float=1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t

class _FakeGraphQLResponse:
    url = 'https://store.epicgames.com/graphql'
    status = 200

    def json(self) -> dict:
        return {'data': {'Wishlist': {'wishlistItems': {'elements': []}}}}

class _FakePage:

    def __init__(self, *, url: str='https://www.epicgames.com/id/login', stays_on_wishlist: bool=False, emit_wishlist_graphql: bool=False) -> None:
        self.url = url
        self.stays_on_wishlist = stays_on_wishlist
        self.emit_wishlist_graphql = emit_wishlist_graphql
        self.goto_calls: int = 0
        self._listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def _emit_wishlist_graphql(self) -> None:
        for callback in self._listeners.get('response', []):
            callback(_FakeGraphQLResponse())

    def goto(self, _url: str, *, wait_until: str | None=None, timeout: int | None=None) -> None:
        self.goto_calls += 1
        ul = (_url or '').lower()
        if 'id/login' in ul or 'id.epicgames.com' in ul:
            self.url = _url
            return
        if self.stays_on_wishlist and 'wishlist' in ul:
            self.url = _url
            if self.emit_wishlist_graphql:
                self._emit_wishlist_graphql()
            return
        if 'wishlist' in ul:
            self.url = 'https://store.epicgames.com/en-US/'
            return
        self.url = _url

    def bring_to_front(self) -> None:
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None

class _FakeLoginThenStorePage:

    def __init__(self) -> None:
        self.url = 'https://www.epicgames.com/id/login'
        self.goto_calls = 0
        self._listeners: dict[str, list] = {}
        self._polls = 0
        self._saw_login = False

    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def _emit_wishlist_graphql(self) -> None:
        for callback in self._listeners.get('response', []):
            callback(_FakeGraphQLResponse())

    def goto(self, _url: str, *, wait_until: str | None=None, timeout: int | None=None) -> None:
        self.goto_calls += 1
        ul = (_url or '').lower()
        if 'id/login' in ul or 'id.epicgames.com' in ul:
            self.url = _url
            self._saw_login = True
            return
        if 'wishlist' in ul:
            self.url = _url
            self._emit_wishlist_graphql()

    def wait_for_timeout(self, _ms: int) -> None:
        self._polls += 1
        path = urlparse(self.url or '').path.lower()
        if self._saw_login and self._polls == 1 and ('wishlist' not in path):
            self.url = 'https://store.epicgames.com/en-US/'

    def bring_to_front(self) -> None:
        return None

class _FakeContext:

    def __init__(self, *, signed_in: bool=False) -> None:
        self._signed_in = signed_in

    def cookies(self) -> list[dict]:
        if not self._signed_in:
            return []
        return [{'name': 'epic_session_diesel', 'value': 'test-session', 'domain': '.epicgames.com'}]

class _FakeSession:

    def emit(self, _event: str, _data: dict) -> None:
        return None

def test_epic_wishlist_inline_times_out_on_login_without_wishlist_graphql(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    context = _FakeContext()
    session = _FakeSession()
    fake_time = _FakeTime(step_s=6.0)
    monkeypatch.setattr(runner.time, 'time', fake_time.time)
    monkeypatch.setattr(runner, 'SUCCESS_WAIT_SEC', 20.0)
    monkeypatch.setattr(runner, 'POLL_SEC', 0.1)
    with pytest.raises(RuntimeError, match='Could not detect Epic wishlist sign-in'):
        runner._extract_epic_wishlist_inline(page, context, session)
    assert page.goto_calls == 1

class _FakeSignedInRedirectPage:

    def __init__(self) -> None:
        self.url = 'https://www.epicgames.com/id/login'
        self.goto_calls = 0
        self._listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def _emit_wishlist_graphql(self) -> None:
        for callback in self._listeners.get('response', []):
            callback(_FakeGraphQLResponse())

    def goto(self, _url: str, *, wait_until: str | None=None, timeout: int | None=None) -> None:
        self.goto_calls += 1
        ul = (_url or '').lower()
        if '/id/login' in ul or 'id.epicgames.com' in ul:
            self.url = 'https://store.epicgames.com/en-US/wishlist'
            self._emit_wishlist_graphql()
            return
        self.url = _url

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def bring_to_front(self) -> None:
        return None

def test_epic_wishlist_inline_accepts_wishlist_graphql_without_extra_goto(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakeSignedInRedirectPage()
    context = _FakeContext()
    session = _FakeSession()
    fake_time = _FakeTime(step_s=1.0)
    monkeypatch.setattr(runner.time, 'time', fake_time.time)
    monkeypatch.setattr(runner, 'SUCCESS_WAIT_SEC', 300.0)
    monkeypatch.setattr(runner, 'POLL_SEC', 0.1)
    creds = runner._extract_epic_wishlist_inline(page, context, session)
    assert creds == {'EPIC_STORE_COOKIE': 'ready'}
    assert page.goto_calls == 1

def test_epic_wishlist_inline_post_login_goto_then_graphql(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakeLoginThenStorePage()
    context = _FakeContext()
    session = _FakeSession()
    fake_time = _FakeTime(step_s=1.0)
    monkeypatch.setattr(runner.time, 'time', fake_time.time)
    monkeypatch.setattr(runner, 'SUCCESS_WAIT_SEC', 300.0)
    monkeypatch.setattr(runner, 'POLL_SEC', 0.1)
    creds = runner._extract_epic_wishlist_inline(page, context, session)
    assert creds == {'EPIC_STORE_COOKIE': 'ready'}
    assert page.goto_calls == 2

def test_epic_wishlist_inline_post_login_goto_without_graphql_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage(url='https://store.epicgames.com/en-US/')
    context = _FakeContext(signed_in=True)
    session = _FakeSession()
    page.url = 'https://www.epicgames.com/id/login'
    fake_time = _FakeTime(step_s=6.0)
    monkeypatch.setattr(runner.time, 'time', fake_time.time)
    monkeypatch.setattr(runner, 'SUCCESS_WAIT_SEC', 20.0)
    monkeypatch.setattr(runner, 'POLL_SEC', 0.1)

    def _goto(url: str, *, wait_until: str | None=None, timeout: int | None=None) -> None:
        page.goto_calls += 1
        ul = (url or '').lower()
        if 'id/login' in ul or 'id.epicgames.com' in ul:
            page.url = url
            return
        if 'wishlist' in ul:
            page.url = 'https://store.epicgames.com/en-US/'
    page.goto = _goto

    def _wait(_ms: int) -> None:
        if '/id/login' in (page.url or '') or 'id.epicgames.com' in (page.url or ''):
            page.url = 'https://store.epicgames.com/en-US/'
    page.wait_for_timeout = _wait
    with pytest.raises(RuntimeError, match='Could not detect Epic wishlist sign-in'):
        runner._extract_epic_wishlist_inline(page, context, session)
    assert page.goto_calls == 2