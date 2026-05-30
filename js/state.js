export const STORAGE_KEY = 'steam-backlog-personal';
export const PREFS_KEY = 'steam-backlog-ui-prefs';
export const MANUAL_KEY = 'steam-backlog-manual-games';

export const state = {
  allGames: [],
  personal: {},
  prefs: {},
  sortKey: 'name',
  sortDir: 1,
  pickedKey: null,
  libraryMeta: { steam: null, gog: null, psn: null, epic: null, amazon: null, nintendo: null, itch: null, wishlist: null },
  crossStoreHiddenKeys: new Set(),
  crossStoreOwnedStores: new Map(),
  wishlistGames: [],
  itchGames: [],
  itadByKey: {},
  activeView: 'dashboard',
  selectedKeys: new Set(),
  cleanupModeActive: false,
  focusedRowIndex: -1,
  ownedNormNames: new Set(),
  filtersDrawerOpen: false,
  genreChipsExpanded: false,
};

export const CLEANUP_MAX_RATING = 60;
export const CLEANUP_MIN_AGE_MS = 2 * 365.25 * 24 * 60 * 60 * 1000;
export const GENRE_CHIP_COLLAPSE_AT = 12;
export const GENRE_ALIASES = { Simulator: 'Simulation', Sport: 'Sports' };
export const ITCH_NON_GAME_CLASSIFICATIONS = new Set(['tool', 'assets', 'comic', 'book', 'soundtrack', 'physical_game', 'other']);
export const STATUS_CHIP_DEFS = [
  { key: 'backlog', label: 'Backlog' },
  { key: 'next', label: 'Next' },
  { key: 'playing', label: 'Playing' },
  { key: 'unfinished', label: 'Unfinished' },
  { key: 'live', label: 'Live' },
  { key: 'finished', label: 'Finished' },
  { key: 'skip', label: 'Skip' },
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
