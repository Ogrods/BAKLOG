// Dashboard orchestrator. Owns the render pipeline fingerprint diffing, the
// mega-hero shell, and the public re-exports consumed by the rest of the app.
// Implementation lives in sibling modules:
//   dashboard-shared      — constants + animateCount + dashboardLibraryGames
//   dashboard-spotlight   — rotating hero card
//   dashboard-insights    — insight ticker + marquee
//   dashboard-cards       — coop / picks-versus / wishlist stats / itch recap
//   dashboard-charts      — Chart.js + scatter cluster picker
//   dashboard-drilldown   — dash* drill-down helpers

import { state } from './state.js';
import { escapeHtml, formatNum } from './dom-util.js';
import { renderDashboardFetcherHealth } from './fetcher-health.js';
import { gameKey, hltbMain, ratingValue, normalizeGame, combinedPlaytime, itchIsGame } from './game-core.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo } from './deals.js';
import { ensureChartJs } from './chart-loader.js';
import { animateCount, countUpDurationForDelta, dashboardLibraryGames, sortStoresByDisplayOrder } from './dashboard-shared.js';
import { isSurfaceAnimating } from './library-count-animation.js';
import { destroyDashboardCharts, replayDashboardChartAnimations, renderDashboardCharts, resetScatterListView, setRibbonChartsResponsive, suppressChartStaggerForBoot } from './dashboard-charts.js';
import { renderDashboardCoopSpotlight, renderDashboardPicksVersus, renderDashboardRecentAdditions, renderDashboardWishlistStats, renderDashboardItchRecap } from './dashboard-cards.js';
import { pickSpotlightGames, renderSpotlightHtml, syncSpotlightInMega, primeSpotlightArt, startSpotlightRotation, stopSpotlightRotation, getSpotlightPool, setSpotlightCurrentKey } from './dashboard-spotlight.js';
import { buildInsightPool, buildMarqueeItems, renderMarqueeHtml, startInsightRotation, stopInsightRotation, observeMarqueeSpeed } from './dashboard-insights.js';
import { connectedProviderCount, authStatusLoaded } from './connections.js';
import { getLibrarySnapshot } from './sabermetrics.js';
import { THEME_CHANGE_EVENT } from './theme.js';
import { storeLogoStripHtml } from './store-logos.js';

// Re-exports — dashboard.js stays the single public entry point for the
// dashboard surface. External callers (app.js / bind-events.js / etc.)
// import from './dashboard.js' as before.
export { dashboardLibraryGames, HLTB_BUCKETS } from './dashboard-shared.js';
export { destroyDashboardCharts, replayDashboardChartAnimations } from './dashboard-charts.js';
export { renderDashboardWishlistStats } from './dashboard-cards.js';
export { stopSpotlightRotation } from './dashboard-spotlight.js';
export { stopInsightRotation } from './dashboard-insights.js';
export { dashDrillCoop } from './dashboard-drilldown.js';

// Kept for backwards compatibility; the dep-bag wiring is long gone and the
// old c('fnName') shim has been replaced with direct ES imports throughout.
// initDashboard remains as a hook for any future first-paint setup.
export function initDashboard() {}

export function stopDashboardRotations() {
  stopInsightRotation();
  stopSpotlightRotation();
  resetScatterListView();
}

let _dashboardRenderTimer = null;
let _dashboardRenderPending = false;
let _dashCountersInitialized = false;
let _dashMegaShellBuilt = false;
let _dashRenderedFingerprint = "";
const _dashLastCounters = {};
let _marqueeItemsKey = "";
let _marqueeSpeedDisconnect = null;

// Entrance animations may only replay when switchView('dashboard') sets the
// token and calls renderDashboard({ replay: true }). Bootstrap schedules and
// personalStore.notify never set the token, so a second schedule after the
// first full render is a no-op instead of chart.reset() + update() again.
let _dashReplayAllowed = false;
let _dashRenderInFlight = false;
const _dashRenderStats = {
  full: 0,
  replay: 0,
  skippedReentrant: 0,
  skippedAutoReplay: 0,
  lastFullAt: 0,
};
if (typeof window !== "undefined") window.__baklogDash = { stats: _dashRenderStats };

