// Dashboard drill-down helpers: click handlers that route from dashboard widgets into the filtered library/itch views.
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { savePrefs, setCoopFilterMode, syncFilterDomFromState } from './prefs.js';
import { refreshFilterUI, renderGenreChips, renderStoreChips, switchView } from './filters-ui.js';
import { invalidateTableCache, setPendingScrollTarget } from './table-ui.js';
import { HLTB_BUCKETS } from './dashboard-shared.js';

export /** Reset every active library filter except cross-store dedup before drilling. */
function dashResetLibraryFiltersExceptDedup() {
  const sp = state.sessionPrefs;
  sp.search = "";
  sp.statusFilter = "";
  sp.unplayedOnly = false;
  sp.earlyAccessOnly = false;
  sp.minRating = 0;
  sp.maxHours = 200;
  setCoopFilterMode('off');
  state.prefs.storeFilter = "";
  state.prefs.wishlistStoreFilter = "";
  state.prefs.releaseYearFilter = "";
  state.prefs.hltbBucket = null;
  state.prefs.genreFilters = [];
  state.cleanupModeActive = false;
  syncFilterDomFromState();
}

/**
 * Land a dashboard drill-in just above the search bar (toolbar section).
 * Scroll is deferred until picks/summary layout settles.
 */
export function scrollDrillResultsIntoView() {
  setPendingScrollTarget({ kind: "toolbar", smooth: false });
}

export function dashDrillStore(store) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
}

export function dashDrillStatus(status) {
  dashResetLibraryFiltersExceptDedup();
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
}

export function dashDrillStoreStatus(store, status) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
}

export function dashFinishDrillToLibrary() {
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
  renderGenreChips();
  refreshFilterUI();
}

export function dashSetReleaseYear(value) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.releaseYearFilter = value || "";
  dashFinishDrillToLibrary();
}

export function dashDrillHltbBucket(idx) {
  if (idx == null || !HLTB_BUCKETS[idx]) return;
  dashResetLibraryFiltersExceptDedup();
  state.sessionPrefs.maxHours = 200;
  syncFilterDomFromState();
  state.prefs.hltbBucket = idx;
  dashFinishDrillToLibrary();
}

export function dashDrillMinRating(minRating) {
  dashResetLibraryFiltersExceptDedup();
  state.sessionPrefs.minRating = +minRating || 0;
  syncFilterDomFromState();
  dashFinishDrillToLibrary();
}

export function dashDrillGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderGenreChips();
  refreshFilterUI();
}

export function dashDrillItchGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("itch");
  renderGenreChips();
  refreshFilterUI();
}

export function dashDrillCoop({ online = false, local = false, any = false } = {}) {
  let mode = "off";
  if (any) mode = "any";
  else if (online && local) mode = "both";
  else if (online) mode = "online";
  else if (local) mode = "local";
  setCoopFilterMode(mode);
  state.sessionPrefs.statusFilter = "";
  syncFilterDomFromState();
  state.prefs.storeFilter = "";
  savePrefs();
  invalidateTableCache();
  setPendingScrollTarget({ kind: "toolbar" });
  if (state.activeView !== "library") switchView("library");
  renderStoreChips();
  refreshFilterUI({ force: true });
}
