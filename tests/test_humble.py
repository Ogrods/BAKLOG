import json
from pathlib import Path

from fetchers.fetch_humble import LibraryItem, _build_row, _parse_order_detail, _subproduct_is_game
from fetchers.fetch_humble_wishlist import WishlistItem, _item_from_lookup
from fetchers.fetch_humble_wishlist import _build_row as _build_wishlist_row

ORDER_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "humble_order_detail.json"
LOOKUP_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "humble_wishlist_lookup.json"


def test_subproduct_is_game_heuristics():
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    tpkd = data["tpkd_dict"]
    subs = {s["machine_name"]: s for s in data["subproducts"]}
    assert _subproduct_is_game(subs["sample_game"], tpkd)
    assert not _subproduct_is_game(subs["sample_ebook"], tpkd)
    assert _subproduct_is_game(subs["sample_steam_key"], tpkd)


def test_parse_order_detail_games_only():
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    items = _parse_order_detail(data, include_nongames=False)
    names = {it.name for it in items}
    assert "Sample Game" in names
    assert "Steam Key Game" in names
    assert "Sample Ebook Only" not in names
    steam = next(it for it in items if it.name == "Steam Key Game")
    assert steam.steam_app_id == "123456"
    assert "steampowered.com" in steam.store_url


def test_parse_order_detail_include_nongames():
    data = json.loads(ORDER_FIXTURE.read_text(encoding="utf-8"))
    items = _parse_order_detail(data, include_nongames=True)
    assert any(it.name == "Sample Ebook Only" for it in items)


def test_build_library_row_schema():
    item = LibraryItem(
        machine_name="sample_game",
        name="Sample Game",
        image_url="https://cdn.humblebundle.com/images/icons/sample_game.png",
        store_url="https://www.humblebundle.com/store/sample_game",
        gamekey="AbCdEf",
        redeemed=False,
        steam_app_id=None,
    )
    row = _build_row(item, None)
    assert row["store"] == "humble"
    assert row["id"] == "humble-sample_game"
    assert row["humble_id"] == "sample_game"
    assert "unredeemed key" in row["tags"]


def test_item_from_lookup_fixture():
    data = json.loads(LOOKUP_FIXTURE.read_text(encoding="utf-8"))
    items = [it for it in (_item_from_lookup(o) for o in data["result"]) if it]
    assert len(items) == 2
    titles = {it.title for it in items}
    assert "Hollow Knight" in titles
    assert "Celeste" in titles
    celeste = next(it for it in items if it.title == "Celeste")
    assert celeste.discount_percent == 75
    assert celeste.price == "$4.99"
    assert celeste.store_url == "https://www.humblebundle.com/store/celeste"


def test_item_from_lookup_requires_title_and_machine():
    assert _item_from_lookup({}) is None
    assert _item_from_lookup({"machine_name": "x"}) is None
    assert _item_from_lookup({"human_name": "X"}) is None


def test_build_wishlist_row_schema():
    item = WishlistItem(
        product_id="hollow_knight",
        title="Hollow Knight",
        image_url="https://cdn.humblebundle.com/images/hollow_knight.jpg",
        store_url="https://www.humblebundle.com/store/hollow_knight",
        price="$14.99",
        price_initial="$14.99",
        discount_percent=None,
        currency="USD",
    )
    row = _build_wishlist_row(item, None)
    assert row["store"] == "wishlist"
    assert row["wishlist_store"] == "humble"
    assert row["id"] == "humble-hollow_knight"
    assert row["humble_product_id"] == "hollow_knight"