/** Only switchView('dashboard') should call this, bracketing renderDashboard({ replay: true }). */
export function setDashReplayAllowed(allowed) {
  _dashReplayAllowed = !!allowed;
}

export function dashboardFingerprint() {
  const seen = state.libraryFirstSeenByKey || {};
  let recentCount = 0;
  let recentMax = 0;
  for (const at of Object.values(seen)) {
    if (at > 0) {
      recentCount++;
      if (at > recentMax) recentMax = at;
    }
  }
  let dealSig = 0;
  for (const g of state.wishlistGames || []) {
    const d = getDealInfo(g);
    if (d) dealSig += (d.cut || 0) + (d.isHistoricalLow ? 1000 : 0);
  }
  return JSON.stringify({
    // Omit _dataVersion — it bumps on every merge (including no-op wishlist
    // re-fetches) and would defeat this fingerprint, forcing chart teardown.
    lg: dashboardLibraryGames().length,
    itch: (state.itchGames || []).filter(itchIsGame).length,
    qw: state.prefs.quickWinMaxHours || 0,
    ihn: !!state.sessionPrefs.itchHideNonGames,
    rc: recentCount,
    rm: recentMax,
    ds: dealSig,
    // Charts read CSS accent tokens at render time; fold the active theme in so
    // switching back to the dashboard after a theme change repaints the charts.
    th: (typeof document !== "undefined" && document.documentElement.getAttribute("data-theme")) || "default",
  });
}

function computeMegaHeroStats(games, snap) {
  const backlogHrs = snap.backlogHrs;
  const playedHrs = snap.playedHrs;
  const completion = snap.nonSkip ? Math.round(snap.completionRate * 100) : 0;
  const rated = games.filter(g => ratingValue(g) > 0);
  const avgRating = rated.length ? Math.round(rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length) : " - ";
  const wlDeals = state.wishlistGames.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
  const storeCountMap = {};
  for (const g of games) {
    const s = normalizeGame(g).store;
    storeCountMap[s] = (storeCountMap[s] || 0) + 1;
  }
  const itchGames = (state.itchGames || []).filter(itchIsGame);
  if (itchGames.length) storeCountMap.itch = (storeCountMap.itch || 0) + itchGames.length;
  const storeKeys = sortStoresByDisplayOrder(Object.keys(storeCountMap));
  const stores = storeKeys.length;
  const years = backlogHrs > 0 ? (backlogHrs / (2 * 365)).toFixed(1) : "0";
  return {
    total: games.length + itchGames.length,
    backlogHrs,
    playedHrs,
    completion,
    avgRating,
    wlDeals,
    stores,
    storeKeys,
    years,
  };
}

function applyMegaHeroCounters(stats) {
  const fmtH = n => `${formatNum(Math.round(n))}h`;
  const fmtN = n => formatNum(Math.round(n));
  const fmtPct = n => `${Math.round(n)}%`;
  const counters = [
    { id: "dashHeroCount", to: stats.total, format: fmtN },
    { id: "dashHeroPlayed", to: Math.round(stats.playedHrs), format: fmtH },
    { id: "dashHeroBacklog", to: Math.round(stats.backlogHrs), format: fmtH },
  ];
  if (stats.avgRating !== " - ") {
    counters.push({ id: "dashHeroAvg", to: stats.avgRating, format: fmtPct });
  }
  for (const item of counters) {
    const node = document.getElementById(item.id);
    if (!node) continue;
    const prev = _dashLastCounters[item.id];
    if (_dashCountersInitialized) {
      // dashHeroCount may already be mid-roll from fireLibraryCountFlash; don't snap.
      if (isSurfaceAnimating(node)) {
        _dashLastCounters[item.id] = item.to;
        continue;
      }
      if (item.id === 'dashHeroCount' && Number.isFinite(prev) && item.to > prev) {
        animateCount(node, prev, item.to, item.format, countUpDurationForDelta(item.to - prev), { easeInOut: true });
      } else {
        node.textContent = item.format(item.to);
      }
    } else {
      if (item.id === 'dashHeroCount') {
        animateCount(node, 0, item.to, item.format, countUpDurationForDelta(item.to), { easeInOut: true });
      } else {
        animateCount(node, 0, item.to, item.format, 1000);
      }
    }
    _dashLastCounters[item.id] = item.to;
  }
  _dashCountersInitialized = true;
}

