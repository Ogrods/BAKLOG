"""Fake-CDP loop test: Nintendo connect must drive the login tab, not a blank popup."""

from __future__ import annotations

import pytest

import auth.runner as runner


class _FakeTime:
    def __init__(self, step_s: float = 1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t


class _FakeCookie:
    def __init__(self, name: str, value: str, domain: str) -> None:
        self.name = name
        self.value = value
        self.domain = domain


class _FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.is_closed = False
        self.goto_calls = 0

    def goto(self, url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        self.goto_calls += 1
        self.url = url

    def bring_to_front(self) -> None:
        return None

    def wait_for_timeout(self, _ms: int) -> None:
        return None


class _FakeContext:
    def __init__(self, pages: list[_FakePage], cookies: list[dict] | None = None) -> None:
        self.pages = pages
        self._cookies = cookies or []

    def new_page(self) -> _FakePage:
        page = _FakePage()
        self.pages.append(page)
        return page

    def cookies(self) -> list[dict]:
        return list(self._cookies)


def test_nintendo_connect_drives_non_blank_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime(step_s=5.0)
    monkeypatch.setattr(runner, "time", clock)

    blank = _FakePage("about:blank")
    login = _FakePage("https://accounts.nintendo.com/")
    eshop = _FakePage("https://ec.nintendo.com/my/transactions/")
    ctx = _FakeContext(
        [blank, login],
        cookies=[
            {"name": "NASID", "value": "abc", "domain": "ec.nintendo.com"},
            {"name": "idToken", "value": "tok", "domain": "ec.nintendo.com"},
        ],
    )

    def _goto(url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        login.goto_calls += 1
        if "ec.nintendo.com" in url:
            login.url = eshop.url
        else:
            login.url = url

    login.goto = _goto  # type: ignore[method-assign]

    monkeypatch.setattr(runner, "_nintendo_has_session", lambda _ctx: True)
    monkeypatch.setattr(runner, "_nintendo_session_has_id_token", lambda _ctx: True)
    monkeypatch.setattr(
        runner,
        "_cookie_header",
        lambda _cookies, _domains: "NASID=abc; idToken=tok",
    )

    creds = runner._extract_nintendo_inline(login, ctx, session=None)
    assert creds == {"NINTENDO_COOKIE": "NASID=abc; idToken=tok"}
    assert login.goto_calls >= 1
