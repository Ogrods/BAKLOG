"""shared/wishlist_keys.py must build the same ids as js/library-load.js.

The dashboard looks up ITAD prices by ``wishlist:<id>``; a mismatch means a
store's wishlist prices never show up. Rule 6 sync pair.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fetchers.registry import WISHLIST_JSON_BY_KEY
from shared.wishlist_keys import WISHLIST_ID_RULES, steam_appid_for, wishlist_lookup_key

ROOT = Path(__file__).resolve().parents[1]

CASES = [
    ("wishlistSteam", {"appid": 570}, "wishlist:570"),
    ("wishlistSteam", {"id": 620, "appid": 570}, "wishlist:620"),
    ("wishlistGog", {"id": "1207658924"}, "wishlist:gog-1207658924"),
    ("wishlistGog", {"gog_id": 42}, "wishlist:gog-42"),
    ("wishlistEpic", {"id": "epic-ns:off"}, "wishlist:epic-ns:off"),
    ("wishlistEpic", {"epic_namespace": "ns", "epic_offer_id": "off"}, "wishlist:epic-ns:off"),
    ("wishlistPsn", {"psn_product_id": "UP1"}, "wishlist:psn-UP1"),
    ("wishlistUbisoft", {"ubisoft_product_id": "u1"}, "wishlist:ubisoft-u1"),
    ("wishlistXbox", {"xbox_product_id": "9N"}, "wishlist:xbox-9N"),
    ("wishlistNintendo", {"nintendo_product_id": "7001"}, "wishlist:nintendo-7001"),
    ("wishlistHumble", {"humble_product_id": "h1"}, "wishlist:humble-h1"),
    ("wishlistHumble", {"id": "humble-h2", "humble_product_id": "h1"}, "wishlist:humble-h2"),
]


@pytest.mark.parametrize(("key", "row", "expected"), CASES)
def test_lookup_key_matches_frontend_rule(key, row, expected):
    assert wishlist_lookup_key(key, row) == expected


def test_missing_id_fields_yield_none():
    for key in WISHLIST_ID_RULES:
        assert wishlist_lookup_key(key, {"name": "No ids"}) is None
    assert wishlist_lookup_key("wishlistEpic", {"epic_namespace": "ns"}) is None
    assert wishlist_lookup_key("unknownStore", {"id": 1}) is None


def test_rules_cover_every_wishlist_catalog():
    assert set(WISHLIST_ID_RULES) == set(WISHLIST_JSON_BY_KEY)


def test_frontend_templates_unchanged():
    """If library-load.js changes an id template, update wishlist_keys.py too."""
    src = (ROOT / "js" / "library-load.js").read_text(encoding="utf-8")
    body = src[src.index("export function rebuildWishlistFromMetas") :]
    body = body[: body.index("state.wishlistGames")]
    expected = [
        "id: g.id ?? g.appid",
        "id: `gog-${g.id ?? g.gog_id}`",
        "id: g.id ?? `epic-${g.epic_namespace}:${g.epic_offer_id}`",
        "id: g.id ?? `psn-${g.psn_product_id}`",
        "id: g.id ?? `ubisoft-${g.ubisoft_product_id}`",
        "id: g.id ?? `xbox-${g.xbox_product_id}`",
        "id: g.id ?? `nintendo-${g.nintendo_product_id}`",
        "id: g.id ?? `humble-${g.humble_product_id}`",
    ]
    for template in expected:
        assert template in body, template
    assert len(re.findall(r"\bid:\s", body)) == len(expected)
    assert 'store: "wishlist"' in body


def test_steam_appid_for():
    assert steam_appid_for("wishlistSteam", {"appid": "570"}) == 570
    assert steam_appid_for("wishlistGog", {"steam_appid": 1091500}) == 1091500
    assert steam_appid_for("wishlistGog", {"id": "123"}) is None
    assert steam_appid_for("wishlistXbox", {"steam_appid": None}) is None
    assert steam_appid_for("wishlistEpic", {"steam_appid": "abc"}) is None
    assert steam_appid_for("wishlistEpic", {"steam_appid": 0}) is None
