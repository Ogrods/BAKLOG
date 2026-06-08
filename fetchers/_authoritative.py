"""Per-store authoritative field sets for ``merge_cached_row``.

Fetcher-owned fields are overwritten from the fresh API row; everything else
(Steam reviews, HLTB when not refreshed, ``hltb_id``, etc.) is preserved from
the on-disk cache.
"""

from __future__ import annotations

_COMMON_LIBRARY = frozenset({
    "store",
    "id",
    "name",
    "playtime_minutes",
    "last_played",
    "header_image",
    "library_image",
    "release_date",
    "genres",
    "tags",
    "store_url",
    "type",
    "price",
    "price_initial",
    "discount_percent",
    "currency",
})


def library_authoritative(*extra: str) -> frozenset[str]:
    return _COMMON_LIBRARY | frozenset(extra)


GOG = library_authoritative("gog_id", "source")
EPIC = library_authoritative("epic_namespace", "epic_catalog_id")
PSN = library_authoritative(
    "psn_id",
    "np_communication_id",
    "title_id",
    "concept_id",
    "psn_platforms",
    "trophy_progress",
    "psn_trophies_earned",
    "psn_trophies_total",
    "psn_has_platinum",
    "psn_platinum_earned",
    "first_played",
)
AMAZON = library_authoritative(
    "amazon_id",
    "amazon_entitlement_id",
    "amazon_adg_id",
    "asin",
    "product_line",
    "publisher",
    "source",
)
XBOX = library_authoritative(
    "xbox_title_id",
    "trophy_progress",
    "xbox_gamerscore_current",
    "xbox_gamerscore_total",
)
BATTLENET = library_authoritative("battlenet_id")
UBISOFT = library_authoritative("ubisoft_id")
NINTENDO = library_authoritative("nintendo_id")
HUMBLE = library_authoritative(
    "humble_id",
    "humble_gamekey",
    "humble_steam_app_id",
)
EA = library_authoritative("ea_id", "ea_offer_id", "ea_game_slug")
