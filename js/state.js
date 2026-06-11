export const STORAGE_KEY = 'steam-backlog-personal';
export const PREFS_KEY = 'steam-backlog-ui-prefs';
export const MANUAL_KEY = 'steam-backlog-manual-games';
export const LIBRARY_FIRST_SEEN_KEY = 'steam-backlog-library-first-seen';

export const state = {
  allGames: [],
  personal: {},
  prefs: {},
  sortKey: 'name',
  sortDir: 1,
  pickedKey: null,
  libraryMeta: {
    steam: null, gog: null, psn: null, epic: null, amazon: null,
    xbox: null, battlenet: null, ubisoft: null, nintendo: null, itch: null, humble: null, ea: null,
    wishlist: null, wishlistGog: null, wishlistEpic: null, wishlistPsn: null, wishlistUbisoft: null, wishlistXbox: null, wishlistNintendo: null, wishlistHumble: null,
    itad: null, claims: null, hltb: null,
  },
  claimableFeed: null,
  claimableNow: [],
  crossStoreHiddenKeys: new Set(),
  crossStoreOwnedStores: new Map(),
  /**
   * Map<gameKey, { total: number, perStore: [{store, minutes}] }>
   *
   * For library rows that are the visible representative of a cross-store dedup
   * group (e.g. Steam wins for "Death Stranding" while a PSN sibling is hidden),
   * this holds the SUM of `playtime_minutes` across every entry in that group.
   * Only populated when `state.sessionPrefs.crossStoreDedup` is on so stats
   * don't double-count when dedup is off.
   */
  crossStorePlaytimeByKey: new Map(),
  /** Normalized title names with >0 playtime across any cross-store sibling. */
  playedTitleNorms: new Set(),
  wishlistCrossStoreHiddenKeys: new Set(),
  wishlistCrossStoreOwnedStores: new Map(),
  wishlistGames: [],
  itchGames: [],
  itadByKey: {},
  itadPriceDroppedKeys: new Set(),
  /** Disclosed sponsored/house deal slots (loaded from sponsors.json). */
  sponsoredDeals: [],
  /** v2 feed: id -> creative */
  sponsoredAds: {},
  /** v2 feed: location key -> ordered ad ids */
  adLocations: {},
  dashboardDataReady: false,
  activeView: 'dashboard',
  selectedKeys: new Set(),
  cleanupModeActive: false,
  focusedRowIndex: -1,
  ownedNormNames: new Set(),
  /** Set of String steam appids owned in the library (claim-owned O(1) lookup). */
  ownedSteamAppids: new Set(),
  /** gameKey -> ms epoch when this library row was first observed (0 = silent seed). */
  libraryFirstSeenByKey: {},
  filtersDrawerOpen: false,
  genreChipsExpanded: false,
  _visibleList: null,
  _visibleListView: null,
  /** True while a cross-view drill-in should keep the loading overlay until scroll lands. */
  _drillHideOverlay: false,
  /**
   * Session-scoped prefs — like `prefs` but never persisted to localStorage.
   * Each tab/reload starts fresh with the defaults in loadSessionPrefs().
   *
   * This is the single source of truth for the live filter UI controls
   * (search box, status filter, unplayed/early-access toggles, min-rating
   * and max-hours sliders, dedup, itch hide-non-games). The DOM controls
   * mirror these values; never read filter state directly off the DOM.
   * Use prefs.js::syncFilterDomFromState() after a programmatic write to
   * push the values back into the visible controls.
   */
  sessionPrefs: {
    crossStoreDedup: true,
    itchHideNonGames: true,
    search: "",
    statusFilter: "",
    unplayedOnly: false,
    earlyAccessOnly: false,
    staleOnly: false,
    minRating: 0,
    maxHours: 200,
  },
};

export const CLEANUP_MAX_RATING = 60;
export const CLEANUP_MIN_AGE_MS = 2 * 365.25 * 24 * 60 * 60 * 1000;

/** Pure cleanup-candidate gate shared by table-query (worker) and UI paths. */
export function isCleanupCandidateFromParts({
  explicitBacklog,
  played,
  rating,
  releaseMs,
  now = Date.now(),
}) {
  if (!explicitBacklog) return false;
  if (played) return false;
  if (!(rating > 0 && rating < CLEANUP_MAX_RATING)) return false;
  if (!releaseMs) return false;
  return now - releaseMs >= CLEANUP_MIN_AGE_MS;
}
export const GENRE_CHIP_COLLAPSE_AT = 12;
export const GENRE_ALIASES = { Simulator: 'Simulation', Sport: 'Sports' };
export const ITCH_NON_GAME_CLASSIFICATIONS = new Set(['tool', 'assets', 'asset_pack', 'comic', 'book', 'soundtrack', 'physical_game', 'other']);
export const STATUS_CHIP_DEFS = [
  { key: 'backlog', label: 'Backlog' },
  { key: 'next', label: 'Next' },
  { key: 'playing', label: 'Playing' },
  { key: 'unfinished', label: 'Unfinished' },
  { key: 'live', label: 'Live' },
  { key: 'finished', label: 'Finished' },
  { key: 'skip', label: 'Skip' },
];
// Wishlist statuses share underlying keys with library but are relabeled by
// the row controls (see WISHLIST_STATUS_LABELS in row-templates.js).
export const WISHLIST_STATUS_CHIP_DEFS = [
  { key: 'backlog', label: 'Watching' },
  { key: 'next', label: 'Want it' },
  { key: 'finished', label: 'Bought' },
  { key: 'skip', label: 'Pass' },
];
export const STATUS_FILTER_LABELS = {
  backlog: 'Backlog',
  next: 'Next up',
  playing: 'Playing',
  unfinished: 'Unfinished',
  live: 'Live service',
  finished: 'Finished',
  skip: 'Skip',
  __none__: 'No status',
};
