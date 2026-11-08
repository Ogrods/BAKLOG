"""Regression guard for EA Connect navigation and sustained hook auth."""

from __future__ import annotations

import pytest

from auth.runner import _extract_ea
from clients.ea_session import EA_COOKIE_SESSION, EA_DEALS_URL, EA_LOGIN_URL

FIXTURES_DIR = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"


def _owned_batch() -> list[dict]:
    import json

    payload = json.loads((FIXTURES_DIR / "ea_graphql_owned_items.json").read_text(encoding="utf-8"))
    from clients.ea_session import ea_graphql_owned_items

    return ea_graphql_owned_items(payload)


class FakeContext:
    def __init__(self) -> None:
        self.handlers: dict[str, list] = {"request": []}

    def on(self, event: str, handler) -> None:
        self.handlers.setdefault(event, []).append(handler)

    def cookies(self) -> list:
        return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]


class FakePage:
    """Minimal page stand-in that records navigations."""

    def __init__(self, *, start_url: str = EA_LOGIN_URL) -> None:
        self.url = start_url
        self.nav_log: list[str] = []
        self.polls = 0

    def goto(self, url: str, **_k) -> None:
        self.nav_log.append(url)
        self.url = url

    def bring_to_front(self) -> None:
        pass

    def content(self) -> str:
        if "signin.ea.com" in (self.url or ""):
            return "<html>Sign in to your EA account</html>"
        return "<html>deals loaded</html>"

    def wait_for_timeout(self, _ms: int) -> None:
        self.polls += 1
        if self.polls == 1 and "signin" in (self.url or ""):
            self.url = EA_DEALS_URL


def test_extract_ea_navigates_login_once_then_deals(monkeypatch) -> None:
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] >= 2:
            return True, _owned_batch(), {"hook_authenticated": True}
        return False, [], {}

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 2.0)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    page = FakePage()
    creds = _extract_ea(page, FakeContext())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    login_navs = [u for u in page.nav_log if u == EA_LOGIN_URL]
    deals_navs = [u for u in page.nav_log if u == EA_DEALS_URL]
    assert len(login_navs) <= 1
    assert len(deals_navs) <= 1
    assert page.nav_log.count(EA_DEALS_URL) <= 1


def test_extract_ea_does_not_return_on_remid_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook",
        lambda _p: (False, [], {"hook_unauthenticated": True}),
    )
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 0.05)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    page = FakePage(start_url=EA_DEALS_URL)
    with pytest.raises(RuntimeError, match="EA session not confirmed"):
        _extract_ea(page, FakeContext())


def test_extract_ea_returns_after_sustained_hook_auth(monkeypatch) -> None:
    poll = {"n": 0}
    snapshots: list[list] = []

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] >= 2:
            return True, _owned_batch(), {"hook_authenticated": True}
        return True, [], {"hook_authenticated": True}

    def fake_write(owned, **_k):
        snapshots.append(list(owned))

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", fake_write)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 2.0)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    page = FakePage(start_url=EA_DEALS_URL)
    creds = _extract_ea(page, FakeContext())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert poll["n"] >= 2
    assert snapshots and len(snapshots[0]) >= 1


def test_extract_ea_single_poll_with_owned_is_enough(monkeypatch) -> None:
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook",
        lambda _p: (True, _owned_batch(), {"hook_authenticated": True}),
    )
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 2.0)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    page = FakePage(start_url=EA_DEALS_URL)
    page.polls = 0
    creds = _extract_ea(page, FakeContext())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert page.polls <= 1


def test_ensure_ea_deals_ready_skips_renav_and_caps_dwell_on_deals() -> None:
    from clients.ea_session import _ensure_ea_deals_ready

    waits: list[int] = []

    class DealsPage:
        url = EA_DEALS_URL

        def goto(self, *_a, **_k):
            raise AssertionError("should not re-nav when already on deals")

        def wait_for_timeout(self, ms: int) -> None:
            waits.append(ms)

    _ensure_ea_deals_ready(DealsPage(), dwell_ms=1500)
    assert waits == [300]

    waits.clear()
    _ensure_ea_deals_ready(DealsPage(), dwell_ms=0)
    assert waits == []


def test_extract_ea_owned_harvest_budget_skips_long_cascade(monkeypatch) -> None:
    """deals_burst_ok with empty owned must not burn multi-second EaClient/inpage loops."""
    poll = {"n": 0}
    dwells: list[int] = []
    pw_calls = {"n": 0}
    inpage_calls = {"n": 0}
    events: list[str] = []

    class Sess:
        fresh_connect = False

        def emit(self, _ev, payload=None):
            events.append((payload or {}).get("message") or "")

    def fake_drain(_page):
        poll["n"] += 1
        # First poll: nudge path needs signed-in deals URL; return auth burst
        # with entries but no owned rows so harvest runs.
        return True, [], {
            "hook_authenticated": True,
            "hook_entries": 2,
        }

    def fake_ensure(page, *, dwell_ms=2500):
        dwells.append(dwell_ms)

    def fake_pw(_ctx):
        pw_calls["n"] += 1
        return []

    def fake_inpage(_page):
        inpage_calls["n"] += 1
        return []

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session._ensure_ea_deals_ready", fake_ensure)
    monkeypatch.setattr("clients.ea_session.fetch_owned_games_playwright_request", fake_pw)
    monkeypatch.setattr("clients.ea_session.fetch_owned_games_inpage", fake_inpage)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 2.0)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    class NudgePage(FakePage):
        def wait_for_timeout(self, ms: int) -> None:
            # Preserve FakePage login→deals transition, then record harvest dwells.
            super().wait_for_timeout(ms)

    page = NudgePage(start_url=EA_LOGIN_URL)
    creds = _extract_ea(page, FakeContext(), Sess())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    # One PW + one inpage max (no EaClient / no 3x escalating inpage).
    assert pw_calls["n"] <= 1
    assert inpage_calls["n"] <= 1
    assert all(d <= 200 for d in dwells)
    assert any("Waiting for EA library" in m for m in events)
