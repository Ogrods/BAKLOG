import { state } from './state.js';
import { escapeHtml, isSafeHttpUrl } from './dom-util.js';
import {
  gameKey,
  findGameByKey,
} from './game-core.js';
import {
  getPersonal,
  setPersonal,
  mergeImportedPersonal,
} from './personal-storage.js';
import {
  savePrefs,
  persistCurrentSort,
  setCoopFilterMode,
} from './prefs.js';
import {
  renderTable,
  invalidateTableCache,
  updateBulkBar,
  updateRowInPlace,
  updateHasNotesIndicatorInPlace,
  toggleSelection,
  bulkSetStatus,
  bulkRemove,
  performUndo,
  canUndo,
  hideUndoToast,
  initAlphaNav,
  focusGame,
  focusRow,
  preloadRowHeroEl,
  warmVisibleRowHeroes,
  visibleListForKeyboard,
  scrollToRowIndex,
  openStoreForFocused,
  filteredGames,
  sortedGames,
  cancelPendingScrollTarget,
  initTablePhoneLayout,
  syncSponsoredTableAfterDismiss,
} from './table-ui.js';
import {
  renderPicks,
  normalizePicksLimit,
  renderPicksLimitButtons,
  applyPicksCollapsedState,
} from './picks-ui.js';
import { stopSpotlightRotation } from './dashboard-spotlight.js';
import { recordSponsoredClick } from './anon-metrics.js';
import { dismissSponsoredDeal, refreshSponsoredSurfaces } from './sponsored-deals.js';
import { openCoverGallery } from './cover-gallery.js';
import { initTrophyPopover } from './trophy-popover.js';
import {
  openFiltersDrawer,
  closeFiltersDrawer,
  updateCleanupBtnState,
  updateGenreChipsCollapse,
  refreshFilterUI,
  refreshFilterUIDebounced,
  scheduleTableRerender,
  renderSummary,
  renderStoreChips,
  renderWishlistStoreChips,
  renderGenreChips,
  switchView,
  exportCsv,
  exportTopBacklogMarkdown,
  download,
  applyPrefsChange,
  clearAllFilters,
  showItchNonGamesFromEmptyState,
} from './filters-ui.js';
import {
  getDealInfo,
  syncDealFilterControls,
  drillWishlistDealFilter,
} from './deals.js';
import { reloadGames } from './library-load.js';
import { bindAddGameModal } from './add-game-modal.js';
import { openBugReportDialog } from './bug-report.js';
import { reportError } from './error-boundary.js';
import { bindOrphanPruneUI } from './orphan-prune.js';
import { bindHiddenPanelUI } from './hidden-panel.js';
import { bindColumnPicker } from './column-picker.js';
import { createGlobalKeydownHandler } from './events.js';
import { bindFetcherHealthEvents } from './bind-events-fetcher.js';
import { bindClaimableEvents } from './bind-events-claims.js';
import {
  dashDrillCoop,
  renderDashboardWishlistStats,
} from './dashboard.js';

/**
 * Collapse the picks panel if it's currently expanded.
 *
 * Called when the user clicks a filter chip in #summary (status / store /
 * deal / wishlist-reset). Picks lives above the table, so leaving it open
 * pushes the row count + filtered rows below the fold and the user can't
 * see their click take effect. Collapsing here keeps the persisted pref in
 * sync with the actual DOM state and updates the toggle button label.
 * No-op when picks is already collapsed.
 */
function closePicksIfOpen() {
  if (state.prefs.picksCollapsed === true) return;
  state.prefs.picksCollapsed = true;
  savePrefs();
  applyPicksCollapsedState();
}

const SUMMARY_FILTER_CHIP_SELECTOR =
  ".status-chip, .summary-store-chip, .summary-stale-chip, .summary-deal-chip[data-wishlist-deal-filter], .summary-wishlist-reset";

let _eventsBound = false;

function handleSponsoredDismiss(dismissEl) {
  const id = dismissEl.dataset.sponsorId;
  dismissSponsoredDeal(id);
  if (dismissEl.closest('.sponsored-table-row')) {
    syncSponsoredTableAfterDismiss();
  }
  refreshSponsoredSurfaces(id);
}

