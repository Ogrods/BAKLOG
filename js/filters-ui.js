import { bindEscapeClose, trapFocus } from './focus-trap.js';
import {
  consumeDeferredRenders,
  deferPicksRender,
  deferSummaryRender,
  deferTableRender,
  isTableDataView,
} from './render-gate.js';
import { cancelAllLibraryCountAnimations } from './library-count-animation.js';
import { noteDeferredFlush } from './propagation-trace.js';
import {
  state,
  GENRE_CHIP_COLLAPSE_AT,
  WISHLIST_STATUS_CHIP_DEFS,
  STATUS_FILTER_LABELS,
} from './state.js';
import { escapeHtml, escapeAttr, formatNum } from './dom-util.js';
import { WISHLIST_STATUS_LABELS } from './row-templates.js';
import {
  gameKey,
  normalizeGame,
  ratingValue,
  hltbMain,
  chipStatusKey,
  priorityScore,
  renderStatusChipsHtml,
  renderBulkStatusButtons,
  recomputeCrossStoreHidden,
  itchIsGame,
  combinedPlaytime,
} from './game-core.js';
import { STORE_DISPLAY_ORDER, storeDisplayRank } from './dashboard-shared.js';
import {
  getDealInfo,
  effectiveDiscountPercent,
  effectiveSortPrice,
  isOwnedByTitle,
} from './deals.js';
import { gameGenresCanonical, aliasCanonicalGenre } from './genres.js';
import { getPersonal, filterOutHidden } from './personal-storage.js';
import {
  savePrefs,
  applySavedSortForView,
  syncCoopFilterSegmented,
  setCoopFilterMode,
  getCoopFilterMode,
  COOP_FILTER_LABELS,
  syncFilterDomFromState,
} from './prefs.js';
import {
  renderTable,
  invalidateTableCache,
  updateBulkBar,
  tableFingerprint,
  isViewCached,
  scheduleScrollAfterLayoutSettled,
  scheduleScrollAfterChromeSettled,
  hasPendingScrollTarget,
  hasPendingToolbarScroll,
  setPendingScrollTarget,
  prewarmTableQueryForView,
  syncRowCountLabel,
} from './table-ui.js';
import { renderPicks } from './picks-ui.js';
import { showViewOverlay, hideViewOverlay } from './loading-curtain.js';
import { ensureChartJs } from './chart-loader.js';

export { hideViewOverlay as hideViewLoading } from './loading-curtain.js';
import {
  scheduleDashboardRender,
  cancelScheduledDashboardRender,
  stopDashboardRotations,
  renderDashboardWishlistStats,
  renderDashboard,
  dashboardWasRendered,
  setDashReplayAllowed,
} from './dashboard.js';
import { fetcherRunner } from './fetcher-health.js';
import {
  refreshConnections,
  startConnectionsPolling,
  stopConnectionsPolling,
  isItchTabAvailable,
  authStatusLoaded,
} from './connections.js';
import { collectActiveFilters } from './active-filters.js';

export { collectActiveFilters } from './active-filters.js';
export { buildTableEmptyStateHtml } from './table-empty-state.js';

// === Drawer + active pills ===

export function renderFiltersButtonBadge() {
  const n = collectActiveFilters().length;
  const badge = document.getElementById("filtersBtnBadge");
  if (!badge) return;
  badge.textContent = String(n);
  badge.classList.toggle("hidden", n === 0);
}

/**
 * Apply a prefs/session-prefs patch in one call instead of hand-rolling
 * the savePrefs + syncFilterDomFromState + recomputeCrossStoreHidden +
 * renderSummary + refreshFilterUI dance at every call site.
 *
 * Lives in filters-ui.js because every dependency already does — putting
 * it in prefs.js would create a circular import.
 *
 * @param {object} [patch]
 * @param {object} [patch.prefs]        Shallow-merge into state.prefs (persistent).
 * @param {object} [patch.sessionPrefs] Shallow-merge into state.sessionPrefs (session-only).
 *
 * @param {object} [options]
 * @param {boolean}   [options.recomputeDedup=false]
 *   Call recomputeCrossStoreHidden() + renderSummary() before the refresh.
 *   Used by the cross-store dedup toggle path.
 * @param {boolean}   [options.refresh=true]
 *   Run refreshFilterUI() at the end. Set false when the caller will paint
 *   the table itself (e.g. dashboard drills that own their scroll target).
 * @param {boolean}   [options.debounced=false]
 *   Use refreshFilterUIDebounced (slider / search-style inputs).
 * @param {object}    [options.refreshOptions]
 *   Forwarded to refreshFilterUI / refreshFilterUIDebounced.
 * @param {Function[]} [options.renderers]
 *   Extra renderers to run before the refresh (renderStoreChips,
 *   renderGenreChips, syncDealFilterControls, etc.). Each is invoked
 *   with no arguments. Errors are caught + warned so a bad chip
 *   renderer can't kill the whole apply.
 * @param {boolean}   [options.skipDomSync=false]
 *   Skip syncFilterDomFromState() even when sessionPrefs changed. Used
 *   by input event handlers where the DOM is already the source of the
 *   new value (pushing it back would just no-op).
 * @param {boolean}   [options.persist=true]
 *   Save state.prefs to localStorage when patch.prefs is present.
 *   Rarely false; only set for ephemeral prefs writes that another
 *   path is about to persist itself.
 */
