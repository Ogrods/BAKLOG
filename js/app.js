// Orchestration entry point. The heavy lifting now lives in focused modules
// (see js/*.js). app.js is responsible for hydrating state, registering the
// downstream-sync callbacks the personal-storage module needs, configuring
// the fetcher-health bridge, wiring the dashboard's dep bag, and then
// kicking off bootstrap + bindEvents.

import { state } from './state.js';
// Side-effect import: installs window.coverFallback / window.markLandscape
// before any module emits row HTML that references them inline.
import './covers.js';
import { installGlobalErrorHandler } from './error-boundary.js';

// Install the global error + unhandled-rejection listeners as early as
// possible — before any other module-level code runs in this file — so that
// errors during the rest of bootstrap also get captured and surfaced.
installGlobalErrorHandler();
import { personalStore, showMigrationBanner } from './personal-store.js';
import {
  fetcherRunner,
  loadFetcherSources,
  configureFetcherHealth,
} from './fetcher-health.js';
import { initConnections } from './connections.js';
import {
  initDashboard,
  scheduleDashboardRender,
} from './dashboard.js';
import { escapeHtml } from './dom-util.js';
import {
  loadPersonal,
  migrateV3,
  stripLegacyTags,
  configureDownstreamSync,
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
import { renderPicks, renderPicksLimitButtons } from './picks-ui.js';
import {
  renderSummary,
  renderStoreChips,
  renderWishlistStoreChips,
  updateCleanupBtnState,
  updateViewChrome,
} from './filters-ui.js';
import {
  setBootCurtainLabel,
  liftBootCurtain,
  hideViewOverlay,
} from './loading-curtain.js';
import { reloadGames, reloadAfterFetcher } from './library-load.js';
import { bindEvents } from './bind-events.js';
import { startDebugOverlay } from './debug-overlay.js';
import { ensureChartJs } from './chart-loader.js';
import { prewarmTableQueryForView } from './table-ui.js';

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

function hydrateState() {
  state.personal = loadPersonal();
  state.prefs = loadPrefs();
  state.sessionPrefs = loadSessionPrefs();
  setBootCurtainLabel(state.prefs.activeView);
}

async function bootstrap() {
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
  }
  migrateV3();
  stripLegacyTags();
  state.prefs.genreFilters = (state.prefs.genreFilters || []).map(aliasCanonicalGenre);
  const VALID_VIEWS = new Set(["dashboard", "library", "wishlist", "itch", "connections"]);
  if (VALID_VIEWS.has(state.prefs.activeView)) {
    state.activeView = state.prefs.activeView;
  }
  applySavedSortForView(state.activeView);
  document.querySelectorAll(".view-tab").forEach(b => b.classList.toggle("active", b.dataset.view === state.activeView));
  savePrefs();
  bindEvents();
  document.getElementById("showScoreColumn").checked = !!state.prefs.showScoreColumn;
  const tableWrap = document.getElementById("tableWrap");
  tableWrap?.classList.toggle("table-hide-score", !state.prefs.showScoreColumn);
  tableWrap?.classList.toggle("table-hide-playtime", state.activeView === "wishlist");
  tableWrap?.classList.toggle("table-hide-lastplayed", state.activeView === "wishlist");
  document.getElementById("genreMode").value = state.prefs.genreFilterMode;
  document.getElementById("quickWinMax").value = state.prefs.quickWinMaxHours;
  document.getElementById("quickWinMaxVal").textContent = state.prefs.quickWinMaxHours;
  document.getElementById("picksContainer").classList.toggle("hidden", state.prefs.picksCollapsed);
  document.getElementById("togglePicks").textContent = state.prefs.picksCollapsed ? "Show" : "Hide";
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
    initConnections();
    const available = await fetcherRunner.probeApi();
    if (!available) return;
    await fetcherRunner.syncFromServer();
    if (state.activeView === "dashboard") fetcherRunner.startDashboardPolling();
  }
  const reloadPromise = reloadGames().catch(() => {
    const banner = document.getElementById("bootErrorBanner");
    if (banner) {
      banner.innerHTML = '<div class="migration-banner-body"><span class="text-amber-400">No library data found. Run fetch scripts (<code class="bg-slate-700 px-1 rounded">fetch_games.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_gog.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_wishlist.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_itad.py</code>, …), then reload.</span></div>';
      banner.classList.remove("hidden");
    }
  });
  // Belt-and-suspenders: if either bootstrap chain rejects (fetcher API
  // unreachable, manifest 404, etc.) we still need to lift the curtain.
  // Without this the boot overlay can persist on Dashboard view because
  // probeApi/syncFromServer threw and Promise.all never settled cleanly.
  const fetcherPromise = bootstrapFetcherChrome().catch(err => {
    console.warn("[bootstrap] fetcher chrome init failed", err);
  });
  try {
    await Promise.all([reloadPromise, fetcherPromise]);
  } finally {
    liftBootCurtain(tBoot);
    hideViewOverlay();
    if (state.activeView === "dashboard") {
      ensureChartJs()
        .then(() => { if (state.activeView === "dashboard") scheduleDashboardRender(); })
        .catch(err => console.warn("[bootstrap] Chart.js load failed", err));
    } else {
      scheduleIdlePrewarm();
    }
  }
  if (migrationInfo.pendingMigration) {
    showMigrationBanner(migrationInfo.pendingMigration, {
      escapeHtml,
      onUploaded: () => reloadGames().then(() => scheduleDashboardRender()),
    });
  }
}

hydrateState();
bootstrap().catch(err => {
  console.error("[bootstrap] unhandled failure — lifting boot curtain", err);
  // Belt-and-suspenders alongside the inline 8s safety net + the try/finally
  // around Promise.all inside bootstrap().
  liftBootCurtain(0, { force: true });
  hideViewOverlay();
});
