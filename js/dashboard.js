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
import { gameKey, hltbMain, ratingValue, normalizeGame, combinedPlaytime } from './game-core.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo } from './deals.js';
import { ensureChartJs } from './chart-loader.js';
import { animateCount, dashboardLibraryGames } from './dashboard-shared.js';
import { destroyDashboardCharts, replayDashboardChartAnimations, renderDashboardCharts } from './dashboard-charts.js';
import { renderDashboardCoopSpotlight, renderDashboardPicksVersus, renderDashboardWishlistStats, renderDashboardItchRecap } from './dashboard-cards.js';
import { pickSpotlightGames, renderSpotlightHtml, syncSpotlightInMega, primeSpotlightArt, startSpotlightRotation, stopSpotlightRotation, getSpotlightPool, setSpotlightCurrentKey } from './dashboard-spotlight.js';
import { buildInsightPool, buildMarqueeItems, renderMarqueeHtml, startInsightRotation, stopInsightRotation } from './dashboard-insights.js';

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
}

let _dashboardRenderTimer = null;
let _dashCountersInitialized = false;
let _dashMegaShellBuilt = false;
let _dashRenderedFingerprint = "";
const _dashLastCounters = {};
let _marqueeItemsKey = "";

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

function dashboardFingerprint() {
  return JSON.stringify({
    dv: window._dataVersion || 0,
    itch: (state.itchGames || []).length > 0,
    qw: state.prefs.quickWinMaxHours || 0,
    ihn: !!state.sessionPrefs.itchHideNonGames,
  });
}