let _resizeQuietInstalled = false;
let _resizeQuietTimer = 0;
// Pause ribbon chart responsive relayout and spotlight float/sheen animations
// while the window is actively resizing (css keys off html.ui-resizing), then
// restore ~200ms after resize settles.
function ensureResizeQuiet() {
  if (_resizeQuietInstalled) return;
  _resizeQuietInstalled = true;
  const root = document.documentElement;
  window.addEventListener('resize', () => {
    const wasResizing = root.classList.contains('ui-resizing');
    root.classList.add('ui-resizing');
    if (!wasResizing) setRibbonChartsResponsive(false);
    if (_resizeQuietTimer) clearTimeout(_resizeQuietTimer);
    _resizeQuietTimer = setTimeout(() => {
      _resizeQuietTimer = 0;
      root.classList.remove('ui-resizing');
      setRibbonChartsResponsive(true);
    }, 200);
  }, { passive: true });
}

function wireMarqueeSpeed(rootEl) {
  ensureResizeQuiet();
  if (_marqueeSpeedDisconnect) {
    _marqueeSpeedDisconnect();
    _marqueeSpeedDisconnect = null;
  }
  _marqueeSpeedDisconnect = observeMarqueeSpeed(rootEl || document.getElementById('dashboardMega'));
}

function updateDashboardMegaInPlace(games, stats, spotlight, spotlightPool, marqueeItems, snap) {
  const el = document.getElementById("dashboardMega");
  if (!el) return;
  el.className = spotlight ? 'dash-mega dash-mega--has-spotlight' : 'dash-mega';
  syncSpotlightInMega(el, spotlight);
  const sub = el.querySelector('.dash-hero-sub');
  if (sub) {
    sub.textContent = `games owned across ${stats.stores} stores`;
    sub.title = 'Library size and number of distinct storefronts';
  }
  const storeStrip = el.querySelector('.dash-hero-stores');
  if (storeStrip) {
    storeStrip.innerHTML = stats.storeKeys.length
      ? storeLogoStripHtml(stats.storeKeys, { size: 'md' })
      : '';
    storeStrip.hidden = !stats.storeKeys.length;
  }
  const countHost = el.querySelector('.library-count-host, #dashHeroCount');
  if (countHost) countHost.title = 'Total games in your merged library across all connected stores';
  const tagline = el.querySelector('.dash-hero-tagline');
  if (tagline) {
    tagline.innerHTML = `
        <span title="Finished share of library excluding skipped games"><strong>${stats.completion}%</strong> complete</span>
        <span class="sep">·</span>
        <span title="Backlog HLTB main hours ÷ (2 hours × 365 days)"><strong>${stats.years}</strong> yrs to clear at 2h/day</span>
        <span class="sep">·</span>
        <span title="Wishlist items with an active discount right now"><strong>${escapeHtml(formatNum(stats.wlDeals))}</strong> deals live</span>`;
  }
  applyMegaHeroCounters(stats);
  const marqueeKey = marqueeItems.map(it => `${it.glyph}|${it.label}|${it.valueHtml}`).join("\n");
  if (marqueeKey !== _marqueeItemsKey) {
    _marqueeItemsKey = marqueeKey;
    const marquee = document.getElementById('dashboardMarquee');
    if (marquee) marquee.outerHTML = renderMarqueeHtml(marqueeItems);
    else {
      const divider = el.querySelector('.dash-mega-divider');
      divider?.insertAdjacentHTML('beforebegin', renderMarqueeHtml(marqueeItems));
    }
    wireMarqueeSpeed(el);
  }
  startInsightRotation(buildInsightPool(games, snap));
  startSpotlightRotation(spotlightPool);
}

