from __future__ import annotations
from fetchers._authoritative import HUMBLE
from fetchers._base import merge_cached_row

def test_humble_refetch_preserves_cached_enrichment() -> None:
    cached = {'store': 'humble', 'id': 'humble-foo', 'humble_id': 'foo', 'coop_online': True, 'image_source': 'steam_search'}
    fresh = {'store': 'humble', 'id': 'humble-foo', 'humble_id': 'foo', 'name': 'Foo', 'playtime_minutes': 0, 'coop_online': False, 'coop_local': False}
    merged = merge_cached_row(fresh, cached, authoritative=HUMBLE, hltb_updated=False)
    assert merged['coop_online'] is True
    assert merged['image_source'] == 'steam_search'
    assert merged['name'] == 'Foo'