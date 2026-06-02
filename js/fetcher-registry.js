// Generated from fetchers/registry.py — keep in sync with manifest maps.
// Regenerate: python -c "from fetchers.registry import export_js_registry; export_js_registry()"

export const LIBRARY_STORE_JSON = {
  "steam": "games_steam.json",
  "gog": "games_gog.json",
  "psn": "games_psn.json",
  "epic": "games_epic.json",
  "amazon": "games_amazon.json",
  "nintendo": "games_nintendo.json",
  "itch": "games_itch.json",
  "xbox": "games_xbox.json",
  "battlenet": "games_battlenet.json",
  "ubisoft": "games_ubisoft.json"
};

export const WISHLIST_FETCHER_JSON = {
  "wishlistSteam": "games_wishlist.json",
  "wishlistGog": "games_wishlist_gog.json",
  "wishlistEpic": "games_wishlist_epic.json",
  "wishlistPsn": "games_wishlist_psn.json",
  "wishlistUbisoft": "games_wishlist_ubisoft.json",
  "wishlistXbox": "games_wishlist_xbox.json"
};

export const WISHLIST_FETCHER_META_KEY = {
  "wishlistSteam": "wishlist",
  "wishlistGog": "wishlistGog",
  "wishlistEpic": "wishlistEpic",
  "wishlistPsn": "wishlistPsn",
  "wishlistUbisoft": "wishlistUbisoft",
  "wishlistXbox": "wishlistXbox"
};

export const ENRICH_FETCHER_KEYS = new Set(["hltb", "steamCovers", "steamReviews", "steamTags"]);

export const FETCHER_AUTH_PROVIDER = {
  "steam": "steam",
  "gog": "gog",
  "psn": "psn",
  "epic": "epic",
  "amazon": "amazon",
  "xbox": "xbox",
  "battlenet": "battlenet",
  "ubisoft": "ubisoft",
  "nintendo": "nintendo",
  "itch": "itch",
  "wishlistSteam": "steam",
  "wishlistGog": "gog",
  "wishlistEpic": "epic_wishlist",
  "wishlistPsn": "psn",
  "wishlistUbisoft": "ubisoft",
  "wishlistXbox": "xbox_wishlist",
  "itad": "itad"
};
