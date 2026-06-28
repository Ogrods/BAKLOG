from __future__ import annotations
from auth.connect_extractors import DeferredGraphqlResponseSniffer, build_epic_wishlist_graphql_sniffer

class _FakeResponse:

    def __init__(self, url: str, payload: dict, *, status: int=200) -> None:
        self.url = url
        self.status = status
        self._payload = payload

    def json(self) -> dict:
        return self._payload

def test_deferred_graphql_sniffer_parses_on_drain() -> None:
    sniffer = DeferredGraphqlResponseSniffer(url_match=lambda u: 'graphql' in u, accept=lambda p: bool(p.get('ok')))
    sniffer._pending.append(_FakeResponse('https://x/graphql', {'ok': True}))
    assert sniffer.drain() is True
    assert sniffer.success is True

def test_epic_wishlist_sniffer_accepts_wishlist_payload() -> None:
    sniffer = build_epic_wishlist_graphql_sniffer()
    payload = {'data': {'Wishlist': {'wishlistItems': {'elements': []}}}}
    sniffer._pending.append(_FakeResponse('https://store.epicgames.com/graphql', payload))
    assert sniffer.drain() is True