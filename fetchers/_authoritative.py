from __future__ import annotations
_COMMON_LIBRARY = frozenset({'store', 'id', 'name', 'playtime_minutes', 'last_played', 'header_image', 'library_image', 'release_date', 'genres', 'tags', 'store_url', 'type', 'price', 'price_initial', 'discount_percent', 'currency'})

def library_authoritative(*extra: str) -> frozenset[str]:
    return _COMMON_LIBRARY | frozenset(extra)
GOG = library_authoritative('gog_id', 'source')
EPIC = library_authoritative('epic_namespace', 'epic_catalog_id', 'acquired_at')
PSN = library_authoritative('psn_id', 'np_communication_id', 'title_id', 'concept_id', 'psn_platforms', 'trophy_progress', 'psn_trophies_earned', 'psn_trophies_total', 'psn_has_platinum', 'psn_platinum_earned', 'first_played', 'play_count')
AMAZON = library_authoritative('amazon_id', 'amazon_entitlement_id', 'amazon_adg_id', 'asin', 'product_line', 'publisher', 'source')
XBOX = library_authoritative('xbox_title_id', 'trophy_progress', 'xbox_gamerscore_current', 'xbox_gamerscore_total')
BATTLENET = library_authoritative('battlenet_id')
UBISOFT = library_authoritative('ubisoft_id')
NINTENDO = library_authoritative('nintendo_id', 'application_id', 'vgc_id', 'nintendo_platform', 'nintendo_apparent_platform', 'nintendo_icon_url_standard', 'nintendo_icon_sizes', 'nintendo_device_type', 'nintendo_content_type', 'nintendo_is_dlc', 'publisher', 'nintendo_is_lending', 'nintendo_is_partial_lending', 'nintendo_lending_expire', 'nintendo_has_application', 'nintendo_has_addon_contents', 'nintendo_has_upgrade', 'nintendo_has_nx_application', 'nintendo_has_nx_addon_contents', 'nintendo_has_ounce_application', 'nintendo_has_ounce_addon_contents', 'nintendo_contains_released', 'nintendo_ownership_source', 'nintendo_transaction_name')
HUMBLE = library_authoritative('humble_id', 'humble_gamekey', 'humble_steam_app_id')
EA = library_authoritative('ea_id', 'ea_offer_id', 'ea_game_slug')