// Dashboard drill-down helpers: click handlers that route from dashboard widgets into the filtered library/itch views.
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { savePrefs, setCoopFilterMode, syncFilterDomFromState } from './prefs.js';
import { refreshFilterUI, renderGenreChips, renderStoreChips, switchView } from './filters-ui.js';
import { invalidateTableCache, setPendingScrollTarget } from './table-ui.js';
import { applyPicksCollapsedState } from './picks-ui.js';
import { HLTB_BUCKETS } from './dashboard-shared.js';

/** Collapse picks on category drill so filtered rows stay in view after toolbar scroll. */
function collapsePicksForDrill() {
  if (state.prefs.picksCollapsed === true) return;
  state.prefs.picksCollapsed = true;
  applyPicksCollapsedState();
}

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

export function dashDrillStore(store) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
}

export function dashDrillStatus(status) {
  dashResetLibraryFiltersExceptDedup();
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
}

export function dashDrillStoreStatus(store, status) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
}

export function dashFinishDrillToLibrary() {
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderStoreChips();
  renderGenreChips();
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
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("library");
  renderGenreChips();
}

export function dashDrillItchGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  collapsePicksForDrill();
  savePrefs();
  setPendingScrollTarget({ kind: "toolbar" });
  switchView("itch");
  renderGenreChips();
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
  collapsePicksForDrill();
  savePrefs();
  invalidateTableCache();
  setPendingScrollTarget({ kind: "toolbar" });
  if (state.activeView !== "library") switchView("library");
  renderStoreChips();
  refreshFilterUI({ force: true });
}
