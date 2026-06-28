import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from clients.ea_client import EaAuthError
from clients.ea_session import (
    DEFAULT_TRIGGER_URLS,
    EA_COOKIE_SESSION,
    EA_SESSION_COOKIE,
    _ea_session_failure,
    drain_ea_graphql_hook,
    ea_graphql_authenticated,
    ea_graphql_owned_items,
    is_ea_login_page,
    normalize_bearer,
    probe_ea_token,
    sniff_ea_bearer,
)


def test_ea_session_failure_remind_without_gql_is_expired():
    stats = {"graphql_requests_seen": 0, "browser_auth_ok": False, "login_page": False}
    cookies = [{"name": EA_SESSION_COOKIE, "value": "x" * 20}]
    with pytest.raises(EaAuthError, match="session expired"):
        _ea_session_failure(stats, cookies)


def test_ea_session_failure_hook_unauth_is_expired():
    stats = {"graphql_requests_seen": 12, "hook_unauthenticated": True, "login_page": False}
    with pytest.raises(EaAuthError, match="session expired"):
        _ea_session_failure(stats, [])


def test_normalize_bearer_strips_prefix():
    assert normalize_bearer("Bearer abc.def") == "abc.def"
    assert normalize_bearer("abc") == "abc"
    assert normalize_bearer("") is None


def test_is_ea_login_page_detects_signin_url():
    assert is_ea_login_page("", "https://signin.ea.com/p/juno/login")
    assert not is_ea_login_page("<html>deals</html>", "https://www.ea.com/sales/deals")


def test_probe_ea_token_cookie_mode_requires_browser():
    out = probe_ea_token(EA_COOKIE_SESSION, [{"name": "remid", "value": "x"}])
    assert out["ok"] is False
    assert "browser" in (out.get("error") or "").lower()


def test_ea_graphql_authenticated_me():
    assert ea_graphql_authenticated({"data": {"me": {"id": "1"}}}) is True
    assert ea_graphql_authenticated({"errors": [{"message": "Not authenticated."}]}) is False


def test_probe_ea_token_ok(monkeypatch):

    class Client:
        _cookie_mode = False

        def probe_owned_games(self):
            return None

    monkeypatch.setattr("clients.ea_session.EaClient", lambda *_a, **_k: Client())
    out = probe_ea_token("tok")
    assert out["ok"] is True


def test_probe_ea_token_falls_back_when_owned_apq_missing(monkeypatch):

    class Client:
        _cookie_mode = False

        def probe_owned_games(self):
            raise EaAuthError('EA GraphQL HTTP 400: {"errors":[{"message":"PersistedQueryNotFound"}]}')

        def probe_user_subscription(self):
            return None

    monkeypatch.setattr("clients.ea_session.EaClient", lambda *_a, **_k: Client())
    out = probe_ea_token("tok")
    assert out["ok"] is True
    assert out.get("library_via_browser") is True


def test_sniff_ea_bearer_from_request_handler(monkeypatch):
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {}))
    monkeypatch.setattr("clients.ea_session.probe_ea_token", lambda _t, _c: {"ok": True})
    handlers = []

    class Ctx:
        def on(self, event, handler):
            if event == "request":
                handlers.append(handler)

        def cookies(self):
            return [{"name": "sid", "value": "1", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            for h in handlers:
                h(
                    MagicMock(
                        url="https://service-aggregation-layer.juno.ea.com/graphql?x=1",
                        headers={"authorization": "Bearer sniffed-token"},
                    )
                )

        def wait_for_timeout(self, _ms):
            pass

        def content(self):
            return "<html>deals</html>"

    result = sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=2)
    assert result.token == "sniffed-token"
    assert result.debug["token_captured"] is True


def test_sniff_cookie_session_when_browser_hook_authenticated(monkeypatch):
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook",
        lambda _p: (True, [], {"browser_auth_ok": True, "hook_authenticated": True}),
    )

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            pass

        def content(self):
            return "<html>deals</html>"

    result = sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=2)
    assert result.token == EA_COOKIE_SESSION
    assert result.debug["browser_auth_ok"] is True


def test_sniff_login_page_raises_auth_error():

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return []

    class Page:
        url = "https://signin.ea.com/login"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            pass

        def content(self):
            return "<html>Sign in to your EA account</html>"

    with pytest.raises(EaAuthError, match="sign-in"):
        sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=1)