export function bindEvents() {
  if (_eventsBound) return;
  _eventsBound = true;
  initTrophyPopover();

  document.getElementById("undoToast")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-undo-action]");
    if (!btn) return;
    if (btn.dataset.undoAction === "undo") performUndo();
    else if (btn.dataset.undoAction === "dismiss") hideUndoToast();
  });

  bindFetcherHealthEvents();

  const onWishlistStatsClick = (e) => {
    const card = e.target.closest("[data-action]");
    if (!card) return;
    const action = card.dataset.action;
    // On the wishlist view itself the deal-hero card opens the actual sale URL
    // (ITAD shop link or Steam store) instead of refocusing the same row that's
    // already visible in the table below. Dashboard path still drills into the row.
    if (action === "deal-hero" && card.dataset.dealUrl && state.activeView === "wishlist") {
      if (isSafeHttpUrl(card.dataset.dealUrl)) window.open(card.dataset.dealUrl, "_blank", "noopener,noreferrer");
      return;
    }
    if ((action === "deal-hero" || action === "deal-steal-jump") && card.dataset.key) {
      focusGame(card.dataset.key);
      return;
    }
    if (action === "sponsored-dismiss") {
      e.preventDefault();
      e.stopPropagation();
      handleSponsoredDismiss(card);
      return;
    }
    if (action === "sponsored-deal") {
      if (!card.dataset.sponsorHouse) recordSponsoredClick(card.dataset.sponsorId);
      if (isSafeHttpUrl(card.dataset.sponsorUrl)) window.open(card.dataset.sponsorUrl, "_blank", "noopener,noreferrer");
      return;
    }
    if (action === "deal-on-sale") {
      drillWishlistDealFilter({ onSaleOnly: true });
      return;
    }
    if (action === "deal-steals") {
      drillWishlistDealFilter({ minDiscount: 50 });
    }
  };
  document.getElementById("dashboardWishlistStats")?.addEventListener("click", onWishlistStatsClick);
  document.getElementById("wishlistDealRadar")?.addEventListener("click", onWishlistStatsClick);

  bindClaimableEvents();

  const onDashListClick = e => {
    const row = e.target.closest('[data-action="dash-list-jump"]');
    if (!row || !row.dataset.key) return;
    if (row.id === "dashboardSpotlight") stopSpotlightRotation();
    focusGame(row.dataset.key);
  };
  document.getElementById("dashPicksVersusCard")?.addEventListener("click", onDashListClick);
  document.getElementById("dashRecentAdditions")?.addEventListener("click", onDashListClick);
  document.getElementById("dashItchRecap")?.addEventListener("click", onDashListClick);
  document.addEventListener('click', (e) => {
    const inDealRail = e.target.closest('#dashboardWishlistStats, #wishlistDealRadar');
    const dismiss = e.target.closest('[data-action="sponsored-dismiss"]');
    if (dismiss && !inDealRail) {
      e.preventDefault();
      e.stopPropagation();
      handleSponsoredDismiss(dismiss);
      return;
    }
    const deal = e.target.closest('[data-action="sponsored-deal"]');
    if (deal && !inDealRail) {
      e.preventDefault();
      e.stopPropagation();
      if (!deal.dataset.sponsorHouse) recordSponsoredClick(deal.dataset.sponsorId);
      if (isSafeHttpUrl(deal.dataset.sponsorUrl)) {
        window.open(deal.dataset.sponsorUrl, '_blank', 'noopener,noreferrer');
      }
    }
  });

  // The sponsored/spotlight dismiss controls render as role="button" spans
  // (they can't be real <button>s when nested inside the card <button>), so
  // keyboard users need an explicit Enter/Space activation to match the mouse
  // click path above.
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
    const dismiss = e.target.closest?.('[data-action="sponsored-dismiss"]');
    if (!dismiss) return;
    e.preventDefault();
    e.stopPropagation();
    handleSponsoredDismiss(dismiss);
  });

  document.getElementById("dashboardMega")?.addEventListener("click", onDashListClick);

  const handleCoopActivate = (e) => {
    const target = e.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "coop-pick-jump" && target.dataset.key) {
      e.stopPropagation();
      focusGame(target.dataset.key);
      return;
    }
    if (action === "coop-drill") {
      try {
        const args = JSON.parse(target.dataset.drill || "{}");
        dashDrillCoop(args);
      } catch (err) { console.error("co-op drill payload error", err); }
    }
  };
  const coopSpotlightEl = document.getElementById("dashboardCoopSpotlight");
  if (coopSpotlightEl) {
    coopSpotlightEl.addEventListener("click", handleCoopActivate);
    coopSpotlightEl.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const target = e.target.closest('[role="button"][data-action]');
      if (!target) return;
      e.preventDefault();
      handleCoopActivate(e);
    });
  }

  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", e => {
      let key = th.dataset.sort;
      // Price header: shift-click swaps to discount % so power users can still
      // surface biggest sales. Plain click sorts by the current price after
      // sales (the visible value), which is what "Price" implies.
      if (key === "deal_price" && e.shiftKey) {
        key = "discount_percent";
      }
      if (state.sortKey === key) state.sortDir *= -1;
      else {
        state.sortKey = key;
        // discount_percent → big sale first; deal_price → cheapest first;
        // everything else → A-Z / oldest first.
        state.sortDir = key === "discount_percent" ? -1 : 1;
      }
      persistCurrentSort();
      renderTable();
    });
  });
  document.getElementById("openFiltersBtn").addEventListener("click", openFiltersDrawer);
  document.getElementById("closeFiltersBtn").addEventListener("click", closeFiltersDrawer);
  document.getElementById("resetDrawerFiltersBtn")?.addEventListener("click", clearAllFilters);
  document.getElementById("filterDrawerBackdrop").addEventListener("click", closeFiltersDrawer);
  document.getElementById("toggleGenreChipsBtn").addEventListener("click", () => {
    state.genreChipsExpanded = !state.genreChipsExpanded;
    updateGenreChipsCollapse();
  });
  const kebabBtn = document.getElementById("kebabBtn");
  const kebabMenu = document.getElementById("kebabMenu");
  kebabBtn.addEventListener("click", e => {
    e.stopPropagation();
    const open = !kebabMenu.classList.contains("open");
    kebabMenu.classList.toggle("open", open);
    kebabBtn.setAttribute("aria-expanded", open ? "true" : "false");
  });
  document.addEventListener("click", () => {
    kebabMenu.classList.remove("open");
    kebabBtn.setAttribute("aria-expanded", "false");
  });
  document.getElementById("coopFilterSegmented")?.addEventListener("click", e => {
    const btn = e.target.closest(".filter-segment[data-coop-mode]");
    if (!btn) return;
    setCoopFilterMode(btn.dataset.coopMode);
    refreshFilterUI();
  });
  // The 6 live filters are stored in state.sessionPrefs (single source of
  // truth); every input event pushes the DOM value into state, then triggers
  // a debounced refresh. The min/max slider value labels also live here so
  // the readout follows the slider without code anywhere else having to know.
  const FILTER_DOM_TO_STATE = {
    search:           el => ({ key: "search",          val: el.value }),
    statusFilter:     el => ({ key: "statusFilter",    val: el.value }),
    unplayedOnly:     el => ({ key: "unplayedOnly",    val: !!el.checked }),
    earlyAccessOnly:  el => ({ key: "earlyAccessOnly", val: !!el.checked }),
    gamePassOnly:     el => ({ key: "gamePassOnly", val: !!el.checked }),
    minRating:        el => ({ key: "minRating",       val: +el.value || 0 }),
    maxHours:         el => ({ key: "maxHours",        val: +el.value || 0 }),
  };
  Object.entries(FILTER_DOM_TO_STATE).forEach(([id, extract]) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener("input", () => {
      const { key, val } = extract(el);
      state.sessionPrefs[key] = val;
      if (id === "minRating") {
        document.getElementById("minRatingVal").textContent = String(val);
      } else if (id === "maxHours") {
        document.getElementById("maxHoursVal").textContent = val >= 200 ? "200+" : String(val);
      }
      refreshFilterUIDebounced({ skipPicks: id === "search" });
    });
  });
  const itchShowNonGamesEl = document.getElementById("itchShowNonGames");
  if (itchShowNonGamesEl) {
    itchShowNonGamesEl.addEventListener("change", () => {
      state.sessionPrefs.itchHideNonGames = !itchShowNonGamesEl.checked;
      refreshFilterUI();
    });
  }
  initAlphaNav();
  const bindDealCheckbox = (id, key) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = !!state.prefs[key];
    el.addEventListener("change", () => {
      applyPrefsChange({ prefs: { [key]: el.checked } });
    });
  };
  bindDealCheckbox("dealOnSaleOnly", "dealOnSaleOnly");
  bindDealCheckbox("dealHistoricalLowOnly", "dealHistoricalLowOnly");
  bindDealCheckbox("dealHideOwned", "dealHideOwned");
  const dealMinDiscountEl = document.getElementById("dealMinDiscount");
  const dealMinDiscountVal = document.getElementById("dealMinDiscountVal");
  if (dealMinDiscountEl) {
    dealMinDiscountEl.value = String(state.prefs.dealMinDiscount || 0);
    dealMinDiscountVal.textContent = String(state.prefs.dealMinDiscount || 0);
    dealMinDiscountEl.addEventListener("input", () => {
      const v = +dealMinDiscountEl.value;
      dealMinDiscountVal.textContent = String(v);
      applyPrefsChange({ prefs: { dealMinDiscount: v } }, { debounced: true });
    });
  }
  const dealMaxPriceEl = document.getElementById("dealMaxPrice");
  const dealMaxPriceVal = document.getElementById("dealMaxPriceVal");
  if (dealMaxPriceEl) {
    const initMax = state.prefs.dealMaxPrice ?? 100;
    dealMaxPriceEl.value = String(initMax);
    dealMaxPriceVal.textContent = initMax >= 100 ? "any" : `$${initMax}`;
    dealMaxPriceEl.addEventListener("input", () => {
      const v = +dealMaxPriceEl.value;
      dealMaxPriceVal.textContent = v >= 100 ? "any" : `$${v}`;
      applyPrefsChange({ prefs: { dealMaxPrice: v } }, { debounced: true });
    });
  }
  const resetDealFiltersBtn = document.getElementById("resetDealFiltersBtn");
  if (resetDealFiltersBtn) {
    resetDealFiltersBtn.addEventListener("click", () => {
      applyPrefsChange(
        {
          prefs: {
            dealOnSaleOnly: false,
            dealHistoricalLowOnly: false,
            dealHideOwned: false,
            dealMinDiscount: 0,
            dealMaxPrice: 100,
          },
        },
        {
          renderers: [
            () => {
              if (dealMinDiscountEl) { dealMinDiscountEl.value = "0"; dealMinDiscountVal.textContent = "0"; }
              if (dealMaxPriceEl) { dealMaxPriceEl.value = "100"; dealMaxPriceVal.textContent = "any"; }
              ["dealOnSaleOnly", "dealHistoricalLowOnly", "dealHideOwned"]
                .forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; });
            },
          ],
        },
      );
    });
  }
  document.getElementById("genreMode").addEventListener("change", e => {
    applyPrefsChange({ prefs: { genreFilterMode: e.target.value } });
  });
  document.getElementById("rowHeroBackdrop").addEventListener("change", e => {
    state.prefs.rowHeroBackdrop = e.target.checked;
    state.prefs.rowHeroBackdropDefaulted = true;
    savePrefs();
    document.body.classList.toggle("row-hero-on", e.target.checked);
    if (e.target.checked) warmVisibleRowHeroes();
  });
  document.getElementById("quickWinMax").addEventListener("input", e => {
    state.prefs.quickWinMaxHours = +e.target.value;
    document.getElementById("quickWinMaxVal").textContent = state.prefs.quickWinMaxHours;
    savePrefs();
    // Only the Quick Wins tab consumes quickWinMaxHours; re-rendering the picks
    // grid on other tabs would needlessly reload every cover (and bounce the
    // landscape detection). Refresh only when the visible tab is affected.
    if (state.prefs.picksTab === "quickWins") renderPicks();
  });
  normalizePicksLimit();
  renderPicksLimitButtons();
  document.getElementById("picksLimitGroup").addEventListener("click", e => {
    const btn = e.target.closest(".picks-limit-btn");
    if (!btn) return;
    state.prefs.picksLimit = +btn.dataset.limit || 16;
    savePrefs();
    renderPicksLimitButtons();
    renderPicks();
  });
  document.getElementById("togglePicks").addEventListener("click", () => {
    state.prefs.picksCollapsed = !(state.prefs.picksCollapsed === true);
    savePrefs();
    applyPicksCollapsedState();
    if (!state.prefs.picksCollapsed) renderPicks();
  });
  document.querySelectorAll(".pick-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      state.prefs.picksTab = tab;
      // Tabs without an explicit pick-view (e.g., the shared "Top Rated") apply
      // to whichever pickView the active view maps to, so save against that.
      const pv = btn.dataset.pickView
        || (state.activeView === "wishlist" ? "wishlist"
          : state.activeView === "itch" ? "itch"
          : "library");
      if (pv === "library") state.prefs.libraryPicksTab = tab;
      if (pv === "itch") state.prefs.itchPicksTab = tab;
      savePrefs();
      renderPicks();
    });
  });
  // The drawer's store-chip row was removed in the filter consolidation;
  // the top-bar summary chips are the only store-filter UI now. Click handling
  // for those lives in the #summary listener below.
  document.getElementById("wishlistStoreChips")?.addEventListener("click", e => {
    const chip = e.target.closest(".wishlist-store-chip");
    if (!chip) return;
    applyPrefsChange(
      { prefs: { wishlistStoreFilter: chip.dataset.wishlistStore || "" } },
      { renderers: [renderWishlistStoreChips] },
    );
  });
  document.getElementById("summary").addEventListener("click", e => {
    // Collapse picks first when the user clicks a filter chip above the table.
    // Picks sits between #summary and the table, so leaving it open hides the
    // filter result below the fold. Excludes .summary-jump-chip (those switch
    // views, not apply filters in-place).
    if (e.target.closest(SUMMARY_FILTER_CHIP_SELECTOR)) {
      closePicksIfOpen();
    }
    const statusChip = e.target.closest(".status-chip");
    if (statusChip) {
      const val = statusChip.dataset.statusFilter;
      const next = state.sessionPrefs.statusFilter === val ? "" : val;
      applyPrefsChange({ sessionPrefs: { statusFilter: next } });
      return;
    }
    const storeChip = e.target.closest(".summary-store-chip");
    if (storeChip) {
      const val = storeChip.dataset.storeFilter || "";
      const next = state.prefs.storeFilter === val ? "" : val;
      applyPrefsChange({ prefs: { storeFilter: next } });
      return;
    }
    const staleChip = e.target.closest(".summary-stale-chip");
    if (staleChip) {
      applyPrefsChange({ sessionPrefs: { staleOnly: !state.sessionPrefs.staleOnly } });
      return;
    }
    const dealChip = e.target.closest(".summary-deal-chip[data-wishlist-deal-filter]");
    if (dealChip) {
      const kind = dealChip.dataset.wishlistDealFilter;
      const patch = {};
      if (kind === "onSale") patch.dealOnSaleOnly = !state.prefs.dealOnSaleOnly;
      else if (kind === "historicalLow") patch.dealHistoricalLowOnly = !state.prefs.dealHistoricalLowOnly;
      else if (kind === "hideOwned") patch.dealHideOwned = !state.prefs.dealHideOwned;
      applyPrefsChange({ prefs: patch }, { renderers: [syncDealFilterControls] });
      return;
    }
    const chip = e.target.closest(".summary-jump-chip");
    if (!chip) return;
    const view = chip.dataset.jumpView;
    if (view) switchView(view);
  });
  document.getElementById("dashboardContent")?.addEventListener("click", e => {
    const chip = e.target.closest("[data-jump-view]");
    if (chip?.dataset.jumpView) switchView(chip.dataset.jumpView);
  });
  document.getElementById("dashboardContainer")?.addEventListener("click", e => {
    if (e.target.closest("[data-dash-goto-connections]")) {
      e.preventDefault();
      switchView("connections");
    }
    if (e.target.closest("[data-dash-goto-library]")) {
      e.preventDefault();
      switchView("library");
    }
  });
  const dedupEl = document.getElementById("crossStoreDedup");
  if (dedupEl) {
    dedupEl.addEventListener("change", () => {
      applyPrefsChange(
        { sessionPrefs: { crossStoreDedup: dedupEl.checked } },
        { recomputeDedup: true, skipDomSync: true },
      );
    });
  }
  document.getElementById("genreChips").addEventListener("click", e => {
    const chip = e.target.closest(".genre-chip");
    if (!chip) return;
    const genre = chip.dataset.genre;
    const cur = state.prefs.genreFilters || [];
    const next = cur.includes(genre) ? cur.filter(x => x !== genre) : [...cur, genre];
    applyPrefsChange({ prefs: { genreFilters: next } }, { renderers: [renderGenreChips] });
  });
  document.getElementById("tbody")?.addEventListener("click", (e) => {
    if (e.target.closest("[data-table-clear-filters]")) {
      e.preventDefault();
      clearAllFilters();
      return;
    }
    if (e.target.closest("[data-table-show-itch-nongames]")) {
      e.preventDefault();
      showItchNonGamesFromEmptyState();
      return;
    }
    if (e.target.closest("[data-table-goto-connections]")) {
      e.preventDefault();
      switchView("connections");
    }
  });
  document.getElementById("tbody").addEventListener("change", e => {
    const t = e.target;
    if (t.classList.contains("row-select")) {
      const tr = t.closest("tr");
      toggleSelection(t.dataset.gameKey, t.checked);
      if (tr) tr.classList.toggle("row-selected", t.checked);
      return;
    }
    if (!t.dataset.gameKey || !t.dataset.field) return;
    const g = findGameByKey(t.dataset.gameKey);
    if (!g) return;
    const field = t.dataset.field;
    setPersonal(g, field, t.value);
    const tr = t.closest("tr");
    if (tr) {
      updateRowInPlace(tr, g);
      if (field === "notes") updateHasNotesIndicatorInPlace(tr, g);
    }
    const statusFilterActive = !!state.sessionPrefs?.statusFilter;
    const sortAffected = state.sortKey === field || state.sortKey === "status";
    if ((field === "status" && (statusFilterActive || state.cleanupModeActive)) || sortAffected) {
      scheduleTableRerender();
    }
  });
  document.getElementById("selectAllVisible").addEventListener("change", e => {
    const list = state._visibleList || sortedGames(filteredGames());
    if (e.target.checked) list.forEach(g => state.selectedKeys.add(gameKey(g)));
    else list.forEach(g => state.selectedKeys.delete(gameKey(g)));
    updateBulkBar();
    invalidateTableCache();
    renderTable();
  });
  document.getElementById("brandMark")?.addEventListener("click", () => {
    window.scrollTo(0, 0);
  });
  document.querySelectorAll(".view-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view || "library";
      if (view === state.activeView) return;
      // Top-tab clicks (never drill-ins, never the dashboard drill helpers)
      // should land the user at the top of the page so they see the header,
      // summary, then picks, then table. Scroll BEFORE switchView so the
      // overlay → new content paints from y=0. Drill-ins go through
      // dashboard-drilldown.js which manages its own scroll target.
      cancelPendingScrollTarget();
      const fromView = state.activeView;
      // Hide dashboard before scrollTo — otherwise jumping to y=0 while still on
      // the dashboard tab briefly exposes the mega hero at the top of the page.
      if (fromView === "dashboard" && view !== "dashboard") {
        document.getElementById("dashboardContainer")?.classList.add("hidden");
      }
      window.scrollTo(0, 0);
      switchView(view);
    });
  });
  document.getElementById("cleanupModeBtn").addEventListener("click", () => {
    if (state.activeView !== "library") return;
    state.cleanupModeActive = !state.cleanupModeActive;
    updateCleanupBtnState();
    state.selectedKeys.clear();
    updateBulkBar();
    state.focusedRowIndex = 0;
    refreshFilterUI();
  });
  document.getElementById("bulkBar")?.addEventListener("click", e => {
    if (e.target.closest("#bulkRemove")) {
      bulkRemove();
      return;
    }
    const btn = e.target.closest(".bulk-status");
    if (btn?.dataset.status) bulkSetStatus(btn.dataset.status);
  });
  document.getElementById("bulkClear").addEventListener("click", () => {
    state.selectedKeys.clear();
    updateBulkBar();
    invalidateTableCache();
    renderTable();
  });
  document.getElementById("tbody").addEventListener("keydown", e => {
    const t = e.target;
    if (!t.classList.contains("notes-input") || e.key !== "Escape") return;
    e.preventDefault();
    const g = findGameByKey(t.dataset.gameKey);
    if (g) t.value = getPersonal(g).notes || "";
    t.blur();
  });
  document.getElementById("tbody").addEventListener("mouseover", e => {
    const tr = e.target.closest("tr.row-has-hero");
    if (tr) preloadRowHeroEl(tr);
  });
  document.getElementById("tbody").addEventListener("click", e => {
    const notesDot = e.target.closest(".has-notes-dot");
    if (notesDot) {
      e.stopPropagation();
      const tr = notesDot.closest("tr[data-row-key]");
      tr?.querySelector(".notes-input")?.focus();
      return;
    }
    const coverEl = e.target.closest(".cover-wrap, .cover");
    if (coverEl) {
      const tr = coverEl.closest("tr[data-row-key]");
      if (tr) {
        e.stopPropagation();
        openCoverGallery(tr.dataset.rowKey);
        return;
      }
    }
    if (!e.target.closest("select, input, a, button, [data-hltb-edit], .has-notes-dot")) {
      const tr = e.target.closest("tr[data-row-key]");
      if (tr) {
        state.focusedRowIndex = Number(tr.dataset.rowIndex || -1);
        focusRow(tr.dataset.rowKey);
      }
    }
    const btn = e.target.closest("[data-hltb-edit]");
    if (!btn) return;
    const g = findGameByKey(btn.dataset.hltbEdit);
    if (!g) return;
    if (e.shiftKey || e.altKey) {
      const existing = getPersonal(g).hltb_override ?? "";
      const next = prompt("Override HLTB main hours (blank to reset):", existing);
      if (next === null) return;
      const value = String(next).trim();
      setPersonal(g, "hltb_override", value === "" ? null : Number(value));
      renderTable();
      return;
    }
    const hltbName = g.hltb_name || g.name || "";
    if (!hltbName) return;
    const url = `https://howlongtobeat.com/?q=${encodeURIComponent(hltbName)}`;
    window.open(url, "_blank", "noopener");
  });
  document.addEventListener("click", e => {
    const card = e.target.closest(".pick-card");
    if (!card) return;
    // #region agent log
    fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'427a43'},body:JSON.stringify({sessionId:'427a43',location:'bind-events.js:pick-card-click',message:'pick card click handler',data:{gameKey:card.dataset.gameKey||null,isSponsored:card.classList.contains('sponsored-pick-card'),fromDismiss:!!e.target.closest('[data-action="sponsored-dismiss"]'),activeView:state.activeView},timestamp:Date.now(),hypothesisId:'A,E'})}).catch(()=>{});
    // #endregion
    if (card) focusGame(card.dataset.gameKey);
  });
  document.addEventListener("keydown", createGlobalKeydownHandler({
    canUndo,
    performUndo,
    closeFiltersDrawer,
    updateBulkBar,
    renderTable,
    visibleListForKeyboard,
    scrollToRowIndex,
    openStoreForFocused,
    setPersonal,
    gameKey,
    toggleSelection,
  }));
  const runPickForMe = (e) => {
    let list = filteredGames();
    if (state.activeView === "library") {
      if (!e.shiftKey) list = list.filter(g => getPersonal(g).status === "backlog");
    } else if (!e.shiftKey) {
      const onSale = list.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
      if (onSale.length) list = onSale;
    }
    if (!list.length) return;
    const pick = list[Math.floor(Math.random() * list.length)];
    focusGame(gameKey(pick));
  };
  document.getElementById("pickForMe").addEventListener("click", runPickForMe);
  document.getElementById("pickForMeKebab")?.addEventListener("click", (e) => {
    document.getElementById("kebabMenu")?.classList.remove("open");
    runPickForMe(e);
  });
  document.getElementById("reloadData").addEventListener("click", async () => {
    kebabMenu.classList.remove("open");
    try { await reloadGames(); } catch { alert("Could not reload library files. Run the fetch scripts (fetch_games.py, fetch_gog.py, etc.) and reload."); }
  });
  kebabMenu.querySelectorAll("button, label").forEach(el => {
    el.addEventListener("click", () => kebabMenu.classList.remove("open"));
  });
  bindAddGameModal();
  bindOrphanPruneUI();
  bindHiddenPanelUI();
  bindColumnPicker();
  document.getElementById("exportCsv").addEventListener("click", exportCsv);
  document.getElementById("exportTopBacklog")?.addEventListener("click", exportTopBacklogMarkdown);
  document.getElementById("exportPersonal").addEventListener("click", () => download("baklog-personal.json", JSON.stringify(state.personal, null, 2), "application/json"));
  function showKebabBanner(message, { error = false } = {}) {
    const banner = document.getElementById('bootErrorBanner');
    if (!banner) return;
    const tone = error ? 'text-red-400' : 'text-amber-400';
    banner.innerHTML = `<div class="migration-banner-body"><span class="${tone}">${escapeHtml(message)}</span></div>`;
    banner.classList.remove('hidden');
  }

  document.getElementById("reportBug")?.addEventListener("click", () => {
    openBugReportDialog();
  });
  document.getElementById("checkUpdates")?.addEventListener("click", async () => {
    kebabMenu.classList.remove("open");
    try {
      const res = await fetch('/api/update-check');
      if (!res.ok) {
        showKebabBanner(`Could not check for updates (server returned ${res.status}).`);
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (data.error) {
        showKebabBanner(`Could not check for updates: ${data.error}`);
        return;
      }
      if (data.update_available) {
        const url = data.url ? ` Download: ${data.url}` : '';
        showKebabBanner(`Update available: v${data.latest} (you have v${data.current}).${url}`);
        return;
      }
      showKebabBanner(`You're on the latest release (v${data.current}).`);
    } catch (err) {
      showKebabBanner(`Update check failed: ${err?.message || err}`, { error: true });
    }
  });
  document.getElementById("copyDiagnostics")?.addEventListener("click", async () => {
    kebabMenu.classList.remove("open");
    try {
      const res = await fetch('/api/diagnostics');
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || 'Diagnostics request failed');
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      showKebabBanner('Diagnostics copied to clipboard.');
    } catch (err) {
      showKebabBanner(`Copy diagnostics failed: ${err?.message || err}`, { error: true });
    }
  });
  document.getElementById("joinDiscord")?.addEventListener("click", () => {
    kebabMenu.classList.remove("open");
  });
  document.getElementById("importNotes").addEventListener("change", async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      mergeImportedPersonal(JSON.parse(await file.text()));
      renderSummary();
      renderPicks();
      renderTable();
    } catch (err) {
      console.warn('[importNotes] invalid JSON', err);
      reportError(err, { source: 'importNotes', kind: 'import' });
      const banner = document.getElementById('bootErrorBanner');
      if (banner) {
        banner.textContent = 'Notes import failed - file is not valid JSON.';
        banner.classList.remove('hidden');
      }
    }
    e.target.value = "";
  });
  initTablePhoneLayout();
}