export function applyPrefsChange(patch = {}, options = {}) {
  const hasPrefs = patch.prefs && typeof patch.prefs === "object";
  const hasSession = patch.sessionPrefs && typeof patch.sessionPrefs === "object";

  if (hasPrefs) Object.assign(state.prefs, patch.prefs);
  if (hasSession) Object.assign(state.sessionPrefs, patch.sessionPrefs);

  if (hasPrefs && options.persist !== false) savePrefs();
  if (hasSession && !options.skipDomSync) syncFilterDomFromState();

  if (options.recomputeDedup) {
    recomputeCrossStoreHidden();
    renderSummary();
  }

  if (Array.isArray(options.renderers)) {
    for (const fn of options.renderers) {
      if (typeof fn !== "function") continue;
      try { fn(); }
      catch (err) { console.warn("[applyPrefsChange] renderer threw", err); }
    }
  }

  if (options.refresh !== false) {
    if (options.debounced) refreshFilterUIDebounced(options.refreshOptions);
    else refreshFilterUI(options.refreshOptions);
  }
}

export function renderActiveFilterPills() {
  const wrap = document.getElementById("activeFilterPills");
  if (!wrap) return;
  const pills = collectActiveFilters();
  // Hide-duplicates is a session toggle; pin it to the far right so it doesn't
  // shuffle around when other filters appear/disappear.
  const dedupIdx = pills.findIndex(p => p.kind === "dedup");
  if (dedupIdx >= 0 && dedupIdx !== pills.length - 1) {
    const [d] = pills.splice(dedupIdx, 1);
    pills.push(d);
  }
  if (!pills.length) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = pills.map(p => `
    <button type="button" class="active-filter-pill" data-kind="${escapeAttr(p.kind)}" data-value="${escapeAttr(p.value)}" aria-label="Remove filter: ${escapeAttr(p.label)}" title="Remove this filter">
      ${escapeHtml(p.label)}
      <span class="active-filter-pill-x" aria-hidden="true">×</span>
    </button>
  `).join("") + `<button type="button" id="clearAllFiltersBtn" class="text-xs text-slate-400 hover:text-slate-200 underline ml-1" title="Clear all active filters">Clear all</button>`;
  wrap.querySelector("#clearAllFiltersBtn")?.addEventListener("click", clearAllFilters);
  wrap.querySelectorAll(".active-filter-pill").forEach(btn => {
    btn.addEventListener("click", () => removeActiveFilter(btn.dataset.kind, btn.dataset.value));
  });
}

/** Sync a single DOM input to a value, no-op if the element is missing. */
function setInputValue(id, val) {
  const el = document.getElementById(id);
  if (el) el.value = String(val);
}
function setInputChecked(id, checked) {
  const el = document.getElementById(id);
  if (el) el.checked = !!checked;
}
function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = String(text);
}

export function removeActiveFilter(kind, value) {
  switch (kind) {
    case "search":          return applyPrefsChange({ sessionPrefs: { search: "" } });
    case "status":          return applyPrefsChange({ sessionPrefs: { statusFilter: "" } });
    case "unplayed":        return applyPrefsChange({ sessionPrefs: { unplayedOnly: false } });
    case "earlyAccess":     return applyPrefsChange({ sessionPrefs: { earlyAccessOnly: false } });
    case "gamePass":        return applyPrefsChange({ sessionPrefs: { gamePassOnly: false } });
    case "stale":           return applyPrefsChange({ sessionPrefs: { staleOnly: false } });
    case "minRating":       return applyPrefsChange({ sessionPrefs: { minRating: 0 } });
    case "maxHours":        return applyPrefsChange({ sessionPrefs: { maxHours: 200 } });
    case "store":           return applyPrefsChange({ prefs: { storeFilter: "" } },           { renderers: [renderStoreChips] });
    case "releaseYear":     return applyPrefsChange({ prefs: { releaseYearFilter: "" } });
    case "wishlistStore":   return applyPrefsChange({ prefs: { wishlistStoreFilter: "" } },   { renderers: [renderWishlistStoreChips] });
    case "hltbBucket":      return applyPrefsChange({ prefs: { hltbBucket: null } });
    case "genre":
      return applyPrefsChange({ prefs: { genreFilters: (state.prefs.genreFilters || []).filter(x => x !== value) } });
    case "coop":
    case "coopOnline":
    case "coopLocal":
    case "coopAny":
      // setCoopFilterMode persists + syncs the segmented control itself.
      setCoopFilterMode("off");
      return applyPrefsChange();
    case "cleanup":
      state.cleanupModeActive = false;
      updateCleanupBtnState();
      return applyPrefsChange();
    case "dedup":
      return applyPrefsChange(
        { sessionPrefs: { crossStoreDedup: false } },
        { recomputeDedup: true, renderers: [() => setInputChecked("crossStoreDedup", false)] },
      );
    case "itchHideNonGames":
      return applyPrefsChange(
        { sessionPrefs: { itchHideNonGames: false } },
        { renderers: [() => setInputChecked("itchShowNonGames", true)] },
      );
    case "dealOnSale":
      return applyPrefsChange(
        { prefs: { dealOnSaleOnly: false } },
        { renderers: [() => setInputChecked("dealOnSaleOnly", false)] },
      );
    case "dealLow":
      return applyPrefsChange(
        { prefs: { dealHistoricalLowOnly: false } },
        { renderers: [() => setInputChecked("dealHistoricalLowOnly", false)] },
      );
    case "dealHideOwned":
      return applyPrefsChange(
        { prefs: { dealHideOwned: false } },
        { renderers: [() => setInputChecked("dealHideOwned", false)] },
      );
    case "dealMinDiscount":
      return applyPrefsChange(
        { prefs: { dealMinDiscount: 0 } },
        { renderers: [
          () => setInputValue("dealMinDiscount", "0"),
          () => setText("dealMinDiscountVal", "0"),
        ] },
      );
    case "dealMaxPrice":
      return applyPrefsChange(
        { prefs: { dealMaxPrice: 100 } },
        { renderers: [
          () => setInputValue("dealMaxPrice", "100"),
          () => setText("dealMaxPriceVal", "any"),
        ] },
      );
  }
  applyPrefsChange();
}

