import { state, PREFS_KEY } from './state.js';
import { personalStore } from './personal-store.js';
import { resolveCoopFilterMode } from './table-query.js';

export const COOP_FILTER_LABELS = {
  any: "Any co-op",
  online: "Online co-op",
  local: "Couch co-op",
  both: "Online + couch co-op",
};

export function getCoopFilterMode() {
  return resolveCoopFilterMode(state.prefs);
}

export function setCoopFilterMode(mode) {
  const ok = new Set(["off", "any", "online", "local", "both"]);
  state.prefs.coopFilterMode = ok.has(mode) ? mode : "off";
  delete state.prefs.coopAny;
  savePrefs();
  syncCoopFilterSegmented();
}

export function syncCoopFilterSegmented() {
  const mode = getCoopFilterMode();
  document.querySelectorAll("#coopFilterSegmented .filter-segment").forEach(btn => {
    const on = btn.dataset.coopMode === mode;
    btn.classList.toggle("active", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  });
}

export function loadPrefs() {
  const fallback = { picksTab: "topRated", libraryPicksTab: "topRated", itchPicksTab: "topRated", picksCollapsed: false, showScoreColumn: false, genreFilters: [], genreFilterMode: "OR", quickWinMaxHours: 15, storeFilter: "", wishlistStoreFilter: "", releaseYearFilter: "", picksLimit: 16, tagFilters: [], tagFilterMode: "OR", dealOnSaleOnly: false, dealHistoricalLowOnly: false, dealHideOwned: false, dealMinDiscount: 0, dealMaxPrice: 100, viewSorts: {}, fetcherHealthStaleOnly: false, coopFilterMode: "off" };
  let merged;
  try { merged = { ...fallback, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}")) }; } catch { return fallback; }
  if (!["off", "any", "online", "local", "both"].includes(merged.coopFilterMode)) {
    merged.coopFilterMode = merged.coopAny ? "any" : "off";
  }
  delete merged.coopAny;
  // Migrated to state.sessionPrefs (never persists). If old persisted values
  // are found, drop them so they don't pollute future saves.
  delete merged.crossStoreDedup;
  delete merged.itchHideNonGames;
  return merged;
}

/** Defaults for state.sessionPrefs. These are NOT persisted; each reload starts fresh. */
export function loadSessionPrefs() {
  return {
    crossStoreDedup: true,
    itchHideNonGames: true,
    search: "",
    statusFilter: "",
    unplayedOnly: false,
    earlyAccessOnly: false,
    minRating: 0,
    maxHours: 200,
  };
}

/**
 * Mirror state.sessionPrefs filter values into the corresponding DOM controls.
 *
 * Call this after a programmatic write to state.sessionPrefs.* so the visible
 * filter inputs match the new state. Event handlers don't need to call this
 * because the DOM already reflects the user's input — they just push the
 * value into state.sessionPrefs.
 *
 * Knows about the min-rating and max-hours display labels too so we can stop
 * sprinkling that bookkeeping across every drill-in / pill-remove path.
 */
export function syncFilterDomFromState() {
  const s = state.sessionPrefs || {};
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = String(val ?? "");
  };
  const setChecked = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.checked = !!val;
  };
  setVal("search", s.search || "");
  setVal("statusFilter", s.statusFilter || "");
  setChecked("unplayedOnly", s.unplayedOnly);
  setChecked("earlyAccessOnly", s.earlyAccessOnly);
  const minR = s.minRating || 0;
  setVal("minRating", minR);
  const minRVal = document.getElementById("minRatingVal");
  if (minRVal) minRVal.textContent = String(minR);
  const maxH = s.maxHours == null ? 200 : s.maxHours;
  setVal("maxHours", maxH);
  const maxHVal = document.getElementById("maxHoursVal");
  if (maxHVal) maxHVal.textContent = maxH >= 200 ? "200+" : String(maxH);
}

export function savePrefs() {
  localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
  personalStore.notify();
}

export const VIEW_SORT_DEFAULTS = {
  library: { key: "name", dir: 1 },
  wishlist: { key: "deal_price", dir: 1 },
  itch: { key: "name", dir: 1 },
};

export function getSavedSortForView(view) {
  const def = VIEW_SORT_DEFAULTS[view];
  if (!def) return null;
  const saved = state.prefs.viewSorts && state.prefs.viewSorts[view];
  if (saved && typeof saved.key === "string" && (saved.dir === 1 || saved.dir === -1)) {
    return { key: saved.key, dir: saved.dir };
  }
  return { ...def };
}

export function applySavedSortForView(view) {
  const s = getSavedSortForView(view);
  if (!s) return;
  state.sortKey = s.key;
  state.sortDir = s.dir;
}

export function persistCurrentSort() {
  if (!VIEW_SORT_DEFAULTS[state.activeView]) return;
  if (!state.prefs.viewSorts || typeof state.prefs.viewSorts !== "object") {
    state.prefs.viewSorts = {};
  }
  state.prefs.viewSorts[state.activeView] = { key: state.sortKey, dir: state.sortDir };
  savePrefs();
}
