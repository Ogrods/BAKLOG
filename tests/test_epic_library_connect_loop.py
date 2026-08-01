"""Fake-CDP loop test: Epic library connect must not miss redirect on a non-first tab."""

from __future__ import annotations

import json

import pytest

import auth.runner as runner


class _FakeTime:
    def __init__(self, step_s: float = 1.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def time(self) -> float:
        self.t += self.step_s
        return self.t


class _FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.is_closed = False
        self.goto_calls = 0
        self._listeners: dict[str, list] = {}
        self.closed = False

    def on(self, event: str, callback) -> None:
        self._listeners.setdefault(event, []).append(callback)

    def goto(self, _url: str, *, wait_until: str | None = None, timeout: int | None = None) -> None:
        self.goto_calls += 1
        if "id/login" in _url or "__cf_chl_tk" in _url:
            self.url = _url

    def evaluate(self, _fn: str) -> str:
        return ""

    def content(self) -> str:
        if runner.EPIC_REDIRECT_MARKER in (self.url or ""):
            return json.dumps({"authorizationCode": "epic-lib-code-123"})
        return ""

    def wait_for_timeout(self, _ms: int) -> None:
        return None

    def close(self) -> None:
        self.closed = True
        self.is_closed = True


class _FakeContext:
    def __init__(self, pages: list[_FakePage]) -> None:
        self.pages = pages
        self.background_new_pages = 0

    def new_page(self, *, background: bool = False) -> _FakePage:
        if background:
            self.background_new_pages += 1
        page = _FakePage()
        self.pages.append(page)
        return page


def test_epic_library_captures_redirect_on_non_first_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeTime()
    monkeypatch.setattr(runner, "time", clock)

    blank = _FakePage("about:blank")
    redirect = _FakePage(
        "https://www.epicgames.com/id/api/redirect?clientId=x&responseType=code"
    )
    ctx = _FakeContext([blank, redirect])
    primary = _FakePage("https://www.epicgames.com/id/login")
    ctx.pages.insert(1, primary)

    class _FakeEpicClient:
        def __init__(self, *, auth_code: str, cache_dir: str) -> None:
            assert auth_code == "epic-lib-code-123"

        def login(self) -> None:
            return None

    monkeypatch.setattr("clients.epic_client.EpicClient", _FakeEpicClient)
    monkeypatch.setattr("clients.epic_client.default_epic_cache_dir", lambda: "/tmp/epic")

    creds = runner._extract_epic_inline(primary, ctx, session=None)
    assert creds == {"EPIC_AUTH_CODE": "epic-lib-code-123"}


def test_epic_library_inline_does_not_poll_content_on_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: never call content() every poll tick on the Epic ID login page."""
    clock = _FakeTime(step_s=6.0)
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(runner, "SUCCESS_WAIT_SEC", 20.0)
    monkeypatch.setattr(runner, "POLL_SEC", 0.1)

    page = _FakePage("https://www.epicgames.com/id/login")
    content_calls = 0
    original_content = page.content

    def _counting_content() -> str:
        nonlocal content_calls
        content_calls += 1
        return original_content()

    page.content = _counting_content  # type: ignore[method-assign]
    ctx = _FakeContext([page])

    with pytest.raises(RuntimeError, match="Could not capture your Epic authorization code"):
        runner._extract_epic_inline(page, ctx, session=None)

    assert content_calls == 0


def test_epic_library_opens_background_cf_challenge_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeTime(step_s=6.0)
    monkeypatch.setattr(runner, "time", clock)
    monkeypatch.setattr(runner, "SUCCESS_WAIT_SEC", 20.0)
    monkeypatch.setattr(runner, "POLL_SEC", 0.1)

    token = "cf-tok-xyz"
    challenge_url = f"https://www.epicgames.com/id/api/email/exists?__cf_chl_tk={token}"

    page = _FakePage("https://www.epicgames.com/id/login")
    ctx = _FakeContext([page])
    events: list[tuple[str, dict]] = []

    class _Session:
        def emit(self, event: str, data: dict) -> None:
            events.append((event, data))

    class _FakeCfSniffer:
        def __init__(self) -> None:
            self._once = True

        def attach(self, _page) -> None:
            return None

        def drain_challenge_url(self) -> str | None:
            if self._once:
                self._once = False
                return challenge_url
            return None

    monkeypatch.setattr(
        "auth.connect_extractors.EpicEmailExistsCfSniffer",
        _FakeCfSniffer,
    )

    with pytest.raises(RuntimeError, match="Could not capture your Epic authorization code"):
        runner._extract_epic_inline(page, ctx, session=_Session())  # type: ignore[arg-type]

    assert ctx.background_new_pages == 1
    assert any(
        e == "waiting_for_user"
        and runner.EPIC_CF_CHALLENGE_HINT in ((d or {}).get("message") or "")
        for e, d in events
    )
    # Login page must not be content()-polled while waiting.
    assert page.content() == ""