export function clearAllFilters() {
  setCoopFilterMode("off");
  state.cleanupModeActive = false;
  applyPrefsChange(
    {
      prefs: {
        storeFilter: "",
        wishlistStoreFilter: "",
        releaseYearFilter: "",
        hltbBucket: null,
        genreFilters: [],
      },
      sessionPrefs: {
        search: "",
        statusFilter: "",
        unplayedOnly: false,
        earlyAccessOnly: false,
        gamePassOnly: false,
        staleOnly: false,
        minRating: 0,
        maxHours: 200,
        crossStoreDedup: false,
        itchHideNonGames: false,
      },
    },
    {
      recomputeDedup: true,
      renderers: [
        () => setInputChecked("crossStoreDedup", false),
        () => setInputChecked("itchShowNonGames", true),
        updateCleanupBtnState,
      ],
    },
  );
}

export function showItchNonGamesFromEmptyState() {
  applyPrefsChange(
    { sessionPrefs: { itchHideNonGames: false } },
    { renderers: [() => setInputChecked("itchShowNonGames", true)] },
  );
}

let _filterDrawerRelease = null;

export function openFiltersDrawer() {
  state.filtersDrawerOpen = true;
  document.getElementById("filterDrawerBackdrop").classList.add("open");
  const drawer = document.getElementById("filterDrawer");
  drawer.classList.add("open");
  document.getElementById("filterDrawerBackdrop").setAttribute("aria-hidden", "false");
  drawer.setAttribute("aria-hidden", "false");
  _filterDrawerRelease?.();
  const releaseTrap = trapFocus(drawer);
  const releaseEsc = bindEscapeClose(drawer, closeFiltersDrawer);
  _filterDrawerRelease = () => {
    releaseTrap();
    releaseEsc();
    _filterDrawerRelease = null;
  };
}

export function closeFiltersDrawer() {
  state.filtersDrawerOpen = false;
  _filterDrawerRelease?.();
  document.getElementById("filterDrawerBackdrop").classList.remove("open");
  document.getElementById("filterDrawer").classList.remove("open");
  document.getElementById("filterDrawerBackdrop").setAttribute("aria-hidden", "true");
  document.getElementById("filterDrawer").setAttribute("aria-hidden", "true");
}

export function updateCleanupBtnState() {
  const btn = document.getElementById("cleanupModeBtn");
  if (!btn) return;
  btn.classList.toggle("active", state.cleanupModeActive);
  btn.classList.toggle("ring-2", state.cleanupModeActive);
  btn.classList.toggle("ring-orange-400", state.cleanupModeActive);
  btn.setAttribute("aria-pressed", String(state.cleanupModeActive));
}

export function updateGenreChipsCollapse() {
  const el = document.getElementById("genreChips");
  const btn = document.getElementById("toggleGenreChipsBtn");
  if (!el || !btn) return;
  const count = el.querySelectorAll(".genre-chip").length;
  if (count <= GENRE_CHIP_COLLAPSE_AT) {
    btn.classList.add("hidden");
    el.classList.remove("collapsed", "expanded");
    return;
  }
  btn.classList.remove("hidden");
  btn.textContent = state.genreChipsExpanded ? "Show fewer genres" : `Show all (${count})`;
  btn.title = state.genreChipsExpanded ? "Collapse the full genre list" : "Expand or collapse the full genre list";
  el.classList.toggle("collapsed", !state.genreChipsExpanded);
  el.classList.toggle("expanded", state.genreChipsExpanded);
}

export async function flushDeferredRenders() {
  if (!isTableDataView(state.activeView)) return;
  const flags = consumeDeferredRenders();
  noteDeferredFlush(flags);
  const tasks = [];
  if (flags.table) tasks.push(renderTable({ force: true }));
  if (flags.summary) renderSummary();
  if (flags.picks) renderPicks();
  if (tasks.length) await Promise.all(tasks);
}