function renderDashboardMega(games, snap) {
  const stats = computeMegaHeroStats(games, snap);
  const el = document.getElementById("dashboardMega");
  if (!el) return;

  const spotlightPool = pickSpotlightGames(games);
  const spotlight = spotlightPool[0] || null;
  if (spotlight) setSpotlightCurrentKey(gameKey(spotlight));
  else setSpotlightCurrentKey(null);
  const marqueeItems = buildMarqueeItems(games, snap);

  if (_dashMegaShellBuilt && document.getElementById('dashHeroCount')) {
    updateDashboardMegaInPlace(games, stats, spotlight, spotlightPool, marqueeItems, snap);
    return;
  }

  _dashMegaShellBuilt = true;
  el.className = spotlight ? 'dash-mega dash-mega--has-spotlight' : 'dash-mega';

  el.innerHTML = `
    <div class="dash-mega-hero">
      ${spotlight ? renderSpotlightHtml(spotlight) : ''}
      <div class="dash-hero-eyebrow">Your library</div>
      <span class="library-count-host" data-libcount-host title="Total games in your merged library across all connected stores"><span class="dash-hero-number" id="dashHeroCount">${escapeHtml(formatNum(stats.total))}</span></span>
      <div class="dash-hero-sub" title="Library size and number of distinct storefronts">games owned across ${escapeHtml(String(stats.stores))} stores</div>
      <div class="dash-hero-stores" aria-label="Stores in your library"${stats.storeKeys.length ? '' : ' hidden'}>${stats.storeKeys.length ? storeLogoStripHtml(stats.storeKeys, { size: 'md' }) : ''}</div>
      <div class="dash-hero-tagline">
        <span title="Finished share of library excluding skipped games"><strong>${stats.completion}%</strong> complete</span>
        <span class="sep">·</span>
        <span title="Backlog HLTB main hours ÷ (2 hours × 365 days)"><strong>${stats.years}</strong> yrs to clear at 2h/day</span>
        <span class="sep">·</span>
        <span title="Wishlist items with an active discount right now"><strong>${escapeHtml(formatNum(stats.wlDeals))}</strong> deals live</span>
      </div>
      <div class="dash-hero-pillars">
        <div class="dash-hero-pillar" title="Sum of playtime across all games, in hours">
          <div class="dash-hero-pillar-value" id="dashHeroPlayed">${escapeHtml(formatNum(Math.round(stats.playedHrs)))}h</div>
          <div class="dash-hero-pillar-label">Played</div>
        </div>
        <div class="dash-hero-pillar" title="Sum of HowLongToBeat main-story hours across backlog games">
          <div class="dash-hero-pillar-value" id="dashHeroBacklog">${escapeHtml(formatNum(Math.round(stats.backlogHrs)))}h</div>
          <div class="dash-hero-pillar-label">Backlog</div>
        </div>
        <div class="dash-hero-pillar" title="Mean review % across rated games">
          <div class="dash-hero-pillar-value" id="dashHeroAvg">${stats.avgRating === " - " ? " - " : escapeHtml(String(stats.avgRating)) + "%"}</div>
          <div class="dash-hero-pillar-label">Avg review</div>
        </div>
      </div>
      <span id="dashboardInsight" class="dash-insight" aria-live="polite"></span>
    </div>
    ${renderMarqueeHtml(marqueeItems)}
    <div class="dash-mega-divider" aria-hidden="true"></div>
    <div class="dash-ribbon">
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow" title="Share of library per connected store - click chart to filter">Library by store</div>
        <div class="dash-ribbon-chart"><canvas id="chartStoreDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonStoreHeadline"></div>
      </div>
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow" title="Personal backlog statuses - click chart to filter">Status breakdown</div>
        <div class="dash-ribbon-chart"><canvas id="chartStatusDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonStatusHeadline"></div>
      </div>
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow" title="Steam review descriptor mix - click chart to filter by rating">Review sentiment</div>
        <div class="dash-ribbon-chart"><canvas id="chartReviewDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonReviewHeadline"></div>
      </div>
    </div>
  `;

  applyMegaHeroCounters(stats);
  primeSpotlightArt(document.getElementById('dashboardSpotlight'));
  startInsightRotation(buildInsightPool(games, snap));
  startSpotlightRotation(spotlightPool);
  wireMarqueeSpeed(el);
}

