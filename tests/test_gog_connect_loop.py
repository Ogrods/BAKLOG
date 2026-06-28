from __future__ import annotations
import pytest
import auth.runner as runner
from auth.connect_extractors import pick_gog_al_from_cookies

class _FakeTime:

    def __init__(self, step_s: float=1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t

class _FakePage:
    url = 'https://www.gog.com/'

    def goto(self, *_a, **_k) -> None:
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None

class _FakeContext:

    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies
        self.pages = [_FakePage()]

    def cookies(self) -> list[dict]:
        return list(self._cookies)

def test_gog_inline_connect_returns_gog_al(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(step_s=5.0)
    monkeypatch.setattr(runner, 'time', clock)
    monkeypatch.setattr('auth.connect_loop.time', clock)
    monkeypatch.setattr('auth.connect_loop.abort_if_browser_closed', lambda _ctx: None)
    cookies = [{'name': 'gog-al', 'value': 'inline-token', 'domain': '.gog.com'}]
    ctx = _FakeContext(cookies)
    page = _FakePage()
    creds = runner._extract_gog_inline(page, ctx, session=None)
    assert creds == {'GOG_AL': 'inline-token'}
    assert pick_gog_al_from_cookies(cookies) == 'inline-token'