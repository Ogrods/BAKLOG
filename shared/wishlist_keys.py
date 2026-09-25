"""ITAD lookup keys for wishlist rows.

Sync pair: js/library-load.js ``rebuildWishlistFromMetas()``. The frontend reads
prices from ``itad_prices.json`` by ``gameKey(g)`` = ``wishlist:<id>``, where
``<id>`` is built by the per-store rules below. Any drift here means prices for
that store silently never appear in the dashboard.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Row = dict[str, Any]


def _first(row: Row, *fields: str) -> Any:
    for field in fields:
        value = row.get(field)
        if value is not None:
            return value
    return None


def _prefixed(prefix: str, field: str) -> Callable[[Row], Any]:
    def build(row: Row) -> Any:
        if row.get("id") is not None:
            return row["id"]
        value = row.get(field)
        return None if value is None else f"{prefix}-{value}"

    return build


def _gog(row: Row) -> Any:
    value = _first(row, "id", "gog_id")
    return None if value is None else f"gog-{value}"


def _epic(row: Row) -> Any:
    if row.get("id") is not None:
        return row["id"]
    ns, offer = row.get("epic_namespace"), row.get("epic_offer_id")
    if ns is None or offer is None:
        return None
    return f"epic-{ns}:{offer}"


WISHLIST_ID_RULES: dict[str, Callable[[Row], Any]] = {
    "wishlistSteam": lambda row: _first(row, "id", "appid"),
    "wishlistGog": _gog,
    "wishlistEpic": _epic,
    "wishlistPsn": _prefixed("psn", "psn_product_id"),
    "wishlistUbisoft": _prefixed("ubisoft", "ubisoft_product_id"),
    "wishlistXbox": _prefixed("xbox", "xbox_product_id"),
    "wishlistNintendo": _prefixed("nintendo", "nintendo_product_id"),
    "wishlistHumble": _prefixed("humble", "humble_product_id"),
}


def wishlist_row_id(fetcher_key: str, row: Row) -> str | None:
    rule = WISHLIST_ID_RULES.get(fetcher_key)
    if rule is None:
        return None
    value = rule(row)
    return None if value is None else str(value)


def wishlist_lookup_key(fetcher_key: str, row: Row) -> str | None:
    row_id = wishlist_row_id(fetcher_key, row)
    return None if row_id is None else f"wishlist:{row_id}"


def steam_appid_for(fetcher_key: str, row: Row) -> int | None:
    """Steam app id usable for an exact ITAD lookup, if the row has one."""
    raw = _first(row, "appid", "id") if fetcher_key == "wishlistSteam" else row.get("steam_appid")
    try:
        appid = int(raw)
    except (TypeError, ValueError):
        return None
    return appid if appid > 0 else None
