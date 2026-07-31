"""Battle.net headed-connect session detection (sniffer + in-page probe + cookie fallback)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from auth.connect_extractors import (
    BattleNetGamesAndSubsSniffer,
    _battlenet_probe_via_page,
    extract_battlenet_session,
)


class _FakePage:
    def __init__(self, result: Any, *, url: str = "https://account.battle.net/games") -> None:
        self._result = result
        self.url = url
        self.evaluate_calls = 0

    def evaluate(self, _expr: str, *, timeout: float = 60) -> Any:
        self.evaluate_calls += 1
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class _FakeContext:
    def __init__(self, cookies: list[dict]) -> None:
        self._cookies = cookies
        self.request_handlers: list = []
        self.response_handlers: list = []

    def cookies(self) -> list[dict]:
        return list(self._cookies)

    def on(self, event: str, handler) -> None:
        if event == "request":
            self.request_handlers.append(handler)
        elif event == "response":
            self.response_handlers.append(handler)


SESSION_COOKIES = [
    {"name": "XSRF-TOKEN", "value": "tok%3D%3D", "domain": ".battle.net"},
    {"name": "BA-tassession", "value": "sess", "domain": "account.battle.net"},
]


def test_probe_via_page_true_on_200() -> None:
    page = _FakePage({"ok": True, "status": 200})
    assert _battlenet_probe_via_page(page, xsrf="tok==") is True
    assert page.evaluate_calls == 1


def test_probe_via_page_false_on_401() -> None:
    page = _FakePage({"ok": False, "status": 401})
    assert _battlenet_probe_via_page(page) is False


def test_probe_via_page_false_on_evaluate_error() -> None:
    page = _FakePage(RuntimeError("cdp dead"))
    assert _battlenet_probe_via_page(page) is False


def test_extract_prefers_in_page_probe() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": True, "status": 200})
    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, page)
        probe.assert_not_called()
    assert creds is not None
    assert "BA-tassession=sess" in creds["BATTLENET_COOKIE"]
    assert "XSRF-TOKEN=tok%3D%3D" in creds["BATTLENET_COOKIE"]


def test_extract_falls_back_to_external_probe_when_page_fails() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": False, "status": 401})
    with patch(
        "clients.battlenet_client.probe_session",
        return_value={"modernGames": []},
    ) as probe:
        creds = extract_battlenet_session(ctx, page)
        probe.assert_called_once()
    assert creds is not None
    assert "BATTLENET_COOKIE" in creds


def test_extract_returns_none_when_external_probe_rejects() -> None:
    from clients.battlenet_client import BattleNetAuthError

    ctx = _FakeContext(SESSION_COOKIES)
    page = _FakePage({"ok": False, "status": 401})
    with patch(
        "clients.battlenet_client.probe_session",
        side_effect=BattleNetAuthError("401"),
    ):
        assert extract_battlenet_session(ctx, page) is None


def test_extract_without_page_uses_external_probe() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    with patch(
        "clients.battlenet_client.probe_session",
        return_value={"modernGames": []},
    ) as probe:
        creds = extract_battlenet_session(ctx)
        probe.assert_called_once()
    assert creds is not None


def test_extract_in_page_ok_but_empty_cookies_waits() -> None:
    ctx = _FakeContext([])
    page = _FakePage({"ok": True, "status": 200})
    with patch("clients.battlenet_client.probe_session") as probe:
        assert extract_battlenet_session(ctx, page) is None
        probe.assert_not_called()


def test_sniffer_200_yields_creds_without_in_page_probe() -> None:
    ctx = _FakeContext(SESSION_COOKIES)
    sniffer = BattleNetGamesAndSubsSniffer()
    sniffer.attach(ctx)
    assert ctx.response_handlers

    req = MagicMock()
    req.url = "https://account.battle.net/api/games-and-subs"
    req.headers = {"cookie": "XSRF-TOKEN=tok%3D%3D; BA-tassession=sess"}
    resp = MagicMock()
    resp.url = req.url
    resp.status = 200
    resp.request = req
    ctx.response_handlers[0](resp)

    page = _FakePage({"ok": False, "status": 401})
    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, page, sniffer=sniffer)
        probe.assert_not_called()
        assert page.evaluate_calls == 0
    assert creds is not None
    assert "BA-tassession=sess" in creds["BATTLENET_COOKIE"]


def test_sniffer_cookie_header_used_when_cdp_dump_empty() -> None:
    ctx = _FakeContext([])
    sniffer = BattleNetGamesAndSubsSniffer()
    sniffer.attach(ctx)
    req = MagicMock()
    req.url = "https://account.battle.net/api/games-and-subs?x=1"
    req.headers = {"cookie": "BA-tassession=from-network; XSRF-TOKEN=abc"}
    resp = MagicMock()
    resp.url = req.url
    resp.status = 200
    resp.request = req
    ctx.response_handlers[0](resp)

    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, None, sniffer=sniffer)
        probe.assert_not_called()
    assert creds == {
        "BATTLENET_COOKIE": "BA-tassession=from-network; XSRF-TOKEN=abc"
    }


def test_in_page_ok_uses_sniffed_cookie_when_dump_empty() -> None:
    ctx = _FakeContext([])
    sniffer = BattleNetGamesAndSubsSniffer()
    sniffer.attach(ctx)
    # Sniffer saw the request cookie but response may arrive after probe.
    ctx.request_handlers[0](
        MagicMock(
            url="https://account.battle.net/api/games-and-subs",
            headers={"cookie": "BA-tassession=sniffed"},
        )
    )
    # Mark verified via response without cookie on request object.
    resp = MagicMock()
    resp.url = "https://account.battle.net/api/games-and-subs"
    resp.status = 200
    resp.request = MagicMock(headers={})
    ctx.response_handlers[0](resp)

    page = _FakePage({"ok": True, "status": 200})
    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, page, sniffer=sniffer)
        probe.assert_not_called()
    assert creds == {"BATTLENET_COOKIE": "BA-tassession=sniffed"}


def test_stale_page_fails_live_page_succeeds() -> None:
    from clients.battlenet_client import BattleNetAuthError

    ctx = _FakeContext(SESSION_COOKIES)
    stale = _FakePage({"ok": False, "status": 0}, url="about:blank")
    live = _FakePage({"ok": True, "status": 200}, url="https://account.battle.net/games")
    with patch(
        "clients.battlenet_client.probe_session",
        side_effect=BattleNetAuthError("401"),
    ):
        assert extract_battlenet_session(ctx, stale) is None
    with patch("clients.battlenet_client.probe_session") as probe:
        creds = extract_battlenet_session(ctx, live)
        probe.assert_not_called()
    assert creds is not None
    assert "BATTLENET_COOKIE" in creds


def test_battlenet_live_page_prefers_games_tab() -> None:
    from auth.runner import _battlenet_live_page

    blank = MagicMock(url="about:blank", is_closed=False)
    games = MagicMock(url="https://account.battle.net/games", is_closed=False)
    login = MagicMock(url="https://account.battle.net/login", is_closed=False)
    ctx = MagicMock()
    ctx.pages = [blank, login, games]
    assert _battlenet_live_page(blank, ctx) is games
