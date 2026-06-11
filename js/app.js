// Orchestration entry point. The heavy lifting now lives in focused modules
// (see js/*.js). app.js is responsible for hydrating state, registering the
// downstream-sync callbacks the personal-storage module needs, configuring
// the fetcher-health bridge, wiring the dashboard's dep bag, and then
// kicking off bootstrap + bindEvents.

import { state } from './state.js';
// Side-effect import: installs window.coverFallback / window.markLandscape
// before any module emits row HTML that references them inline.
import './covers.js';
import { installGlobalErrorHandler, registerBugBundleContext, reportError } from './error-boundary.js';
import { initScrollLock } from './scroll-lock.js';

// Install the global error + unhandled-rejection listeners as early as
// possible — before any other module-level code runs in this file — so that
// errors during the rest of bootstrap also get captured and surfaced.
installGlobalErrorHandler();
import { personalStore, showMigrationBanner } from './personal-store.js';
import {
  fetcherRunner,
  loadFetcherSources,
  configureFetcherHealth,
  ensureProfileScopedFetcherState,
} from './fetcher-health.js';
import { startMetrics } from './anon-metrics.js';
import { initAuthGate } from './auth-gate.js';
import { initConnections, isItchTabAvailable } from './connections.js';
import {
  initDashboard,
  scheduleDashboardRender,
} from './dashboard.js';
import { escapeHtml, syncCheckboxLabelTitles } from './dom-util.js';
import {
  loadPersonal,
  loadLibraryFirstSeen,
  migrateV3,
  stripLegacyTags,
  seedPreHiddenDefaults,
  configureDownstreamSync,
  installPersonalStorageSync,
} from './personal-storage.js';
import {
  loadPrefs,
  loadSessionPrefs,
  savePrefs,
  applySavedSortForView,
  syncFilterDomFromState,
} from './prefs.js';
import { aliasCanonicalGenre } from './genres.js';
import { renderBulkStatusButtons, recomputeCrossStoreHidden } from './game-core.js';
import { renderPicks, renderPicksLimitButtons, applyPicksCollapsedState } from './picks-ui.js';
import {
  renderSummary,
  renderStoreChips,
  renderWishlistStoreChips,
  updateCleanupBtnState,
  updateViewChrome,
  collectActiveFilters,
  syncViewTabAria,
} from './filters-ui.js';
import {
  setBootCurtainLabel,
  liftBootCurtain,
  hideViewOverlay,
} from './loading-curtain.js';
import { reloadGames, reloadAfterFetcher, finishEmptyLibraryLoad } from './library-load.js';
import { initLibraryWatches } from './library-watch.js';
import { runLibraryCountDemo, runLibraryCountSmallDemo, armLibraryCountAnimations } from './library-count-animation.js';
import { bindEvents } from './bind-events.js';
import { initProfiles } from './profiles.js';
import { startDebugOverlay } from './debug-overlay.js';
import { ensureChartJs } from './chart-loader.js';
import { suppressChartStaggerForBoot, resizeRibbonCharts } from './dashboard-charts.js';
import { prewarmTableQueryForView, tableFingerprint } from './table-ui.js';
import { applyColumnVisibility } from './table-columns.js';
import { initBugReportDialog } from './bug-report.js';
import {
  applyProTabVisibility,
  consumeCheckoutQuery,
  consumeProHash,
  handleCheckoutSuccessReturn,
  wireProView,
} from './pro-view.js';

// Personal-storage's setPersonal triggers a downstream render of
// summary/picks/dashboard. Those callbacks live in filters-ui/picks-ui/
// dashboard, which themselves depend on game-core/personal-storage; wiring
// them via this register call avoids a hard import cycle.
configureDownstreamSync({
  renderSummary,
  scheduleDashboardRender,
  renderPicks,
});

// Fetcher-health needs to ask the library-load layer for fresh data after a
// fetcher run completes. Wired here for the same reason — keeps library-load
// out of fetcher-health's import graph.
configureFetcherHealth({ reloadGames, reloadAfterFetcher });

// Wire the bug-bundle's runtime context. error-boundary.js is intentionally
// dependency-free so it can be installed before anything else loads (catches
// boot-time errors). The fingerprint + active-filter-count come from
// table-ui / filters-ui, which load later — register the lookups here so the
// "Copy bug bundle" button can include them.
registerBugBundleContext({
  getFingerprint: tableFingerprint,
  getActiveFilterCount: () => collectActiveFilters().length,
  getActiveView: () => state.activeView,
});

function hydrateState() {
  state.personal = loadPersonal();
  state.prefs = loadPrefs();
  state.sessionPrefs = loadSessionPrefs();
  state.libraryFirstSeenByKey = loadLibraryFirstSeen();
  setBootCurtainLabel(state.prefs.activeView);
  installPersonalStorageSync();
}