function runWhenIdle(fn, timeoutMs = 1200) {
  if (typeof requestIdleCallback === "function") requestIdleCallback(fn, { timeout: timeoutMs });
  else setTimeout(fn, 0);
}

function renderDashboardOnboard() {
  const el = document.getElementById("dashOnboard");
  if (!el) return;
  // Don't paint the welcome wizard during cold boot: until the library load
  // finishes (dashboardDataReady) and the connections status has been fetched
  // at least once, allGames is transiently empty and connectedProviderCount()
  // is 0, which would flash the onboarding before real data lands.
  if (!state.dashboardDataReady || !authStatusLoaded()) {
    el.innerHTML = "";
    el.hidden = true;
    return;
  }
  const games = state.allGames.length;
  const connections = connectedProviderCount();
  if (games === 0 && connections === 0) {
    el.hidden = false;
    el.innerHTML = `
      <div class="conn-onboard" role="region" aria-label="Get started">
        <p class="conn-onboard-title">Welcome</p>
        <p class="conn-onboard-lead">Connect your first store to fill this dashboard with your library, deals, and stats.</p>
        <button type="button" class="conn-onboard-btn" data-dash-goto-connections>Open Connections</button>
      </div>`;
  } else if (games === 0 && connections > 0) {
    el.hidden = false;
    el.innerHTML = `
      <div class="conn-onboard" role="region" aria-label="Next step">
        <p class="conn-onboard-title">Stores connected</p>
        <p class="conn-onboard-lead">Run a library fetch from Connections or the fetcher log, then open Library to browse your games.</p>
        <div class="conn-onboard-actions">
          <button type="button" class="conn-onboard-btn" data-dash-goto-connections>Connections</button>
          <button type="button" class="conn-onboard-btn conn-onboard-btn--ghost" data-dash-goto-library>Open Library</button>
        </div>
      </div>`;
  } else if (games > 0 && connections === 0) {
    el.hidden = false;
    el.innerHTML = `
      <div class="conn-onboard" role="region" aria-label="Next step">
        <p class="conn-onboard-title">Library loaded</p>
        <p class="conn-onboard-lead">Your games are here - connect more stores to merge libraries and unlock cross-store deals.</p>
        <div class="conn-onboard-actions">
          <button type="button" class="conn-onboard-btn" data-dash-goto-library>Open Library</button>
          <button type="button" class="conn-onboard-btn conn-onboard-btn--ghost" data-dash-goto-connections>Connections</button>
        </div>
      </div>`;
  } else {
    el.innerHTML = "";
    el.hidden = true;
  }
}