function computeMegaHeroStats(games) {
  const backlog = games.filter(g => getPersonal(g).status === "backlog");
  const backlogHrs = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
  const playedHrs = games.reduce((s, g) => s + combinedPlaytime(g), 0) / 60;
  const nonSkip = games.filter(g => getPersonal(g).status !== "skip");
  const finished = games.filter(g => getPersonal(g).status === "finished").length;
  const completion = nonSkip.length ? Math.round((finished / nonSkip.length) * 100) : 0;
  const rated = games.filter(g => ratingValue(g) > 0);
  const avgRating = rated.length ? Math.round(rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length) : "—";
  const wlDeals = state.wishlistGames.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
  const stores = new Set(games.map(g => normalizeGame(g).store)).size;
  const years = backlogHrs > 0 ? (backlogHrs / (2 * 365)).toFixed(1) : "0";
  return {
    total: games.length,
    backlogHrs,
    playedHrs,
    completion,
    avgRating,
    wlDeals,
    stores,
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
  if (stats.avgRating !== "—") {
    counters.push({ id: "dashHeroAvg", to: stats.avgRating, format: fmtPct });
  }
  for (const item of counters) {
    const node = document.getElementById(item.id);
    if (!node) continue;
    if (_dashCountersInitialized) node.textContent = item.format(item.to);
    else animateCount(node, 0, item.to, item.format, 900);
    _dashLastCounters[item.id] = item.to;
  }
  _dashCountersInitialized = true;
}

function updateDashboardMegaInPlace(games, stats, spotlight, spotlightPool, marqueeItems) {
  const el = document.getElementById("dashboardMega");
  if (!el) return;
  el.className = spotlight ? 'dash-mega dash-mega--has-spotlight' : 'dash-mega';
  syncSpotlightInMega(el, spotlight);
  const sub = el.querySelector('.dash-hero-sub');
  if (sub) sub.textContent = `games owned across ${stats.stores} stores`;
  const tagline = el.querySelector('.dash-hero-tagline');
  if (tagline) {
    tagline.innerHTML = `
        <span><strong>${stats.completion}%</strong> complete</span>
        <span class="sep">·</span>
        <span><strong>${stats.years}</strong> yrs to clear at 2h/day</span>
        <span class="sep">·</span>
        <span><strong>${escapeHtml(formatNum(stats.wlDeals))}</strong> deals live</span>`;
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
  }
  startInsightRotation(buildInsightPool(games));
  startSpotlightRotation(spotlightPool);
}

function renderDashboardMega(games) {
  const stats = computeMegaHeroStats(games);
  const el = document.getElementById("dashboardMega");
  if (!el) return;

  const spotlightPool = pickSpotlightGames(games);
  const spotlight = spotlightPool[0] || null;
  if (spotlight) setSpotlightCurrentKey(gameKey(spotlight));
  else setSpotlightCurrentKey(null);
  const marqueeItems = buildMarqueeItems(games);

  if (_dashMegaShellBuilt && document.getElementById('dashHeroCount')) {
    updateDashboardMegaInPlace(games, stats, spotlight, spotlightPool, marqueeItems);
    return;
  }

  _dashMegaShellBuilt = true;
  el.className = spotlight ? 'dash-mega dash-mega--has-spotlight' : 'dash-mega';

  el.innerHTML = `
    <div class="dash-mega-hero">
      ${spotlight ? renderSpotlightHtml(spotlight) : ''}
      <div class="dash-hero-eyebrow">Your library</div>
      <div class="dash-hero-number" id="dashHeroCount">${escapeHtml(formatNum(stats.total))}</div>
      <div class="dash-hero-sub">games owned across ${escapeHtml(String(stats.stores))} stores</div>
      <div class="dash-hero-tagline">
        <span><strong>${stats.completion}%</strong> complete</span>
        <span class="sep">·</span>
        <span><strong>${stats.years}</strong> yrs to clear at 2h/day</span>
        <span class="sep">·</span>
        <span><strong>${escapeHtml(formatNum(stats.wlDeals))}</strong> deals live</span>
      </div>
      <div class="dash-hero-pillars">
        <div class="dash-hero-pillar">
          <div class="dash-hero-pillar-value" id="dashHeroPlayed">${escapeHtml(formatNum(Math.round(stats.playedHrs)))}h</div>
          <div class="dash-hero-pillar-label">Played</div>
        </div>
        <div class="dash-hero-pillar">
          <div class="dash-hero-pillar-value" id="dashHeroBacklog">${escapeHtml(formatNum(Math.round(stats.backlogHrs)))}h</div>
          <div class="dash-hero-pillar-label">Backlog</div>
        </div>
        <div class="dash-hero-pillar">
          <div class="dash-hero-pillar-value" id="dashHeroAvg">${stats.avgRating === "—" ? "—" : escapeHtml(String(stats.avgRating)) + "%"}</div>
          <div class="dash-hero-pillar-label">Avg review</div>
        </div>
      </div>
      <span id="dashboardInsight" class="dash-insight" aria-live="polite"></span>
    </div>
    ${renderMarqueeHtml(marqueeItems)}
    <div class="dash-mega-divider" aria-hidden="true"></div>
    <div class="dash-ribbon">
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow">Library by store</div>
        <div class="dash-ribbon-chart"><canvas id="chartStoreDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonStoreHeadline"></div>
      </div>
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow">Status breakdown</div>
        <div class="dash-ribbon-chart"><canvas id="chartStatusDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonStatusHeadline"></div>
      </div>
      <div class="dash-ribbon-tile">
        <div class="dash-ribbon-eyebrow">Review sentiment</div>
        <div class="dash-ribbon-chart"><canvas id="chartReviewDonut"></canvas></div>
        <div class="dash-ribbon-headline" id="ribbonReviewHeadline"></div>
      </div>
    </div>
  `;

  applyMegaHeroCounters(stats);
  primeSpotlightArt(document.getElementById('dashboardSpotlight'));
  startInsightRotation(buildInsightPool(games));
  startSpotlightRotation(spotlightPool);
}

function runWhenIdle(fn, timeoutMs = 1200) {
  if (typeof requestIdleCallback === "function") requestIdleCallback(fn, { timeout: timeoutMs });
  else setTimeout(fn, 0);
}

export async function renderDashboard(opts = {}) {
  if (state.activeView !== "dashboard") return;
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
  if (!state.dashboardDataReady) return;
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
        startInsightRotation(buildInsightPool(games));
        replayDashboardChartAnimations();
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
    destroyDashboardCharts();
    Chart.defaults.color = "#94a3b8";
    Chart.defaults.borderColor = "#334155";
    const games = dashboardLibraryGames();
    renderDashboardFetcherHealth();
    renderDashboardMega(games);
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
    });
    _dashRenderedFingerprint = fp;
    _dashRenderStats.full++;
    _dashRenderStats.lastFullAt = now;
  } finally {
    _dashRenderInFlight = false;
  }
}

export function cancelScheduledDashboardRender() {
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = null;
}

export function scheduleDashboardRender() {
  if (state.activeView !== "dashboard") return;
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = setTimeout(renderDashboard, 80);
}

/** Has the dashboard ever been rendered in this session? */
export function dashboardWasRendered() {
  return _dashMegaShellBuilt;
}