def test_sniff_unauthenticated_hook_raises_auth_error(monkeypatch):
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {"hook_unauthenticated": True})
    )

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            pass

        def content(self):
            return "<html>deals loaded</html>"

    with pytest.raises(EaAuthError, match="session expired"):
        sniff_ea_bearer(Ctx(), Page(), trigger_urls=(DEFAULT_TRIGGER_URLS[0],), timeout_s=1)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_ea_graphql_owned_items_extracts_rows():
    payload = _load_fixture("ea_graphql_owned_items.json")
    items = ea_graphql_owned_items(payload)
    assert len(items) == 3
    assert items[0]["originOfferId"] == "OFW-TEST-001"


def test_ea_graphql_owned_items_empty_when_missing():
    assert ea_graphql_owned_items({}) == []
    assert ea_graphql_owned_items({"data": {"me": {}}}) == []


def test_fetch_owned_games_inpage_paginates():
    from clients.ea_session import fetch_owned_games_inpage

    owned_payload = _load_fixture("ea_graphql_owned_items.json")
    calls = {"n": 0}

    class Page:
        def evaluate(self, script):
            calls["n"] += 1
            if calls["n"] == 1:
                payload = dict(owned_payload)
                me_owned = dict(payload["data"]["me"]["ownedGameProducts"])
                me_owned["next"] = "page-2"
                payload["data"] = {"me": {"ownedGameProducts": me_owned}}
                return {"status": 200, "payload": payload}
            page2 = _load_fixture("ea_graphql_owned_items.json")
            extra = dict(page2["data"]["me"]["ownedGameProducts"]["items"][0])
            extra["originOfferId"] = "OFW-TEST-004"
            extra["id"] = "item-004"
            payload = {"data": {"me": {"ownedGameProducts": {"next": None, "items": [extra]}}}}
            return {"status": 200, "payload": payload}

    items = fetch_owned_games_inpage(Page())
    assert calls["n"] == 2
    assert len(items) == 4
    assert {i["originOfferId"] for i in items} == {"OFW-TEST-001", "OFW-TEST-002", "OFW-TEST-003", "OFW-TEST-004"}


def test_fetch_owned_games_playwright_request_paginates():
    from clients.ea_session import fetch_owned_games_playwright_request

    owned_payload = _load_fixture("ea_graphql_owned_items.json")
    calls = {"n": 0}

    class Resp:
        def __init__(self, payload):
            self.status = 200
            self._payload = payload

        def json(self):
            return self._payload

    class Request:
        def post(self, url, headers=None, data=None):
            calls["n"] += 1
            if calls["n"] == 1:
                payload = dict(owned_payload)
                me_owned = dict(payload["data"]["me"]["ownedGameProducts"])
                me_owned["next"] = "page-2"
                payload["data"] = {"me": {"ownedGameProducts": me_owned}}
                return Resp(payload)
            page2 = _load_fixture("ea_graphql_owned_items.json")
            extra = dict(page2["data"]["me"]["ownedGameProducts"]["items"][0])
            extra["originOfferId"] = "OFW-TEST-004"
            extra["id"] = "item-004"
            return Resp({"data": {"me": {"ownedGameProducts": {"next": None, "items": [extra]}}}})

    class Ctx:
        request = Request()

    items = fetch_owned_games_playwright_request(Ctx())
    assert calls["n"] == 2
    assert len(items) == 4


def test_fetch_owned_games_inpage_unauthenticated_raises():
    from clients.ea_session import fetch_owned_games_inpage

    class Page:
        def evaluate(self, script):
            return {"status": 200, "payload": {"errors": [{"message": "User is not authenticated"}]}}

    with pytest.raises(EaAuthError, match="not authenticated"):
        fetch_owned_games_inpage(Page())


def test_drain_ea_graphql_hook_merges_auth_and_owned(monkeypatch):
    owned_payload = _load_fixture("ea_graphql_owned_items.json")
    me_payload = _load_fixture("ea_graphql_me_authenticated.json")
    unauth_payload = _load_fixture("ea_graphql_not_authenticated.json")
    monkeypatch.setattr(
        "clients.ea_session.read_captured_ea_graphql",
        lambda _p: [{"payload": me_payload}, {"payload": owned_payload}, {"payload": unauth_payload}],
    )
    auth_ok, owned, stats = drain_ea_graphql_hook(object())
    assert auth_ok is True
    assert len(owned) == 3
    assert stats["hook_authenticated"] is True
    assert stats["hook_unauthenticated"] is True
    assert stats["hook_owned_items"] == 3