export async function renderDashboard(opts = {}) {
  if (state.activeView !== "dashboard") return;
  renderDashboardOnboard();
  if (!state.dashboardDataReady) return;
  try {
    await ensureChartJs();
  } catch (err) {
    console.warn("[dashboard] Chart.js load failed", err);
    return;
  }
  // Re-entrant guard. renderDashboard isn't async, but Chart.js init can call
  // back into user code (legend plugins, tooltip handlers) and any path that
  // hits savePrefs() will trigger personalStore.notify →
  // scheduleDashboardRender during this render. Counter is exposed via
  // window.__baklogDash.stats so debug-overlay surfaces if we ever trip it.
  if (_dashRenderInFlight) {
    _dashRenderStats.skippedReentrant++;
    return;
  }
  const content = document.getElementById("dashboardContent");
  // Boot curtain covers Chart.js / data-not-ready during cold load; no in-card loader.
  if (typeof Chart === "undefined") return;
  content?.classList.remove("hidden");

  const fp = dashboardFingerprint();
  const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
  if (!opts.force && fp === _dashRenderedFingerprint && _dashMegaShellBuilt) {
    if (opts.replay && _dashReplayAllowed) {
      _dashRenderInFlight = true;
      try {
        const games = dashboardLibraryGames();
        const spotlightPool = getSpotlightPool().length ? getSpotlightPool() : pickSpotlightGames(games);
        startSpotlightRotation(spotlightPool);
        const snapReplay = getLibrarySnapshot(games);
        startInsightRotation(buildInsightPool(games, snapReplay));
        replayDashboardChartAnimations({ ribbonOnly: !!opts.replayRibbonOnly });
        _dashRenderStats.replay++;
      } finally {
        _dashRenderInFlight = false;
      }
    } else {
      _dashRenderStats.skippedAutoReplay++;
    }
    return;
  }

  _dashRenderInFlight = true;
  try {
    // Lazy lower charts can appear seconds after sync render; boot-only stagger
    // suppression expired before they painted (log: 120ms gaps + 1.6s to scatter).
    suppressChartStaggerForBoot(1200);
    destroyDashboardCharts();
    Chart.defaults.color = "#94a3b8";
    Chart.defaults.borderColor = "#334155";
    const games = dashboardLibraryGames();
    const snap = getLibrarySnapshot(games);
    renderDashboardFetcherHealth();
    try {
      renderDashboardMega(games, snap);
    } catch (err) {
      console.error("Dashboard mega error:", err);
    }
    renderDashboardItchRecap();
    try {
      renderDashboardCharts(games);
    } catch (err) {
      console.error("Dashboard charts error:", err);
    }
    const fpAfterCharts = dashboardFingerprint();
    runWhenIdle(() => {
      if (state.activeView !== "dashboard" || dashboardFingerprint() !== fpAfterCharts) return;
      renderDashboardWishlistStats();
      try {
        renderDashboardCoopSpotlight(games);
      } catch (err) {
        console.error("Dashboard co-op spotlight error:", err);
      }
      try {
        renderDashboardPicksVersus(games);
      } catch (err) {
        console.error("Dashboard picks versus error:", err);
      }
      try {
        renderDashboardRecentAdditions(games);
      } catch (err) {
        console.error("Dashboard recent additions error:", err);
      }
    });
    _dashRenderedFingerprint = fp;
    _dashRenderStats.full++;
    _dashRenderStats.lastFullAt = now;
  } finally {
    _dashRenderInFlight = false;
    if (_dashboardRenderPending) {
      _dashboardRenderPending = false;
      scheduleDashboardRender();
    }
  }
}

export function cancelScheduledDashboardRender() {
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = null;
  _dashboardRenderPending = false;
}

export function scheduleDashboardRender() {
  if (state.activeView !== "dashboard") return;
  if (_dashRenderInFlight) {
    _dashboardRenderPending = true;
    return;
  }
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = setTimeout(() => {
    _dashboardRenderTimer = null;
    void renderDashboard();
  }, 80);
}

/** Has the dashboard ever been rendered in this session? */
export function dashboardWasRendered() {
  return _dashMegaShellBuilt;
}

// Charts bake CSS accent tokens into Chart.js datasets at render time, so a
// live theme switch needs a forced re-render to repaint them. When the
// dashboard isn't the active view, the theme is folded into the fingerprint so
// the next switch-in repaints without a forced render here.
if (typeof window !== "undefined") {
  window.addEventListener(THEME_CHANGE_EVENT, () => {
    if (state.activeView === "dashboard") {
      renderDashboard({ force: true });
    }
  });
}