export async function refreshFilterUI(options) {
  syncCoopFilterSegmented();
  renderFiltersButtonBadge();
  renderActiveFilterPills();
  if (state.activeView === "dashboard") {
    if (!options?.skipDashboardSchedule) scheduleDashboardRender();
    return;
  }
  if (state.activeView === "connections") {
    if (!options?.skipTable) deferTableRender();
    if (!options?.skipPicks) deferPicksRender();
    deferSummaryRender();
    return;
  }
  const drillIn = !!options?.drillIn || !!state._pendingFocusKey;
  // Chart drill-ins: paint summary + picks before the table so toolbar scroll
  // does not land while chrome above the table is still growing.
  if (hasPendingToolbarScroll()) {
    renderSummary();
    if (!options?.skipPicks) renderPicks();
    scheduleScrollAfterChromeSettled();
    if (!options?.skipTable) {
      if (options?.force) await renderTable({ force: true, drillIn: false });
      else await renderTable({ drillIn: false });
    }
    return;
  }
  if (!options?.skipTable) {
    if (options?.force || drillIn) await renderTable({ force: true, drillIn });
    else renderTable({ drillIn });
  }
  if (drillIn) {
    const deferChrome = () => {
      renderSummary();
      if (!options?.skipPicks) renderPicks();
      scheduleScrollAfterChromeSettled();
    };
    if (typeof requestIdleCallback === "function") requestIdleCallback(deferChrome, { timeout: 800 });
    else setTimeout(deferChrome, 0);
    return;
  }
  if (options?.skipPicks) {
    if (hasPendingScrollTarget()) scheduleScrollAfterChromeSettled();
    return;
  }
  renderSummary();
  renderPicks();
  if (hasPendingScrollTarget()) scheduleScrollAfterChromeSettled();
}

let _filterDebounceTimer = null;
export function refreshFilterUIDebounced(options) {
  clearTimeout(_filterDebounceTimer);
  _filterDebounceTimer = setTimeout(() => refreshFilterUI(options), 120);
}

let _tableRerenderTimer = null;
export function scheduleTableRerender() {
  clearTimeout(_tableRerenderTimer);
  _tableRerenderTimer = setTimeout(renderTable, 200);
}

export function updateWishlistDrawerVisibility() {
  const section = document.getElementById("wishlistDealsSection");
  if (section) section.classList.toggle("hidden", state.activeView !== "wishlist");
  const showWishlistDeals = state.activeView === "wishlist" && state.dashboardDataReady;
  const radar = document.getElementById("wishlistDealRadar");
  if (radar) {
    // Wait for the library/wishlist data to land before showing the radar so
    // it never flashes the "No wishlist data — run fetch_wishlist.py" message
    // on reload (mirrors the dashboardDataReady gate the dashboard uses).
    radar.classList.toggle("hidden", !showWishlistDeals);
    if (showWishlistDeals) renderDashboardWishlistStats();
  }
  const wishHouse = document.getElementById("wishlistHouseSlot");
  if (wishHouse) {
    wishHouse.classList.toggle("hidden", !showWishlistDeals);
  }
  void import('./claimable.js').then(m => m.renderClaimableModule());
}

