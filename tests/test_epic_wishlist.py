"""Unit tests for Epic wishlist GraphQL parsing."""
from __future__ import annotations

import json
from pathlib import Path

from fetch_epic_wishlist import (
    _build_row,
    _signed_out,
    parse_wishlist_sources,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "epic_wishlist_graphql.json"


def test_parse_wishlist_from_graphql_fixture() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    elements = parse_wishlist_sources("", [payload])
    assert len(elements) == 2
    titles = {(el.get("offer") or {}).get("title") for el in elements}
    assert "Test Epic Game" in titles
    assert "Free Epic Title" in titles


def test_build_row_schema() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    el = parse_wishlist_sources("", [payload])[0]
    row = _build_row(el, None)
    assert row is not None
    assert row["store"] == "wishlist"
    assert row["wishlist_store"] == "epic"
    assert row["id"] == "epic-fn:offer-aaa"
    assert row["epic_namespace"] == "fn"
    assert row["epic_offer_id"] == "offer-aaa"
    assert "epicgames.com" in row["store_url"]
    assert row["price"] == "$19.99"


def test_signed_out_login_page() -> None:
    assert _signed_out("", "https://www.epicgames.com/id/login")
    assert _signed_out("", "https://store.epicgames.com/challenge")
    assert not _signed_out("<html>wishlist</html>", "https://store.epicgames.com/en-US/wishlist")