def test_drain_ea_graphql_hook_unauthenticated_only(monkeypatch):
    monkeypatch.setattr(
        "clients.ea_session.read_captured_ea_graphql",
        lambda _p: [{"payload": _load_fixture("ea_graphql_not_authenticated.json")}],
    )
    auth_ok, owned, stats = drain_ea_graphql_hook(object())
    assert auth_ok is False
    assert owned == []
    assert stats["hook_unauthenticated"] is True


def test_read_ea_connect_snapshot_requires_owned_and_fresh(tmp_path, monkeypatch):
    from clients.ea_session import CONNECT_SNAPSHOT_TTL_SEC, read_ea_connect_snapshot, write_ea_connect_snapshot

    snap_path = tmp_path / "ea" / "connect_snapshot.json"
    monkeypatch.setattr("clients.ea_session.ea_connect_snapshot_path", lambda: snap_path)
    assert read_ea_connect_snapshot() is None
    write_ea_connect_snapshot([], browser_auth_ok=True)
    auth_only = read_ea_connect_snapshot()
    assert auth_only is not None
    assert auth_only["owned_items"] == []
    write_ea_connect_snapshot([{"originOfferId": "1", "product": {"name": "Game"}}], browser_auth_ok=True)
    data = read_ea_connect_snapshot()
    assert data is not None
    assert len(data["owned_items"]) == 1
    old = json.loads(snap_path.read_text(encoding="utf-8"))
    old["captured_at"] = "2000-01-01T00:00:00+00:00"
    snap_path.write_text(json.dumps(old), encoding="utf-8")
    assert read_ea_connect_snapshot(max_age_sec=CONNECT_SNAPSHOT_TTL_SEC) is None


def test_capture_ea_browser_session_success(monkeypatch):
    from clients.ea_session import capture_ea_browser_session

    owned_payload = _load_fixture("ea_graphql_owned_items.json")
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook",
        lambda _p: (True, ea_graphql_owned_items(owned_payload), {"hook_authenticated": True}),
    )
    clock = {"now": 1000.0}
    monkeypatch.setattr("clients.ea_session.time.time", lambda: clock["now"])

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            clock["now"] += _ms / 1000.0

        def content(self):
            return "<html>deals</html>"

    result = capture_ea_browser_session(Ctx(), Page(), timeout_s=45)
    assert result.token == EA_COOKIE_SESSION
    assert len(result.owned_items) >= 1
    assert result.debug.get("browser_auth_ok") is True


def test_capture_ea_browser_session_login_page_raises(monkeypatch):
    from clients.ea_session import capture_ea_browser_session

    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {}))
    tick = {"t": 0.0}
    monkeypatch.setattr("clients.ea_session.time.time", lambda: tick.__setitem__("t", tick["t"] + 5) or tick["t"])

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return []

    class Page:
        url = "https://signin.ea.com/p/juno/login"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            pass

        def content(self):
            return "<html>Sign in to your EA account</html>"

    with pytest.raises(EaAuthError, match="sign-in"):
        capture_ea_browser_session(Ctx(), Page(), timeout_s=5)


def test_fetch_owned_games_browser_merges_batches(monkeypatch, tmp_path):
    from clients.ea_session import fetch_owned_games_browser

    batch_a = [{"originOfferId": "a", "product": {"name": "A"}}]
    batch_b = [{"originOfferId": "b", "product": {"name": "B"}}]
    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", lambda _p: (True, batch_a + batch_b, {}))
    monkeypatch.setattr("clients.ea_session.fetch_owned_games_inpage", lambda _p, **_k: [])
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    tick = {"t": 0.0}
    monkeypatch.setattr("clients.ea_session.time.time", lambda: tick.__setitem__("t", tick["t"] + 5) or tick["t"])

    class Ctx:
        pages = []

        def new_page(self):
            return Page()

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def wait_for_timeout(self, _ms):
            pass

    class Cm:
        def __enter__(self):
            return Ctx()

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr("clients.ea_session.launch_ea_profile", lambda *_a, **_k: Cm())
    owned = fetch_owned_games_browser(tmp_path, headless=True)
    assert len(owned) == 2
    assert {i["originOfferId"] for i in owned} == {"a", "b"}
