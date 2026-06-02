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
} from './game-core.js';
import {
  getDealInfo,
  effectiveDiscountPercent,
  effectiveSortPrice,
  isOwnedByTitle,
} from './deals.js';
import { gameGenresCanonical, aliasCanonicalGenre } from './genres.js';
import { getPersonal } from './personal-storage.js';
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
  reanchorPickedRow,
} from './table-ui.js';
import { renderPicks } from './picks-ui.js';
import { showViewOverlay, hideViewOverlay } from './loading-curtain.js';

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
import { refreshConnections, startConnectionsPolling, stopConnectionsPolling } from './connections.js';

// === Drawer + active pills ===
export function collectActiveFilters() {
  const pills = [];
  const sp = state.sessionPrefs || {};
  const q = String(sp.search || "").trim();
  if (q) pills.push({ kind: "search", value: q, label: `Search: ${q}` });
  if (state.activeView === "library" || state.activeView === "itch") {
    const status = sp.statusFilter || "";
    if (status) pills.push({ kind: "status", value: status, label: `Status: ${STATUS_FILTER_LABELS[status] || status}` });
  } else if (state.activeView === "wishlist") {
    const status = sp.statusFilter || "";
    if (status) {
      const label = WISHLIST_STATUS_LABELS[status] || STATUS_FILTER_LABELS[status] || status;
      pills.push({ kind: "status", value: status, label: `Status: ${label}` });
    }
  }
  if (state.prefs.storeFilter) pills.push({ kind: "store", value: state.prefs.storeFilter, label: `Store: ${state.prefs.storeFilter}` });
  if (state.activeView === "library" && state.prefs.releaseYearFilter) {
    pills.push({ kind: "releaseYear", value: state.prefs.releaseYearFilter, label: `Released: ${state.prefs.releaseYearFilter}` });
  }
  if (state.activeView === "wishlist" && state.prefs.wishlistStoreFilter) {
    const labelMap = { steam: "Steam", gog: "GOG", epic: "Epic", psn: "PlayStation", ubisoft: "Ubisoft" };
    const v = state.prefs.wishlistStoreFilter;
    pills.push({ kind: "wishlistStore", value: v, label: `Wishlist source: ${labelMap[v] || v}` });
  }
  for (const g of state.prefs.genreFilters || []) pills.push({ kind: "genre", value: g, label: g });
  if (sp.unplayedOnly) pills.push({ kind: "unplayed", value: "1", label: "Unplayed only" });
  if (sp.earlyAccessOnly) pills.push({ kind: "earlyAccess", value: "1", label: "Early Access only" });
  const coopMode = getCoopFilterMode();
  if (coopMode !== "off") {
    pills.push({ kind: "coop", value: coopMode, label: COOP_FILTER_LABELS[coopMode] || coopMode });
  }
  const minR = +(sp.minRating || 0);
  if (minR > 0) pills.push({ kind: "minRating", value: String(minR), label: `Rating ≥ ${minR}%` });
  const maxH = sp.maxHours == null ? 200 : +sp.maxHours;
  if (maxH < 200) pills.push({ kind: "maxHours", value: String(maxH), label: `HLTB ≤ ${maxH}h` });
  if (state.prefs.hltbBucket != null) {
    const labels = ["0–2h", "2–5h", "5–10h", "10–20h", "20–40h", "40h+"];
    const lbl = labels[state.prefs.hltbBucket];
    if (lbl) pills.push({ kind: "hltbBucket", value: String(state.prefs.hltbBucket), label: `HLTB ${lbl}` });
  }
  if (state.cleanupModeActive && state.activeView === "library") pills.push({ kind: "cleanup", value: "1", label: "Cleanup mode" });
  if (state.activeView === "itch" && state.sessionPrefs.itchHideNonGames) pills.push({ kind: "itchHideNonGames", value: "1", label: "Hide tools, soundtracks, etc." });
  if (state.sessionPrefs.crossStoreDedup) pills.push({ kind: "dedup", value: "1", label: "Hide duplicates" });
  if (state.activeView === "wishlist") {
    if (state.prefs.dealOnSaleOnly) pills.push({ kind: "dealOnSale", value: "1", label: "On sale only" });
    if (state.prefs.dealHistoricalLowOnly) pills.push({ kind: "dealLow", value: "1", label: "Historical low only" });
    if (state.prefs.dealHideOwned) pills.push({ kind: "dealHideOwned", value: "1", label: "Hide owned" });
    if (+state.prefs.dealMinDiscount > 0) pills.push({ kind: "dealMinDiscount", value: String(state.prefs.dealMinDiscount), label: `Discount ≥ ${state.prefs.dealMinDiscount}%` });
    if (+state.prefs.dealMaxPrice < 100) pills.push({ kind: "dealMaxPrice", value: String(state.prefs.dealMaxPrice), label: `Price ≤ $${state.prefs.dealMaxPrice}` });
  }
  return pills;
}

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
    <button type="button" class="active-filter-pill" data-kind="${escapeAttr(p.kind)}" data-value="${escapeAttr(p.value)}" aria-label="Remove filter: ${escapeAttr(p.label)}">
      ${escapeHtml(p.label)}
      <span class="active-filter-pill-x" aria-hidden="true">×</span>
    </button>
  `).join("") + `<button type="button" id="clearAllFiltersBtn" class="text-xs text-slate-400 hover:text-slate-200 underline ml-1">Clear all</button>`;
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
        minRating: 0,
        maxHours: 200,
        crossStoreDedup: false,
      },
    },
    {
      recomputeDedup: true,
      renderers: [
        () => setInputChecked("crossStoreDedup", false),
        updateCleanupBtnState,
      ],
    },
  );
}

export function openFiltersDrawer() {
  state.filtersDrawerOpen = true;
  document.getElementById("filterDrawerBackdrop").classList.add("open");
  document.getElementById("filterDrawer").classList.add("open");
  document.getElementById("filterDrawerBackdrop").setAttribute("aria-hidden", "false");
  document.getElementById("filterDrawer").setAttribute("aria-hidden", "false");
}

export function closeFiltersDrawer() {
  state.filtersDrawerOpen = false;
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
  el.classList.toggle("collapsed", !state.genreChipsExpanded);
  el.classList.toggle("expanded", state.genreChipsExpanded);
}

export async function refreshFilterUI(options) {
  syncCoopFilterSegmented();
  renderFiltersButtonBadge();
  renderActiveFilterPills();
  if (state.activeView === "dashboard") {
    if (!options?.skipDashboardSchedule) scheduleDashboardRender();
    return;
  }
  const drillIn = !!options?.drillIn || !!state._pendingFocusKey;
  // Dashboard drill-in: paint the table first; summary chips scan allGames and
  // picks re-query deals — defer both so we don't block the first row paint.
  if (!drillIn) renderSummary();
  if (!options?.skipTable) {
    if (options?.force || drillIn) await renderTable({ force: true });
    else renderTable();
  }
  if (drillIn) {
    const deferChrome = () => {
      renderSummary();
      if (!options?.skipPicks) renderPicks();
      // Picks/summary just paint above the table, shifting tableShell down.
      // paintTableBody's earlier scroll measured tableShell BEFORE that shift,
      // so the focused row is now off-center (often above the fold for high
      // indices, or under the picks card for low indices like the spotlight
      // pool which sorts alphabetically near the top). Re-anchor against the
      // live row rect now that the layout has settled.
      requestAnimationFrame(() => reanchorPickedRow());
    };
    if (typeof requestIdleCallback === "function") requestIdleCallback(deferChrome, { timeout: 800 });
    else setTimeout(deferChrome, 0);
    return;
  }
  if (options?.skipPicks) return;
  renderPicks();
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
  const radar = document.getElementById("wishlistDealRadar");
  if (radar) {
    // Wait for the library/wishlist data to land before showing the radar so
    // it never flashes the "No wishlist data — run fetch_wishlist.py" message
    // on reload (mirrors the dashboardDataReady gate the dashboard uses).
    const showRadar = state.activeView === "wishlist" && state.dashboardDataReady;
    radar.classList.toggle("hidden", !showRadar);
    if (showRadar) renderDashboardWishlistStats();
  }
}

export function updateViewChrome(options) {
  const isWish = state.activeView === "wishlist";
  const isItch = state.activeView === "itch";
  const isDash = state.activeView === "dashboard";
  const isConn = state.activeView === "connections";
  // refreshFilterUI runs renderSummary later. On drill-in we defer it to
  // requestIdleCallback so the chip scan never blocks the first row paint.
  const drillIn = !!options?.drillIn || !!state._pendingFocusKey;
  // Keep the FOUC guard in sync so its !important rules don't outlive the
  // initial view. Once the user switches views, the attribute matches reality.
  document.documentElement.setAttribute("data-init-view", state.activeView);
  updateWishlistDrawerVisibility();
  updatePickTabsVisibility();
  // Quick-Wins slider visibility lives in picks-ui via updatePicksChrome;
  // import lazily here so we avoid a top-level cycle with picks-ui.
  document.getElementById("quickWinMaxWrap")?.classList.toggle("hidden", isWish || isItch);
  document.getElementById("picksSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("toolbarSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("tableShell")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("rowCount")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("summary")?.classList.toggle("hidden", isConn);
  document.getElementById("alphaNavWrap")?.classList.toggle("dashboard-hidden", isDash || isConn);
  document.getElementById("dashboardContainer")?.classList.toggle("hidden", !isDash);
  document.getElementById("connectionsContainer")?.classList.toggle("hidden", !isConn);
  document.getElementById("libraryStatusSection")?.classList.add("hidden");
  document.getElementById("itchFilterSection")?.classList.toggle("hidden", !isItch);
  // Cross-store dedup applies to library and wishlist (not itch — single store).
  document.getElementById("libraryStoreSection")?.classList.toggle("hidden", isItch || isDash || isConn);
  document.getElementById("wishlistStoreSection")?.classList.toggle("hidden", !isWish);
  const dedupHint = document.getElementById("crossStoreDedupHint");
  if (dedupHint) {
    dedupHint.textContent = isWish
      ? "Hides the same title listed on multiple wishlist stores. Store priority matches Library."
      : "Filter by store using the chips at the top of the page.";
  }
  document.getElementById("libraryMiscSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn);
  document.getElementById("earlyAccessSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("coopSection")?.classList.toggle("hidden", isDash || isConn);
  if (isDash && !options?.skipDashboardSchedule) scheduleDashboardRender();
  else {
    // Keep charts built so a later return-to-dashboard can replay their
    // entrance animations cheaply. Just pause the rotation timers.
    stopDashboardRotations();
  }
  if (isConn) refreshConnections();
  renderBulkStatusButtons();
  if (!drillIn) renderSummary();
}

export function updatePickTabsVisibility() {
  document.querySelectorAll(".pick-tab").forEach(btn => {
    const owner = btn.dataset.pickView;
    // Each tab declares data-pick-view (library | wishlist). Hide tabs that
    // belong to another view so wishlist never shows library "Top Rated", etc.
    btn.classList.toggle("hidden", !!owner && owner !== state.activeView);
  });
}

export function switchView(view) {
  if (view === state.activeView) return;
  const fromView = state.activeView;
  const drillIn = !!state._pendingFocusKey;
  const fpBefore = view !== "dashboard" ? tableFingerprint().replace(/"v":"[^"]+"/, `"v":"${view}"`) : "";
  const tableCached = !drillIn && view !== "dashboard" && isViewCached(view, fpBefore);
  const dashCached = view === "dashboard" && dashboardWasRendered();
  const useOverlay = drillIn || (!tableCached && !dashCached);
  // Light-up the clicked tab immediately so the click feels responsive even on
  // first-render paths where doSwitch is deferred to the next rAF.
  document.querySelectorAll(".view-tab").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  if (useOverlay) showViewOverlay(view);
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
    if (!state._pendingFocusKey) state.focusedRowIndex = 0;
    if (view === "dashboard") {
      state.cleanupModeActive = false;
    } else if (view === "wishlist") {
      state.cleanupModeActive = false;
      state.sessionPrefs.statusFilter = "";
      syncFilterDomFromState();
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "wishlistDeals") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = "wishlistDeals";
    } else if (view === "itch") {
      state.cleanupModeActive = false;
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
    updateViewChrome({ drillIn, skipDashboardSchedule });
    refreshFilterUI({ force: true, drillIn, skipDashboardSchedule });
    if (view === "dashboard") {
      // Explicit tab click — skip the 80ms scheduleDashboardRender debounce and
      // render this frame so the overlay/blank state doesn't linger.
      cancelScheduledDashboardRender();
      setDashReplayAllowed(true);
      renderDashboard({ replay: true });
      setDashReplayAllowed(false);
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
    } else {
      fetcherRunner.stopDashboardPolling();
      stopConnectionsPolling();
    }
    if (useOverlay && !drillIn) hideViewOverlay();
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
    const cuts = onSale.map(g => effectiveDiscountPercent(g)).filter(c => c > 0);
    const avgDisc = cuts.length ? Math.round(cuts.reduce((s, c) => s + c, 0) / cuts.length) : null;
    const prices = wl.map(g => effectiveSortPrice(g)).filter(p => p != null);
    const avgPrice = prices.length ? (prices.reduce((s, p) => s + p, 0) / prices.length).toFixed(2) : null;
    const onSaleActive = !!state.prefs.dealOnSaleOnly;
    const lowOnlyActive = !!state.prefs.dealHistoricalLowOnly;
    const hideOwnedActive = !!state.prefs.dealHideOwned;
    const wishlistFiltersDirty = onSaleActive || lowOnlyActive || hideOwnedActive
      || !!state.prefs.wishlistStoreFilter
      || !!state.sessionPrefs?.statusFilter;
    const resetChip = `<button type="button" class="summary-wishlist-reset px-3 py-2 rounded-full bg-slate-800 hover:bg-slate-700 text-xs cursor-pointer border border-slate-700${wishlistFiltersDirty ? " text-slate-200" : " text-slate-400 cursor-default"}" title="${wishlistFiltersDirty ? "Clear all wishlist filters" : "All wishlist entries"}"><span>Wishlist</span> <span class="text-slate-100 font-semibold ml-1">${wl.length}</span>${hiddenCount ? ` <span class="text-slate-500 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</button>`;
    const onSaleChip = `<button type="button" class="summary-deal-chip${onSaleActive ? " active" : ""}" data-wishlist-deal-filter="onSale" title="${onSaleActive ? "Clear: show only on-sale wishlist items" : "Show only on-sale wishlist items"}">On sale <span class="text-emerald-200 font-semibold ml-1">${onSale.length}</span></button>`;
    const lowChip = lows.length
      ? `<button type="button" class="summary-deal-chip historical${lowOnlyActive ? " active" : ""}" data-wishlist-deal-filter="historicalLow" title="${lowOnlyActive ? "Clear: show only historical lows" : "Show only historical lows"}">Historical low <span class="text-amber-300 font-semibold ml-1">${lows.length}</span></button>`
      : "";
    const ownedChip = owned
      ? `<button type="button" class="summary-deal-chip owned${hideOwnedActive ? " active" : ""}" data-wishlist-deal-filter="hideOwned" title="${hideOwnedActive ? "Currently hiding already-owned wishlist items — click to show" : "Hide wishlist items you already own elsewhere"}">Already owned <span class="text-amber-200 font-semibold ml-1">${owned}</span></button>`
      : "";
    const statusChips = renderStatusChipsHtml(wl, WISHLIST_STATUS_CHIP_DEFS);
    const sourcesChip = sourceSet.size
      ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs" title="Wishlist sources: ${escapeAttr(sourcesList)}">Sources <span class="text-slate-100 font-semibold ml-1">${sourceSet.size}</span></div>`
      : "";
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        ${resetChip}
        ${sourcesChip}
        ${onSaleChip}
        ${lowChip}
        ${avgDisc != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg discount <span class="text-slate-100 font-semibold ml-1">${avgDisc}%</span></div>` : ""}
        ${avgPrice != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg price <span class="text-slate-100 font-semibold ml-1">$${avgPrice}</span></div>` : ""}
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
    const avg = rated.length ? (rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length).toFixed(0) : "—";
    const fetched = state.libraryMeta.itch?.fetched_at ? new Date(state.libraryMeta.itch.fetched_at).toLocaleString() : "";
    const countLabel = hideNonGames && gamesOnly !== total
      ? `${gamesOnly} of ${total}`
      : String(total);
    const itchScope = hideNonGames ? state.itchGames.filter(itchIsGame) : state.itchGames;
    const statusChips = renderStatusChipsHtml(itchScope);
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">itch.io <span class="text-slate-100 font-semibold ml-1">${countLabel}</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Backlog hours <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(totalHltb))}h</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Rated <span class="text-slate-100 font-semibold ml-1">${rated.length}</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg rating <span class="text-slate-100 font-semibold ml-1">${avg}${avg !== "—" ? "%" : ""}</span></div>
        ${fetched ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs text-slate-400">Fetched ${escapeHtml(fetched)}</div>` : ""}
      </div>
      ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
    return;
  }
  const visible = state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)));
  const backlog = visible.filter(g => getPersonal(g).status === "backlog");
  const totalHltb = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
  const played = visible.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  const storeLabels = {
    steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic",
    amazon: "Amazon", xbox: "Xbox", battlenet: "Battle.net",
    ubisoft: "Ubisoft", nintendo: "Nintendo", itch: "itch.io",
  };
  const storeCounts = Object.keys(storeLabels)
    .map(k => ({
      key: k,
      label: storeLabels[k],
      count: k === "itch" ? state.itchGames.filter(itchIsGame).length : state.allGames.filter(g => normalizeGame(g).store === k).length,
    }))
    .sort((a, b) => b.count - a.count);
  const rated = visible.filter(g => ratingValue(g) > 0);
  const avg = rated.length ? (rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length).toFixed(0) : "—";
  const hiddenCount = state.allGames.length - visible.length;
  const activeStore = state.prefs.storeFilter || "";
  const storeChips = storeCounts
    .map(s => {
      if (s.key === "itch" && s.count > 0) {
        const itchTotal = state.itchGames.length;
        const titleText = itchTotal !== s.count
          ? `Open itch.io library tab (${s.count} games of ${itchTotal} total keys)`
          : "Open itch.io library tab";
        return `<button type="button" class="summary-jump-chip px-3 py-2 rounded-full bg-slate-800 hover:bg-slate-700 text-xs cursor-pointer border border-slate-700" data-jump-view="itch" title="${titleText}">${s.label} <span class="text-slate-100 font-semibold ml-1">${s.count}</span> <span class="text-slate-400 ml-0.5">→</span></button>`;
      }
      if (s.count === 0) return "";
      const isActive = activeStore === s.key;
      const title = isActive ? `Clear ${s.label} filter` : `Filter: ${s.label}`;
      return `<button type="button" class="summary-store-chip${isActive ? " active" : ""}" data-store-filter="${escapeAttr(s.key)}" title="${escapeAttr(title)}">${escapeHtml(s.label)} <span class="text-slate-100 font-semibold ml-1">${s.count}</span></button>`;
    })
    .join("");
  const statusChips = renderStatusChipsHtml(visible);
  el.innerHTML = `
    <div class="w-full flex flex-wrap gap-2">
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Games <span class="text-slate-100 font-semibold ml-1">${visible.length}</span>${hiddenCount ? ` <span class="text-slate-500 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</div>
      ${storeChips}
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Backlog hours <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(totalHltb))}h</span></div>
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Played <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(played))}h</span></div>
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg rating <span class="text-slate-100 font-semibold ml-1">${avg}${avg !== "—" ? "%" : ""}</span></div>
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
    return `<button type="button" class="genre-chip px-2 py-1 rounded border border-slate-600 text-xs ${active ? "active" : "bg-slate-700 text-slate-300"}" data-genre="${escapeAttr(genre)}">${escapeHtml(genre)}</button>`;
  }).join("");
  document.getElementById("genreChips").innerHTML = html || '<span class="text-xs text-slate-400">No genres found.</span>';
  updateGenreChipsCollapse();
}

// === Export ===
export function exportTopBacklogMarkdown() {
  const visible = state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)));
  const backlog = visible
    .filter(g => chipStatusKey(g) === "backlog")
    .sort((a, b) => priorityScore(b) - priorityScore(a))
    .slice(0, 20);
  if (!backlog.length) {
    alert("No backlog games to export.");
    return;
  }
  const lines = [
    "# BAKLOG — Top 20 backlog",
    "",
    "| # | Game | Store | Score | HLTB main | Rating |",
    "|---:|---|---|---:|---:|---:|",
  ];
  backlog.forEach((g, i) => {
    const store = normalizeGame(g).store.toUpperCase();
    const h = hltbMain(g);
    const rating = ratingValue(g);
    lines.push(
      `| ${i + 1} | ${g.name.replace(/\|/g, "\\|")} | ${store} | ${priorityScore(g).toFixed(1)} | ${h != null ? `${h}h` : "—"} | ${rating > 0 ? `${rating}%` : "—"} |`,
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
      ng.store, ng.id, g.name, p.status, priorityScore(g).toFixed(2), (g.playtime_minutes / 60).toFixed(1),
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