export function updateViewChrome(options) {
  const isWish = state.activeView === "wishlist";
  const isItch = state.activeView === "itch";
  const isDash = state.activeView === "dashboard";
  const isConn = state.activeView === "connections";
  const isProView = state.activeView === "pro";
  const deferChrome = !!options?.deferTableChrome;
  const drillIn = !!options?.drillIn || !!state._pendingFocusKey;
  const hideTableUi = isDash || isConn || isProView || deferChrome;
  // Keep the FOUC guard in sync so its !important rules don't outlive the
  // initial view. Once the user switches views, the attribute matches reality.
  document.documentElement.setAttribute("data-init-view", state.activeView);
  applyItchTabVisibility();
  updateWishlistDrawerVisibility();
  updatePickTabsVisibility();
  // Quick-Wins slider visibility (only shown on the Quick Wins tab) lives in
  // picks-ui via updatePicksChrome; import lazily to avoid a top-level cycle.
  void import('./picks-ui.js').then(m => {
    m.updatePicksChrome();
    m.renderViewHouseSlot?.();
  });
  document.getElementById("picksSection")?.classList.toggle("hidden", hideTableUi);
  document.getElementById("toolbarSection")?.classList.toggle("hidden", hideTableUi);
  document.getElementById("tableShell")?.classList.toggle("hidden", hideTableUi);
  document.getElementById("rowCount")?.classList.toggle("hidden", hideTableUi);
  if (!hideTableUi) syncRowCountLabel();
  document.getElementById("summary")?.classList.toggle("hidden", isConn || isProView || deferChrome);
  document.getElementById("alphaNavWrap")?.classList.toggle("dashboard-hidden", isDash || isConn || isProView);
  document.getElementById("dashboardContainer")?.classList.toggle("hidden", !isDash);
  document.getElementById("connectionsContainer")?.classList.toggle("hidden", !isConn);
  document.getElementById("proContainer")?.classList.toggle("hidden", !isProView);
  document.getElementById("libraryStatusSection")?.classList.add("hidden");
  document.getElementById("itchFilterSection")?.classList.toggle("hidden", !isItch);
  // Cross-store dedup applies to library and wishlist (not itch — single store).
  document.getElementById("libraryStoreSection")?.classList.toggle("hidden", isItch || isDash || isConn || isProView || deferChrome);
  document.getElementById("wishlistStoreSection")?.classList.toggle("hidden", !isWish || deferChrome);
  const dedupHint = document.getElementById("crossStoreDedupHint");
  if (dedupHint) {
    dedupHint.title = isWish
      ? "Hides the same title listed on multiple wishlist stores. Store priority matches Library."
      : "Filter by store using the chips at the top of the page.";
  }
  document.getElementById("libraryMiscSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn || isProView);
  document.getElementById("displayToolsSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn || isProView);
  document.getElementById("gamePassSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn || isProView);
  document.getElementById("earlyAccessSection")?.classList.toggle("hidden", isItch || isDash || isConn || isProView);
  document.getElementById("coopSection")?.classList.toggle("hidden", isItch || isDash || isConn || isProView);
  if (isDash && !options?.skipDashboardSchedule) scheduleDashboardRender();
  else {
    // Keep charts built so a later return-to-dashboard can replay their
    // entrance animations cheaply. Just pause the rotation timers.
    stopDashboardRotations();
  }
  if (isConn) refreshConnections();
  if (isProView) {
    void import('./pro-view.js').then((m) => {
      m.applyProTabVisibility();
      m.renderProView();
    });
  } else {
    void import('./pro-view.js').then((m) => m.applyProTabVisibility());
  }
  renderBulkStatusButtons();
  if (!drillIn && !deferChrome) renderSummary();
}

export function updatePickTabsVisibility() {
  document.querySelectorAll(".pick-tab").forEach(btn => {
    const owner = btn.dataset.pickView;
    // Each tab declares data-pick-view (library | wishlist). Hide tabs that
    // belong to another view so wishlist never shows library "Top Rated", etc.
    btn.classList.toggle("hidden", !!owner && owner !== state.activeView);
  });
}

export function syncViewTabAria(view) {
  document.querySelectorAll(".view-tab").forEach((b) => {
    const active = b.dataset.view === view;
    b.classList.toggle("active", active);
    if (active) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
}

/** Quarantine itch.io nav until the user has set up itch (API key) or already has itch data. */
export function applyItchTabVisibility() {
  const tab = document.querySelector('.view-tab[data-view="itch"]');
  if (!tab) return;
  const available = isItchTabAvailable();
  tab.classList.toggle("hidden", !available);
  // Fail open during boot: until auth status is fetched and the library has
  // loaded, authStatus/itchGames are empty, so a hard refresh on itch would
  // always bounce to dashboard. Only redirect once we truly know.
  const known = authStatusLoaded() && state.dashboardDataReady;
  if (!available && known && state.activeView === "itch") {
    switchView("dashboard");
    state.prefs.activeView = "dashboard";
    savePrefs();
  }
}

export function switchView(view) {
  if (view === state.activeView) return;
  cancelAllLibraryCountAnimations();
  const fromView = state.activeView;
  const drillIn = !!state._pendingFocusKey;
  let drillOverlaySafety = null;
  const fpBefore = view !== "dashboard" ? tableFingerprint().replace(/"v":"[^"]+"/, `"v":"${view}"`) : "";
  const tableCached = !drillIn && view !== "dashboard" && isViewCached(view, fpBefore);
  const dashCached = view === "dashboard" && dashboardWasRendered();
  const useOverlay = drillIn || (!tableCached && !dashCached);
  if (fromView === "dashboard" && view !== "dashboard") {
    document.getElementById("dashboardContainer")?.classList.add("hidden");
    cancelScheduledDashboardRender();
    stopDashboardRotations();
  }
  // Light-up the clicked tab immediately so the click feels responsive even on
  // first-render paths where doSwitch is deferred to the next rAF.
  syncViewTabAria(view);
  if (useOverlay) showViewOverlay(view);
  if (drillIn && state._drillHideOverlay) {
    drillOverlaySafety = setTimeout(() => {
      if (state._drillHideOverlay) {
        state._drillHideOverlay = false;
        hideViewOverlay();
      }
    }, 600);
  }
  const doSwitch = () => {
    if (fromView === "dashboard") {
      cancelScheduledDashboardRender();
      // Charts left intact so the return trip can replay animations
      // via renderDashboard's same-data fast path. See replayDashboardChartAnimations.
      stopDashboardRotations();
    }
    invalidateTableCache();
    state.activeView = view;
    state.prefs.activeView = view;
    state.selectedKeys.clear();
    if (view !== "library") state.cleanupModeActive = false;
    if (!state._pendingFocusKey) state.focusedRowIndex = 0;
    if (view === "wishlist") {
      state.sessionPrefs.statusFilter = "";
      syncFilterDomFromState();
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "wishlistDeals") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = "wishlistDeals";
    } else if (view === "itch") {
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "topRated") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = state.prefs.itchPicksTab || "topRated";
    } else {
      state.prefs.picksTab = state.prefs.libraryPicksTab || "topRated";
    }
    applySavedSortForView(view);
    savePrefs();
    updateCleanupBtnState();
    updateBulkBar();
    const skipDashboardSchedule = view === "dashboard";
    const deferTableChrome = useOverlay && !drillIn && view !== "dashboard";
    updateViewChrome({ drillIn, skipDashboardSchedule, deferTableChrome });
    void flushDeferredRenders();
    const refreshDone = refreshFilterUI({ force: true, drillIn, skipDashboardSchedule });
    if (view === "dashboard") {
      // Explicit tab click — load Chart.js then render so the overlay doesn't linger.
      cancelScheduledDashboardRender();
      setDashReplayAllowed(true);
      ensureChartJs()
        .then(() => {
          if (state.activeView !== "dashboard") return;
          renderDashboard({ replay: true, replayRibbonOnly: true });
        })
        .catch(err => console.warn("[switchView] Chart.js load failed", err))
        .finally(() => setDashReplayAllowed(false));
      fetcherRunner.probeApi().then(async ok => {
        if (!ok) return;
        await fetcherRunner.syncFromServer();
        fetcherRunner.startDashboardPolling();
        stopConnectionsPolling();
      });
    } else if (view === "connections") {
      fetcherRunner.stopDashboardPolling();
      startConnectionsPolling();
      refreshConnections();
    } else if (view === "pro") {
      fetcherRunner.stopDashboardPolling();
      stopConnectionsPolling();
      void import('./pro-view.js').then((m) => m.renderProView());
    } else {
      fetcherRunner.stopDashboardPolling();
      stopConnectionsPolling();
    }
    if (view === "library" && state.dashboardDataReady) {
      const warm = () => prewarmTableQueryForView("wishlist").catch(() => {});
      if (typeof requestIdleCallback === "function") requestIdleCallback(warm, { timeout: 4000 });
      else setTimeout(warm, 500);
    }
    if (useOverlay && !drillIn) {
      if (view === "dashboard") {
        // catch() before finally(): a transient Chart.js load failure must not
        // leak as an unhandledrejection (the render path above logs it).
        ensureChartJs().catch(() => {}).finally(() => hideViewOverlay());
      } else {
        refreshDone.finally(() => {
          updateViewChrome({ skipDashboardSchedule: view === "dashboard" });
          hideViewOverlay();
          if (hasPendingScrollTarget()) scheduleScrollAfterChromeSettled();
        });
      }
    }
  };
  if (useOverlay) {
    requestAnimationFrame(() => requestAnimationFrame(doSwitch));
  } else {
    doSwitch();
  }
}

export function renderSummary() {
  const el = document.getElementById("summary");
  if (!el) return;
  if (state.activeView === "dashboard") {
    el.innerHTML = "";
    return;
  }
  if (state.activeView === "wishlist") {
    const wl = state.wishlistGames.filter(g => !state.wishlistCrossStoreHiddenKeys.has(gameKey(g)));
    const hiddenCount = state.wishlistGames.length - wl.length;
    const sourceSet = new Set();
    for (const g of state.wishlistGames) {
      const s = (g.wishlist_store || g.store_target || (g.store === "wishlist" ? "steam" : g.store) || "").toLowerCase();
      if (s) sourceSet.add(s);
    }
    const sourcesList = [...sourceSet].map(s => s.toUpperCase()).sort().join(", ");
    const onSale = wl.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
    const lows = wl.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; });
    const owned = wl.filter(g => isOwnedByTitle(g.name)).length;
    // 100%-off (free-to-claim) deals skew the averages (0 price, max discount),
    // so they're excluded from Avg discount / Avg price.
    const isFullyFree = g => effectiveDiscountPercent(g) >= 100;
    const cuts = onSale.map(g => effectiveDiscountPercent(g)).filter(c => c > 0 && c < 100);
    const avgDisc = cuts.length ? Math.round(cuts.reduce((s, c) => s + c, 0) / cuts.length) : null;
    const prices = wl.filter(g => !isFullyFree(g)).map(g => effectiveSortPrice(g)).filter(p => p != null);
    const avgPrice = prices.length ? (prices.reduce((s, p) => s + p, 0) / prices.length).toFixed(2) : null;
    const onSaleActive = !!state.prefs.dealOnSaleOnly;
    const lowOnlyActive = !!state.prefs.dealHistoricalLowOnly;
    const hideOwnedActive = !!state.prefs.dealHideOwned;
    const resetChip = `<div class="summary-stat-chip" data-stat="wishlist" title="All wishlist entries"><span>Wishlist</span> <span class="library-count-host" data-libcount-host><span class="text-slate-100 font-semibold ml-1" data-count-target="wishlist">${wl.length}</span></span>${hiddenCount ? ` <span class="text-slate-400 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</div>`;
    const onSaleChip = `<button type="button" class="summary-deal-chip${onSaleActive ? " active" : ""}" data-wishlist-deal-filter="onSale" title="${onSaleActive ? "Clear: show only on-sale wishlist items" : "Show only on-sale wishlist items"}">On sale <span class="text-emerald-200 font-semibold ml-1">${onSale.length}</span></button>`;
    const lowChip = lows.length
      ? `<button type="button" class="summary-deal-chip historical${lowOnlyActive ? " active" : ""}" data-wishlist-deal-filter="historicalLow" title="${lowOnlyActive ? "Clear: show only historical lows" : "Show only historical lows"}">Historical low <span class="text-amber-300 font-semibold ml-1">${lows.length}</span></button>`
      : "";
    const ownedChip = owned
      ? `<button type="button" class="summary-deal-chip owned${hideOwnedActive ? " active" : ""}" data-wishlist-deal-filter="hideOwned" title="${hideOwnedActive ? "Currently hiding already-owned wishlist items - click to show" : "Hide wishlist items you already own elsewhere"}">Already owned <span class="text-amber-200 font-semibold ml-1">${owned}</span></button>`
      : "";
    const statusChips = renderStatusChipsHtml(wl, WISHLIST_STATUS_CHIP_DEFS);
    const sourcesChip = sourceSet.size
      ? `<div class="summary-stat-chip" data-stat="sources" title="Wishlist sources: ${escapeAttr(sourcesList)}">Sources <span class="text-slate-100 font-semibold ml-1">${sourceSet.size}</span></div>`
      : "";
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        ${resetChip}
        ${sourcesChip}
        ${avgDisc != null ? `<div class="summary-stat-chip" data-stat="avg-discount" title="Average discount % across on-sale wishlist items">Avg discount <span class="text-slate-100 font-semibold ml-1">${avgDisc}%</span></div>` : ""}
        ${avgPrice != null ? `<div class="summary-stat-chip" data-stat="avg-price" title="Average current deal price (USD) on wishlist">Avg price <span class="text-slate-100 font-semibold ml-1">$${avgPrice}</span></div>` : ""}
        ${onSaleChip}
        ${lowChip}
        ${ownedChip}
      </div>
      ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
    return;
  }
  if (state.activeView === "itch") {
    const total = state.itchGames.length;
    const gamesOnly = state.itchGames.filter(itchIsGame).length;
    const hideNonGames = !!state.sessionPrefs.itchHideNonGames;
    const showingGames = hideNonGames ? gamesOnly : total;
    const backlog = state.itchGames.filter(g => getPersonal(g).status === "backlog" && (!hideNonGames || itchIsGame(g)));
    const totalHltb = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
    const rated = state.itchGames.filter(g => ratingValue(g) > 0 && (!hideNonGames || itchIsGame(g)));
    const avg = rated.length ? (rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length).toFixed(0) : " - ";
    const fetched = state.libraryMeta.itch?.fetched_at ? new Date(state.libraryMeta.itch.fetched_at).toLocaleString() : "";
    const countLabel = hideNonGames && gamesOnly !== total
      ? `${gamesOnly} of ${total}`
      : String(total);
    const itchScope = hideNonGames ? state.itchGames.filter(itchIsGame) : state.itchGames;
    const statusChips = renderStatusChipsHtml(itchScope);
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        <div class="summary-stat-chip summary-stat-chip--itch" title="itch.io items in your library">itch.io <span class="text-slate-100 font-semibold ml-1">${countLabel}</span></div>
        <div class="summary-stat-chip summary-stat-chip--itch" title="Sum of HLTB main hours on itch backlog">Backlog hours <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(totalHltb))}h</span></div>
        <div class="summary-stat-chip summary-stat-chip--itch" title="itch.io items with a community rating">Rated <span class="text-slate-100 font-semibold ml-1">${rated.length}</span></div>
        <div class="summary-stat-chip summary-stat-chip--itch" title="Mean itch.io review % (rated items)">Avg rating <span class="text-slate-100 font-semibold ml-1">${avg}${avg !== " - " ? "%" : ""}</span></div>
        ${fetched ? `<div class="summary-stat-chip summary-stat-chip--itch text-slate-400" title="Last itch.io library fetch time">Fetched ${escapeHtml(fetched)}</div>` : ""}
      </div>
      ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
    return;
  }
  const visible = filterOutHidden(state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))));
  const storeLabels = {
    steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic",
    amazon: "Amazon", xbox: "Xbox", battlenet: "Battle.net",
    ubisoft: "Ubisoft", nintendo: "Nintendo", itch: "itch.io", humble: "Humble", ea: "EA App",
  };
  const storeCounts = STORE_DISPLAY_ORDER
    .filter(k => storeLabels[k])
    .map(k => ({
      key: k,
      label: storeLabels[k],
      count: k === "itch" ? state.itchGames.filter(itchIsGame).length : state.allGames.filter(g => normalizeGame(g).store === k).length,
    }))
    .sort((a, b) => storeDisplayRank(a.key) - storeDisplayRank(b.key));
  const hiddenCount = state.allGames.length - visible.length;
  const staleCount = state.allGames.filter(g => g.stale).length;
  const staleActive = !!state.sessionPrefs.staleOnly;
  const sourceCount = storeCounts.filter(s => s.count > 0).length;
  const activeStore = state.prefs.storeFilter || "";
  const storeChips = storeCounts
    .map(s => {
      if (s.key === "itch" && s.count > 0) {
        const itchTotal = state.itchGames.length;
        const titleText = itchTotal !== s.count
          ? `Open itch.io library tab (${s.count} games of ${itchTotal} total keys)`
          : "Open itch.io library tab";
        return `<button type="button" class="summary-jump-chip cursor-pointer" data-jump-view="itch" title="${titleText}">${s.label} <span class="font-semibold ml-1">${s.count}</span> <span class="ml-0.5 opacity-60">→</span></button>`;
      }
      if (s.count === 0) return "";
      const isActive = activeStore === s.key;
      const title = isActive ? `Clear ${s.label} filter` : `Filter: ${s.label}`;
      return `<button type="button" class="summary-store-chip${isActive ? " active" : ""}" data-store-filter="${escapeAttr(s.key)}" title="${escapeAttr(title)}"><span class="summary-store-chip-label">${escapeHtml(s.label)}</span> <span class="text-slate-100 font-semibold ml-1">${s.count}</span></button>`;
    })
    .join("");
  const statusChips = renderStatusChipsHtml(visible);
  const staleChip = staleCount
    ? `<button type="button" class="summary-stale-chip${staleActive ? " active" : ""}" data-stale-filter="1" title="${staleActive ? "Clear: show all library games" : "Show only games not seen in the latest store sync"}">Stale sync <span class="text-amber-200 font-semibold ml-1">${staleCount}</span></button>`
    : "";
  el.innerHTML = `
    <div class="w-full flex flex-wrap gap-2">
      <div class="summary-stat-chip" data-stat="games" title="Visible games in library (after filters and dedup)">Games <span class="library-count-host" data-libcount-host><span class="text-slate-100 font-semibold ml-1" data-count-target="library">${visible.length}</span></span>${hiddenCount ? ` <span class="text-slate-400 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</div>
      <div class="summary-stat-chip" data-stat="sources" title="Stores with games in your library">Sources <span class="text-slate-100 font-semibold ml-1">${sourceCount}</span></div>
      ${staleChip}
      ${storeChips}
    </div>
    ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
}