async function bootstrap() {
  initScrollLock();
  await initAuthGate();
  const checkoutReturn = consumeCheckoutQuery();
  if (!checkoutReturn) consumeProHash();
  ensureProfileScopedFetcherState();
  const tBoot = typeof performance !== "undefined" ? performance.now() : Date.now();
  // Dashboard now uses direct ES imports for its dependencies (game-core,
  // deals, genres, personal-storage, prefs, filters-ui, table-ui). The
  // initDashboard() call stays as a hook in case the dashboard ever needs
  // first-paint setup that has to happen before the first render.
  initDashboard();
  let migrationInfo = { migrated: true, pendingMigration: null };
  try {
    migrationInfo = await personalStore.init();
  } catch (err) {
    console.warn("[personalStore] init failed, falling back to localStorage", err);
    reportError(err, { source: "personalStore.init", kind: "bootstrap" });
  }
  migrateV3();
  stripLegacyTags();
  seedPreHiddenDefaults();
  state.prefs.genreFilters = (state.prefs.genreFilters || []).map(aliasCanonicalGenre);
  const VALID_VIEWS = new Set(["dashboard", "library", "wishlist", "itch", "connections", "pro"]);
  if (VALID_VIEWS.has(state.prefs.activeView)) {
    state.activeView = state.prefs.activeView;
  }
  applySavedSortForView(state.activeView);
  syncViewTabAria(state.activeView);
  savePrefs();
  bindEvents();
  wireProView();
  applyProTabVisibility();
  if (state.prefs.shareAnonStats) startMetrics();
  await initProfiles();
  document.getElementById("rowHeroBackdrop").checked = !!state.prefs.rowHeroBackdrop;
  document.body.classList.toggle("row-hero-on", !!state.prefs.rowHeroBackdrop);
  syncCheckboxLabelTitles();
  applyColumnVisibility(state.activeView);
  document.getElementById("genreMode").value = state.prefs.genreFilterMode;
  document.getElementById("quickWinMax").value = state.prefs.quickWinMaxHours;
  document.getElementById("quickWinMaxVal").textContent = state.prefs.quickWinMaxHours;
  applyPicksCollapsedState();
  // Hide duplicates is a session pref (state.sessionPrefs.crossStoreDedup) —
  // defaults on each reload via loadSessionPrefs(); never persisted.
  recomputeCrossStoreHidden();
  const dedupEl = document.getElementById("crossStoreDedup");
  if (dedupEl) dedupEl.checked = !!state.sessionPrefs.crossStoreDedup;
  // itchHideNonGames is a session pref (state.sessionPrefs.itchHideNonGames);
  // defaults on each reload via loadSessionPrefs(), never persisted.
  const itchShowNonGamesEl = document.getElementById("itchShowNonGames");
  if (itchShowNonGamesEl) itchShowNonGamesEl.checked = !state.sessionPrefs.itchHideNonGames;
  // The 6 live filter controls (search/status/unplayed/early-access/min-rating/max-hours)
  // are also session prefs; push their defaults into the DOM so the visible
  // inputs match the freshly-loaded state.
  syncFilterDomFromState();
  updateCleanupBtnState();
  updateViewChrome();
  if (state.activeView === "library" && state.prefs.picksTab === "wishlistDeals") {
    state.prefs.picksTab = state.prefs.libraryPicksTab || "topRated";
    savePrefs();
  }
  if (state.activeView === "wishlist" && state.prefs.picksTab !== "wishlistDeals") {
    state.prefs.picksTab = "wishlistDeals";
    savePrefs();
  }
  if (state.activeView === "itch") {
    const itchTab = state.prefs.itchPicksTab || "topRated";
    if (state.prefs.picksTab === "wishlistDeals" || !state.prefs.picksTab) {
      state.prefs.picksTab = itchTab;
      savePrefs();
    }
  }
  renderStoreChips();
  renderWishlistStoreChips();
  renderBulkStatusButtons();
  renderPicksLimitButtons();
  startDebugOverlay();
  initBugReportDialog();
  function scheduleIdlePrewarm() {
    const run = () => {
      if (state.activeView === "library" && state.dashboardDataReady) {
        prewarmTableQueryForView("wishlist").catch(() => {});
      }
    };
    if (typeof requestIdleCallback === "function") requestIdleCallback(run, { timeout: 4000 });
    else setTimeout(run, 2000);
  }
  /** Load fetcher manifest + probe API in parallel with library JSON so the
   *  first scheduleDashboardRender (from applyMergedLibrary) paints real chips. */
  async function bootstrapFetcherChrome() {
    await loadFetcherSources();
    // Await the first /api/auth/status so the post-boot scheduleDashboardRender
    // below evaluates the onboarding wizard with real connection state (avoids
    // a "Welcome" flash before status resolves). refreshConnections swallows
    // its own errors, so this never rejects the boot chain.
    await initConnections();
    const available = await fetcherRunner.probeApi();
    if (!available) return;
    try {
      const cfgRes = await fetch('/api/config');
      if (cfgRes.ok) {
        const cfg = await cfgRes.json();
        if (cfg.running_from_temp) {
          const banner = document.getElementById('bootErrorBanner');
          if (banner) {
            banner.innerHTML = '<div class="migration-banner-body"><span class="text-amber-400">BAKLOG is running from a temporary folder. Unzip it to Desktop or Documents before connecting stores, or your data may be lost.</span></div>';
            banner.classList.remove('hidden');
          }
        }
      }
    } catch {
      /* non-fatal */
    }
    await fetcherRunner.syncFromServer();
    if (state.activeView === "dashboard") fetcherRunner.startDashboardPolling();
  }
  const reloadPromise = reloadGames().catch(async () => {
    const banner = document.getElementById("bootErrorBanner");
    if (banner) {
      banner.innerHTML = '<div class="migration-banner-body"><span class="text-amber-400">No library data yet. Open <strong>Connections</strong>, connect a store, and your games will appear here.</span></div>';
      banner.classList.remove("hidden");
    }
    await finishEmptyLibraryLoad();
  });
  // Belt-and-suspenders: if either bootstrap chain rejects (fetcher API
  // unreachable, manifest 404, etc.) we still need to lift the curtain.
  // Without this the boot overlay can persist on Dashboard view because
  // probeApi/syncFromServer threw and Promise.all never settled cleanly.
  const fetcherPromise = bootstrapFetcherChrome().catch(err => {
    console.warn("[bootstrap] fetcher chrome init failed", err);
    reportError(err, { source: "bootstrapFetcherChrome", kind: "bootstrap" });
  });
  try {
    await Promise.all([reloadPromise, fetcherPromise]);
  } finally {
    suppressChartStaggerForBoot();
    liftBootCurtain(tBoot);
    hideViewOverlay();
    if (state.activeView === "dashboard") {
      requestAnimationFrame(() => resizeRibbonCharts());
    }
    if (state.activeView === "itch" && !isItchTabAvailable()) {
      state.activeView = "dashboard";
      state.prefs.activeView = "dashboard";
      savePrefs();
      updateViewChrome({ skipDashboardSchedule: true });
    }
    // Dashboard still renders after lift (Chart.js is heavy); the boot curtain
    // covers the empty shell until ensureChartJs + scheduleDashboardRender run.
    if (state.activeView === "dashboard") {
      ensureChartJs()
        .then(() => { if (state.activeView === "dashboard") scheduleDashboardRender(); })
        .catch(err => {
          console.warn("[bootstrap] Chart.js load failed", err);
          reportError(err, { source: "ensureChartJs", kind: "bootstrap" });
        });
    } else if (state.activeView === "pro") {
      void handleCheckoutSuccessReturn();
    } else {
      scheduleIdlePrewarm();
    }
    // Arm the count-up combat text only AFTER boot. The initial page-load
    // count-up (including any 0 -> full jump during boot) stays silent; popups
    // only appear when a live fetcher/manual action adds games afterward.
    armLibraryCountAnimations();
    initLibraryWatches();
    if (!fetcherRunner.isApiAvailable()) {
      void import('./claimable.js').then(m => m.startClaimableReadOnlyPolling());
    }
  }
  if (migrationInfo.pendingMigration) {
    showMigrationBanner(migrationInfo.pendingMigration, {
      escapeHtml,
      onUploaded: () => reloadGames().then(() => scheduleDashboardRender()),
    });
  }

  // ?demo=count auto-fires the library-count 1UP demo (3-6 fake store
  // landings on the hero number). Useful for screen recordings without
  // burning a real refresh. Window-global baklogDemoLibraryCount() works
  // at any time from devtools.
  try {
    const params = new URLSearchParams(window.location.search);
    const demo = params.get('demo');
    if (state.activeView === 'dashboard') {
      if (demo === 'count') setTimeout(() => runLibraryCountDemo(), 1200);
      else if (demo === 'count-small') setTimeout(() => runLibraryCountSmallDemo(), 1200);
    }
  } catch (_) {}
}

bootstrap().catch(err => {
  console.error("[bootstrap] unhandled failure", err);
  if (document.documentElement.hasAttribute('data-auth-required')) {
    return;
  }
  // Belt-and-suspenders alongside the inline 8s safety net + the try/finally
  // around Promise.all inside bootstrap().
  liftBootCurtain(0, { force: true });
  hideViewOverlay();
});
