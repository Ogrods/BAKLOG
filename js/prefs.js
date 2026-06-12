import { state } from './state.js';
import { prefsStorageKey } from './profiles.js';
import { personalStore } from './personal-store.js';
import { resolveCoopFilterMode } from './table-query.js';
import { migrateColumnPrefs } from './table-columns.js';

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
    btn.setAttribute("aria-checked", on ? "true" : "false");
  });
}

export function loadPrefs() {
  const fallback = {
    picksTab: "topRated", libraryPicksTab: "topRated", itchPicksTab: "topRated", picksCollapsed: false,
    columns: {}, rowHeroBackdrop: true, genreFilters: [], genreFilterMode: "OR", quickWinMaxHours: 15,
    metricsDisabled: [],
    storeFilter: "", wishlistStoreFilter: "", releaseYearFilter: "", picksLimit: 16,
    dealOnSaleOnly: false, dealHistoricalLowOnly: false, dealHideOwned: false,
    dealMinDiscount: 0, dealMaxPrice: 100, viewSorts: {},
    shareAnonStats: false,
    fetcherHealthShowConnected: true, fetcherHealthShowStaleMissing: true,
    autoEnrichOnAdd: true, coopFilterMode: "off", fetcherCollapsed: true,
    itadAutoRefreshIntervalMin: 15,
    claimsAutoRefreshIntervalMin: 120,
    autoFetchOnConnect: true,
    autoFetchStale24h: true,
    connectionNotes: {},
  };
  let merged;
  try { merged = { ...fallback, ...(JSON.parse(localStorage.getItem(prefsStorageKey()) || "{}")) }; } catch { return fallback; }
  if (!["off", "any", "online", "local", "both"].includes(merged.coopFilterMode)) {
    merged.coopFilterMode = merged.coopAny ? "any" : "off";
  }
  delete merged.coopAny;
  // Migrate single stale-only toggle to dual fetcher-health filters.
  if (merged.fetcherHealthShowConnected === undefined || merged.fetcherHealthShowStaleMissing === undefined) {
    if (merged.fetcherHealthStaleOnly === true) {
      merged.fetcherHealthShowConnected = false;
      merged.fetcherHealthShowStaleMissing = true;
    } else {
      merged.fetcherHealthShowConnected = true;
      merged.fetcherHealthShowStaleMissing = true;
    }
  }
  delete merged.fetcherHealthStaleOnly;
  // Migrated to state.sessionPrefs (never persists). If old persisted values
  // are found, drop them so they don't pollute future saves.
  delete merged.crossStoreDedup;
  delete merged.hideSponsoredDeals;
  delete merged.itchHideNonGames;
  delete merged.tagFilters;
  delete merged.tagFilterMode;
  const rawItadMin = Number(merged.itadAutoRefreshIntervalMin);
  if (!Number.isFinite(rawItadMin)) {
    merged.itadAutoRefreshIntervalMin = 15;
  } else {
    const clamped = Math.min(60, Math.max(15, rawItadMin));
    merged.itadAutoRefreshIntervalMin = Math.round(clamped / 5) * 5;
  }
  const rawClaimsMin = Number(merged.claimsAutoRefreshIntervalMin);
  if (!Number.isFinite(rawClaimsMin)) {
    merged.claimsAutoRefreshIntervalMin = 120;
  } else {
    const clamped = Math.min(360, Math.max(30, rawClaimsMin));
    merged.claimsAutoRefreshIntervalMin = Math.round(clamped / 30) * 30;
  }
  if (!merged.connectionNotes || typeof merged.connectionNotes !== 'object' || Array.isArray(merged.connectionNotes)) {
    merged.connectionNotes = {};
  }
  // One-time flip for users whose prefs predate the on-by-default change.
  if (!merged.rowHeroBackdropDefaulted) {
    merged.rowHeroBackdrop = true;
    merged.rowHeroBackdropDefaulted = true;
  }
  migrateColumnPrefs(merged);
  merged.picksCollapsed = merged.picksCollapsed === true;
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
  try {
    localStorage.setItem(prefsStorageKey(), JSON.stringify(state.prefs));
  } catch (err) {
    // Quota exhaustion / private-mode write blocks shouldn't break the UI; the
    // server-side personal doc PUT (via personalStore.notify) remains the
    // durable copy of prefs.
    const quota = err && (err.name === 'QuotaExceededError' || err.code === 22);
    console.warn(`[prefs] localStorage write failed${quota ? ' (quota exceeded)' : ''}`, err);
  }
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