export function renderStoreChips() {
  // Drawer chips were retired in the filter consolidation; the top-bar summary
  // chips are the source of truth. Kept for backward compat with callers that
  // touch this after a state-only filter change (e.g. removeActiveFilter).
  document.querySelectorAll(".store-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.store === (state.prefs.storeFilter || ""));
  });
  if (state.activeView !== "dashboard") renderSummary();
}

export function renderWishlistStoreChips() {
  document.querySelectorAll(".wishlist-store-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.wishlistStore === (state.prefs.wishlistStoreFilter || ""));
  });
}

export function renderGenreChips() {
  const genreSource = state.activeView === "itch" ? state.itchGames : state.allGames;
  const genres = [...new Set(genreSource.flatMap(g => gameGenresCanonical(g)))].sort();
  const html = genres.map(genre => {
    const active = (state.prefs.genreFilters || []).includes(genre);
    return `<button type="button" class="genre-chip px-2 py-1 rounded border border-slate-600 text-xs ${active ? "active" : "bg-slate-700 text-slate-300"}" data-genre="${escapeAttr(genre)}" title="Toggle genre filter (OR/AND set in drawer)">${escapeHtml(genre)}</button>`;
  }).join("");
  document.getElementById("genreChips").innerHTML = html || '<span class="text-xs text-slate-400">No genres found.</span>';
  updateGenreChipsCollapse();
}

