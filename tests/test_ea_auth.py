from unittest.mock import MagicMock

import pytest

from auth.runner import AuthSession, _extract_ea
from clients.ea_session import EA_COOKIE_SESSION


def test_extract_ea_returns_bearer_token(monkeypatch):
    monkeypatch.setattr("clients.ea_session.probe_ea_token", lambda _t, _c: {"ok": True})
    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {}))
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    handlers = []

    class Ctx:
        def on(self, event, handler):
            if event == "request":
                handlers.append(handler)

        def cookies(self):
            return []

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            for h in handlers:
                h(
                    MagicMock(
                        url="https://service-aggregation-layer.juno.ea.com/graphql",
                        headers={"Authorization": "Bearer connect-token"},
                    )
                )

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_PROFILE"] == "ready"
    assert creds["EA_BEARER_TOKEN"] == "connect-token"


def test_extract_ea_apq_fallback_bearer_waits_for_cookie(monkeypatch):
    poll = {"n": 0}

    def fake_probe(_t, _c):
        return {"ok": True, "library_via_browser": True}

    def fake_drain(_page):
        poll["n"] += 1
        return (True, [], {"hook_authenticated": True})

    monkeypatch.setattr("clients.ea_session.probe_ea_token", fake_probe)
    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    handlers = []

    class Ctx:
        def on(self, event, handler):
            if event == "request":
                handlers.append(handler)

        def cookies(self):
            return []

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            for h in handlers:
                h(
                    MagicMock(
                        url="https://service-aggregation-layer.juno.ea.com/graphql",
                        headers={"Authorization": "Bearer apq-fallback"},
                    )
                )

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert poll["n"] >= 2


def test_extract_ea_returns_cookie_session_from_browser_hook(monkeypatch):
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] >= 2:
            return (True, [], {"hook_authenticated": True})
        return (True, [], {"hook_authenticated": True})

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_PROFILE"] == "ready"
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION


def test_extract_ea_remid_alone_does_not_connect(monkeypatch):
    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {"hook_unauthenticated": True})
    )
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 0.05)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>session expired</html>"

        def wait_for_timeout(self, _ms):
            pass

    with pytest.raises(RuntimeError, match="EA session not confirmed"):
        _extract_ea(Page(), Ctx())


def test_extract_ea_blip_auth_resets_on_unauthenticated(monkeypatch):
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] == 1:
            return (True, [], {"hook_authenticated": True})
        return (False, [], {"hook_unauthenticated": True})

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 0.05)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    with pytest.raises(RuntimeError, match="EA session not confirmed"):
        _extract_ea(Page(), Ctx())


def test_extract_ea_writes_connect_snapshot(tmp_path, monkeypatch):
    snapshots = []

    def fake_write(owned, **_k):
        snapshots.append(list(owned))

    monkeypatch.setattr(
        "clients.ea_session.drain_ea_graphql_hook",
        lambda _p: (True, [{"originOfferId": "1", "product": {"name": "Game"}}], {}),
    )
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", fake_write)

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert snapshots and snapshots[0][0]["originOfferId"] == "1"


def test_extract_ea_mixed_hook_batch_still_counts_auth(monkeypatch):
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        return (True, [], {"hook_authenticated": True, "hook_unauthenticated": True})

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)

    class Ctx:
        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            self.url = "https://www.ea.com/sales/deals"

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert poll["n"] >= 2


def test_extract_ea_deals_hook_burst_single_poll_succeeds(monkeypatch):
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] == 1:
            return (False, [], {"hook_entries": 0})
        return (True, [], {"hook_entries": 21, "hook_authenticated": True, "hook_unauthenticated": False})

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "clients.ea_session.probe_ea_token", lambda *_a, **_k: {"ok": False, "error": "PersistedQueryNotFound"}
    )

    class Ctx:
        _proc = MagicMock(poll=MagicMock(return_value=None))
        _ws_dead = False

        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "abc", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            self.url = "https://www.ea.com/sales/deals"

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    creds = _extract_ea(Page(), Ctx())
    assert creds["EA_BEARER_TOKEN"] == EA_COOKIE_SESSION
    assert poll["n"] >= 2


def test_extract_ea_browser_closed_before_auth_raises(monkeypatch):
    from auth.cdp_browser import ConnectBrowserClosed

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", lambda _p: (False, [], {"hook_entries": 0}))
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)

    class Ctx:
        _proc = MagicMock(poll=MagicMock(return_value=0))
        _ws_dead = True

        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return []

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, *_a, **_k):
            pass

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    with pytest.raises(ConnectBrowserClosed):
        _extract_ea(Page(), Ctx())


def test_extract_ea_fresh_reconnect_requires_signin_before_deals_burst(monkeypatch):
    poll = {"n": 0}

    def fake_drain(_page):
        poll["n"] += 1
        if poll["n"] == 1:
            return (False, [], {"hook_entries": 0})
        return (True, [], {"hook_entries": 21, "hook_authenticated": True, "hook_unauthenticated": False})

    monkeypatch.setattr("clients.ea_session.drain_ea_graphql_hook", fake_drain)
    monkeypatch.setattr("clients.ea_session.install_ea_graphql_hook", lambda _c: None)
    monkeypatch.setattr("clients.ea_session.ensure_ea_graphql_hook", lambda _p: None)
    monkeypatch.setattr("clients.ea_session.write_ea_connect_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr("auth.runner.SUCCESS_WAIT_SEC", 0.05)
    monkeypatch.setattr("auth.runner.POLL_SEC", 0.01)

    class Ctx:
        _proc = MagicMock(poll=MagicMock(return_value=None))
        _ws_dead = False

        def on(self, *_a, **_k):
            pass

        def cookies(self):
            return [{"name": "remid", "value": "stale", "domain": ".ea.com"}]

    class Page:
        url = "https://www.ea.com/sales/deals"

        def goto(self, url, *_a, **_k):
            self.url = url

        def bring_to_front(self):
            pass

        def content(self):
            return "<html>deals</html>"

        def wait_for_timeout(self, _ms):
            pass

    session = AuthSession("test", "ea", fresh_connect=True)
    with pytest.raises(RuntimeError, match="not confirmed"):
        _extract_ea(Page(), Ctx(), session=session)
    assert poll["n"] >= 2
