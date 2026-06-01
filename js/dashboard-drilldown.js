// Dashboard drill-down helpers: click handlers that route from dashboard widgets into the filtered library/itch views.
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { savePrefs, setCoopFilterMode, syncFilterDomFromState } from './prefs.js';
import { refreshFilterUI, renderGenreChips, renderStoreChips, switchView } from './filters-ui.js';
import { invalidateTableCache, renderTable } from './table-ui.js';
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
  state.prefs.tagFilters = [];
  state.prefs.tagFilterMode = "OR";
  state.cleanupModeActive = false;
  syncFilterDomFromState();
  const tagModeEl = document.getElementById("tagFilterMode");
  if (tagModeEl) tagModeEl.value = "OR";
}

/**
 * Land a dashboard drill-in just above the search bar.
 *
 * The toolbar section contains the search input + filter button + active
 * pills. Scrolling to its top means the user immediately sees: search bar,
 * active filter pills, then the filtered table — exactly what they expect
 * after clicking a chart category. Works whether picks is collapsed or
 * expanded; when expanded the picks grid is intentionally above the fold.
 */
export function scrollDrillResultsIntoView() {
  const land = () => {
    const toolbar = document.getElementById("toolbarSection");
    if (!toolbar) {
      window.scrollTo(0, 0);
      return;
    }
    const rect = toolbar.getBoundingClientRect();
    const targetY = Math.max(0, rect.top + window.scrollY - 12);
    try { window.scrollTo({ top: targetY, behavior: "auto" }); }
    catch (_) { window.scrollTo(0, targetY); }
  };
  // Two rAFs: first lets renderTable commit, second lets picks/summary layout settle.
  requestAnimationFrame(() => requestAnimationFrame(land));
}

export function dashDrillStore(store) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  savePrefs();
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
}

export function dashDrillStatus(status) {
  dashResetLibraryFiltersExceptDedup();
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  savePrefs();
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
}

export function dashDrillStoreStatus(store, status) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  state.sessionPrefs.statusFilter = status || "";
  syncFilterDomFromState();
  savePrefs();
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
}

export function dashFinishDrillToLibrary() {
  savePrefs();
  switchView("library");
  renderStoreChips();
  renderGenreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
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
  switchView("library");
  renderGenreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
}

export function dashDrillItchGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  savePrefs();
  switchView("itch");
  renderGenreChips();
  refreshFilterUI();
  scrollDrillResultsIntoView();
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
  if (state.activeView !== "library") switchView("library");
  renderStoreChips();
  refreshFilterUI();
  renderTable();
  scrollDrillResultsIntoView();
}