// === Export ===
export function exportTopBacklogMarkdown() {
  const visible = filterOutHidden(state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))));
  const backlog = visible
    .filter(g => chipStatusKey(g) === "backlog")
    .sort((a, b) => priorityScore(b) - priorityScore(a))
    .slice(0, 20);
  if (!backlog.length) {
    alert("No backlog games to export.");
    return;
  }
  const lines = [
    "# BAKLOG - Top 20 backlog",
    "",
    "| # | Game | Store | Score | HLTB main | Rating |",
    "|---:|---|---|---:|---:|---:|",
  ];
  backlog.forEach((g, i) => {
    const store = normalizeGame(g).store.toUpperCase();
    const h = hltbMain(g);
    const rating = ratingValue(g);
    lines.push(
      `| ${i + 1} | ${g.name.replace(/\|/g, "\\|")} | ${store} | ${priorityScore(g).toFixed(1)} | ${h != null ? `${h}h` : " - "} | ${rating > 0 ? `${rating}%` : " - "} |`,
    );
  });
  const md = lines.join("\n");
  navigator.clipboard.writeText(md).then(
    () => { /* copied */ },
    () => download("baklog-top-20.md", md, "text/markdown"),
  );
}

export function exportCsv() {
  // Local import-free path: read the visible list snapshot from state so we
  // don't pull table-ui's filteredGames into the import graph here.
  const list = state._visibleList || [];
  const isWish = state.activeView === "wishlist";
  const headers = isWish
    ? ["store", "wishlist_store", "id", "name", "tracking_status", "deal_price", "deal_discount_pct", "deal_shop", "historical_low", "steam_review_percent", "hltb_main", "release_date", "genres", "notes", "store_url"]
    : ["store", "id", "name", "status", "score", "playtime_hours", "hltb_main", "hltb_main_extra", "hltb_completionist", "steam_review_percent", "price", "discount_percent", "release_date", "genres", "notes"];
  const rows = list.map(g => {
    const p = getPersonal(g);
    const ng = normalizeGame(g);
    const d = getDealInfo(g);
    if (isWish) {
      return [
        ng.store, g.wishlist_store ?? "", ng.id, g.name, p.status,
        d?.price != null ? d.price.toFixed(2) : "", effectiveDiscountPercent(g) || "",
        d?.shop ?? "", d?.isHistoricalLow ? "yes" : "",
        g.steam_review_percent ?? "", hltbMain(g) ?? "",
        g.release_date ?? "", (g.genres || []).join("; "), p.notes,
        g.store_url ?? d?.url ?? "",
      ];
    }
    return [
      ng.store, ng.id, g.name, p.status, priorityScore(g).toFixed(2), (combinedPlaytime(g) / 60).toFixed(1),
      hltbMain(g) ?? "", g.hltb_main_extra_hours ?? "", g.hltb_completionist_hours ?? "", g.steam_review_percent ?? "",
      g.price ?? "", effectiveDiscountPercent(g) || (g.discount_percent ?? ""), g.release_date ?? "", (g.genres || []).join("; "), p.notes
    ];
  }).map(cells => cells.map(x => `"${String(x).replace(/"/g, '""')}"`).join(","));
  const fname = isWish ? "steam-backlog-wishlist.csv" : "steam-backlog-library.csv";
  download(fname, `${headers.join(",")}\n${rows.join("\n")}`, "text/csv");
}

export function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}
