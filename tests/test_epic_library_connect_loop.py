from __future__ import annotations
import json
import pytest
import auth.runner as runner

class _FakeTime:

    def __init__(self, step_s: float=1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t

class _FakePage:

    def __init__(self, url: str='about:blank') -> None:
        self.url = url
        self.is_closed = False
        self.goto_calls = 0

    def goto(self, _url: str, *, wait_until: str | None=None, timeout: int | None=None) -> None:
        self.goto_calls += 1
        if 'id/login' in _url:
            self.url = _url

    def evaluate(self, _fn: str) -> str:
        return ''

    def content(self) -> str:
        if runner.EPIC_REDIRECT_MARKER in (self.url or ''):
            return json.dumps({'authorizationCode': 'epic-lib-code-123'})
        return ''

    def wait_for_timeout(self, _ms: int) -> None:
        return None

class _FakeContext:

    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page

def test_epic_library_captures_redirect_on_non_first_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime()
    monkeypatch.setattr(runner, 'time', clock)
    blank = _FakePage('about:blank')
    redirect = _FakePage('https://www.epicgames.com/id/api/redirect?clientId=x&responseType=code')
    ctx = _FakeContext([blank, redirect])
    primary = _FakePage('https://www.epicgames.com/id/login')
    ctx.pages.insert(1, primary)

    class _FakeEpicClient:

        def __init__(self, *, auth_code: str, cache_dir: str) -> None:
            assert auth_code == 'epic-lib-code-123'

        def login(self) -> None:
            return None
    monkeypatch.setattr('clients.epic_client.EpicClient', _FakeEpicClient)
    monkeypatch.setattr('clients.epic_client.default_epic_cache_dir', lambda: '/tmp/epic')
    creds = runner._extract_epic_inline(primary, ctx, session=None)
    assert creds == {'EPIC_AUTH_CODE': 'epic-lib-code-123'}