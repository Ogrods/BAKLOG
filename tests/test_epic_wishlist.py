from __future__ import annotations
import json
from pathlib import Path
from fetchers.fetch_epic_wishlist import _build_row, parse_wishlist_sources
FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'epic_wishlist_graphql.json'

def test_parse_wishlist_from_graphql_fixture() -> None:
    payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
    elements = parse_wishlist_sources('', [payload])
    assert len(elements) == 2

def test_parse_wishlist_from_dehydrated_html() -> None:
    html = '{"state":{"data":{"Wishlist":{"wishlistItems":{"elements":[{"id":"wish-1","offerId":"offer-aaa","namespace":"ns-1"}]}}},"status":"success"},"queryKey":["getWishlist",["accountId","acct"],"hash"]},{"state":{"data":[{"Catalog":{"catalogOffer":{"title":"Test Epic Game","id":"offer-aaa","namespace":"ns-1","productSlug":"test-epic-game","keyImages":[],"price":{"totalPrice":{"discountPrice":1999,"originalPrice":3999,"currencyCode":"USD","fmtPrice":{"originalPrice":"$39.99","discountPrice":"$19.99"}}}}}}}]}}'
    elements = parse_wishlist_sources(html, [])
    assert len(elements) == 1
    assert (elements[0].get('offer') or {}).get('title') == 'Test Epic Game'

def test_build_row_schema() -> None:
    payload = json.loads(FIXTURE.read_text(encoding='utf-8'))
    el = parse_wishlist_sources('', [payload])[0]
    row = _build_row(el, None)
    assert row is not None
    assert row['store'] == 'wishlist'
    assert row['wishlist_store'] == 'epic'
    assert row['id'] == 'epic-fn:offer-aaa'
    assert row['epic_namespace'] == 'fn'
    assert row['epic_offer_id'] == 'offer-aaa'
    assert 'epicgames.com' in row['store_url']
    assert row['price'] == '$19.99'