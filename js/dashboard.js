import { state, STATUS_CHIP_DEFS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { renderDashboardFetcherHealth } from './fetcher-health.js';

let ctx = {};

export function initDashboard(appContext) {
  ctx = appContext;
}

function c(name) {
  const fn = ctx[name];
  if (!fn) throw new Error(`dashboard context missing: ${name}`);
  return fn;
}

const dashboardCharts = {};
let _dashboardRenderTimer = null;
let itchHeroIndex = Math.floor(Math.random() * 10);
let _insightTimer = null;
let _insightFadeTimer = null;
let _insightIndex = 0;
let _spotlightTimer = null;
let _spotlightFadeTimer = null;
let _spotlightIndex = 0;
let _spotlightPool = [];
let _spotlightCurrentKey = null;
const SPOTLIGHT_INTERVAL_MS = 7000;
const SPOTLIGHT_FADE_MS = 300;

let _dashCountersInitialized = false;
let _dashMegaShellBuilt = false;
let _dashRenderedFingerprint = "";

function dashboardFingerprint() {
  return JSON.stringify({
    dv: window._dataVersion || 0,
    itch: (state.itchGames || []).length > 0,
    qw: state.prefs.quickWinMaxHours || 0,
    ihn: !!state.prefs.itchHideNonGames,
  });
}
const _dashLastCounters = {};

function animateCount(el, from, to, format, durationMs = 900) {
  if (!el) return;
  const prefersReduced = typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduced || durationMs <= 0 || from === to) {
    el.textContent = format(to);
    return;
  }
  const start = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  const ease = t => 1 - Math.pow(1 - t, 3);
  function tick(now) {
    const elapsed = (now || performance.now()) - start;
    const t = Math.min(1, elapsed / durationMs);
    const v = from + (to - from) * ease(t);
    el.textContent = format(v);
    if (t < 1) requestAnimationFrame(tick);
    else el.textContent = format(to);
  }
  requestAnimationFrame(tick);
}

const ITCH_CLASS_LABELS = {
  game: "Games",
  tool: "Tools",
  assets: "Assets",
  comic: "Comics",
  book: "Books",
  soundtrack: "Soundtracks",
  physical_game: "Physical games",
  other: "Other",
};
const DASH_STORE_COLORS = {
  steam: "#ea580c", gog: "#6d28d9", psn: "#003791", epic: "#64748b",
  amazon: "#c2410c", xbox: "#107C10", battlenet: "#148EFF", ubisoft: "#FFD200",
  nintendo: "#E60012", itch: "#fa5c5c", other: "#94a3b8", manual: "#64748b",
};
const DASH_STATUS_COLORS = {
  backlog: "#ef4444", next: "#38bdf8", playing: "#facc15", unfinished: "#f97316",
  live: "#ec4899", finished: "#22c55e", skip: "#475569", __none__: "#334155",
};
const DASH_REVIEW_COLORS = {
  "Overwhelmingly Positive": "#22c55e",
  "Very Positive": "#34d399",
  "Mostly Positive": "#86efac",
  "Mixed": "#fbbf24",
  "Mostly Negative": "#f97316",
  "Negative": "#ef4444",
  "Unreviewed": "#475569",
};
const DASH_STORE_LABELS = {
  steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic", amazon: "Amazon",
  xbox: "Xbox", battlenet: "Battle.net", ubisoft: "Ubisoft", nintendo: "Nintendo",
  itch: "itch.io", other: "Other", manual: "Manual",
};

export function stopInsightRotation() {
  if (_insightTimer) clearInterval(_insightTimer);
  if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
  _insightTimer = null;
  _insightFadeTimer = null;
}

export function stopSpotlightRotation() {
  if (_spotlightTimer) clearInterval(_spotlightTimer);
  if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
  _spotlightTimer = null;
  _spotlightFadeTimer = null;
  // Intentionally NOT clearing _spotlightIndex / _spotlightCurrentKey / _spotlightPool —
  // see stopDashboardRotations / renderDashboardMega for the "preserve across revisits" rule.
}

export function stopDashboardRotations() {
  stopInsightRotation();
  stopSpotlightRotation();
}

function poolKeysEqual(a, b) {
  if (!a || !b || a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (c('gameKey')(a[i]) !== c('gameKey')(b[i])) return false;
  }
  return true;
}

const pendingChartRenders = new Map();
let chartLazyObserver = null;

const CHART_STAGGER_MS = 120;
const chartRenderQueue = [];
let chartRenderTimer = null;
let lastChartRenderAt = 0;

function drainChartRenderQueue() {
  chartRenderTimer = null;
  if (!chartRenderQueue.length) return;
  const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
  const sinceLast = now - lastChartRenderAt;
  if (sinceLast < CHART_STAGGER_MS) {
    chartRenderTimer = setTimeout(drainChartRenderQueue, CHART_STAGGER_MS - sinceLast);
    return;
  }
  const job = chartRenderQueue.shift();
  if (job) {
    lastChartRenderAt = now;
    try { job(); } catch (err) { console.error("Lazy chart render failed:", err); }
  }
  if (chartRenderQueue.length) {
    chartRenderTimer = setTimeout(drainChartRenderQueue, CHART_STAGGER_MS);
  }
}

function scheduleStaggeredChartRender(fn) {
  chartRenderQueue.push(fn);
  if (chartRenderTimer == null) {
    chartRenderTimer = setTimeout(drainChartRenderQueue, 0);
  }
}

function ensureChartObserver() {
  if (chartLazyObserver || typeof IntersectionObserver === "undefined") return chartLazyObserver;
  chartLazyObserver = new IntersectionObserver((entries) => {
    const ready = [];
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const id = entry.target.id;
      const fn = pendingChartRenders.get(id);
      if (!fn) continue;
      pendingChartRenders.delete(id);
      chartLazyObserver.unobserve(entry.target);
      ready.push({ fn, top: entry.boundingClientRect.top });
    }
    ready.sort((a, b) => a.top - b.top);
    for (const r of ready) scheduleStaggeredChartRender(r.fn);
  }, { threshold: 0.5, rootMargin: "0px" });
  return chartLazyObserver;
}

export function destroyDashboardCharts() {
  // Rotations (insight + spotlight) are deliberately NOT stopped here so an in-place
  // dashboard re-render doesn't reset the spotlight. Use stopDashboardRotations()
  // from the actual teardown sites (view switch).
  clearScatterList();
  Object.values(dashboardCharts).forEach(ch => { try { ch.destroy(); } catch (_) {} });
  Object.keys(dashboardCharts).forEach(k => delete dashboardCharts[k]);
  if (chartLazyObserver) {
    for (const id of pendingChartRenders.keys()) {
      const el = document.getElementById(id);
      if (el) chartLazyObserver.unobserve(el);
    }
  }
  pendingChartRenders.clear();
  chartRenderQueue.length = 0;
  if (chartRenderTimer != null) {
    clearTimeout(chartRenderTimer);
    chartRenderTimer = null;
  }
  lastChartRenderAt = 0;
}

/** Replay the entrance animation on every live chart without rebuilding it. */
export function replayDashboardChartAnimations() {
  for (const chart of Object.values(dashboardCharts)) {
    try {
      chart.reset();
      chart.update();
    } catch (_) { /* chart was disposed externally */ }
  }
}

export function dashboardLibraryGames() {
  return state.allGames.filter(g => !state.crossStoreHiddenKeys.has(c('gameKey')(g)));
}

function dashChartOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: "#ffffff", boxWidth: 12 } } },
    ...extra,
  };
}

/** Highlight one donut slice + its legend chip; dim the rest on hover. */
function donutLegendHighlight() {
  const dimOther = (chart, hoveredIdx) => {
    const ds = chart.data.datasets[0];
    if (!ds) return;
    if (!ds._origColors) ds._origColors = [...ds.backgroundColor];
    const orig = ds._origColors;
    ds.backgroundColor = orig.map((c, i) => (hoveredIdx == null || i === hoveredIdx ? c : c + "33"));
    chart.update("none");
  };
  const showSliceTooltip = (chart, idx) => {
    if (!chart?.tooltip) return;
    if (idx == null) {
      chart.tooltip.setActiveElements([], { x: 0, y: 0 });
      chart.update("none");
      return;
    }
    const meta = chart.getDatasetMeta(0);
    const arc = meta?.data?.[idx];
    if (!arc) return;
    const { x, y } = arc.tooltipPosition();
    chart.tooltip.setActiveElements([{ datasetIndex: 0, index: idx }], { x, y });
    chart.update("none");
  };
  return {
    position: "right",
    labels: { color: "#ffffff", boxWidth: 12, padding: 8, font: { size: 11 } },
    onHover(_evt, legendItem, legend) {
      if (legendItem && legendItem.index != null) {
        dimOther(legend.chart, legendItem.index);
        showSliceTooltip(legend.chart, legendItem.index);
      }
    },
    onLeave(_evt, _legendItem, legend) {
      dimOther(legend.chart, null);
      showSliceTooltip(legend.chart, null);
    },
  };
}

function setDashboardChart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas || typeof Chart === "undefined") return;
  if (dashboardCharts[id]) {
    dashboardCharts[id].destroy();
    delete dashboardCharts[id];
  }
  const build = () => {
    if (!document.body.contains(canvas)) return;
    dashboardCharts[id] = new Chart(canvas, config);
  };
  const observer = ensureChartObserver();
  if (!observer) {
    build();
    return;
  }
  const rect = canvas.getBoundingClientRect();
  const vh = window.innerHeight || document.documentElement.clientHeight;
  const visible = rect.height > 0
    && rect.top < vh - rect.height * 0.5
    && rect.bottom > rect.height * 0.5;
  if (visible) {
    build();
    return;
  }
  pendingChartRenders.set(id, build);
  observer.observe(canvas);
}

const ERA_BANDS = [
  { start: 1990, end: 1999, label: "'90s", fill: "rgba(251, 191, 36, 0.06)", textColor: "rgba(251, 191, 36, 0.55)" },
  { start: 2000, end: 2009, label: "'00s", fill: "rgba(52, 211, 153, 0.06)", textColor: "rgba(52, 211, 153, 0.55)" },
  { start: 2010, end: 2019, label: "'10s", fill: "rgba(56, 189, 248, 0.07)", textColor: "rgba(56, 189, 248, 0.6)" },
  { start: 2020, end: 2099, label: "'20s", fill: "rgba(168, 85, 247, 0.08)", textColor: "rgba(168, 85, 247, 0.65)" },
];

const DASH_REVIEW_MIN_RATING = {
  "Overwhelmingly Positive": 95,
  "Very Positive": 80,
  "Mostly Positive": 70,
  Mixed: 40,
};

export const HLTB_BUCKETS = [
  { minExclusive: null, maxInclusive: 2, label: "HLTB 0–2h" },
  { minExclusive: 2, maxInclusive: 5, label: "HLTB 2–5h" },
  { minExclusive: 5, maxInclusive: 10, label: "HLTB 5–10h" },
  { minExclusive: 10, maxInclusive: 20, label: "HLTB 10–20h" },
  { minExclusive: 20, maxInclusive: 40, label: "HLTB 20–40h" },
  { minExclusive: 40, maxInclusive: null, label: "HLTB 40h+" },
];

function parseReleaseYear(d) {
  if (!d) return null;
  const s = String(d);
  const m = s.match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
  if (m) return parseInt(m[1], 10);
  const t = Date.parse(s);
  if (!Number.isNaN(t)) return new Date(t).getUTCFullYear();
  return null;
}

function findEraLabelHit(chart, x, y) {
  for (const h of chart._eraHits || []) {
    if (x >= h.labelLeft && x <= h.labelRight && y >= h.labelTop && y <= h.labelBottom) return h;
  }
  return null;
}

function findEraBandAtPixel(chart, x) {
  for (const h of chart._eraHits || []) {
    if (x >= h.bandLeft && x <= h.bandRight) return h;
  }
  return null;
}

function buildDecadeStats(games) {
  const stats = new Map();
  ERA_BANDS.forEach(era => {
    const eraGames = games.filter(g => {
      const y = parseReleaseYear(g.release_date);
      return y != null && y >= era.start && y <= era.end;
    });
    if (!eraGames.length) return;
    const ratings = eraGames.map(g => c("ratingValue")(g)).filter(n => n > 0);
    const hours = eraGames.map(g => c("hltbMain")(g)).filter(n => n != null && n > 0);
    const top = eraGames.slice().sort((a, b) => c("ratingValue")(b) - c("ratingValue")(a))[0];
    stats.set(era.start, {
      era,
      count: eraGames.length,
      avgRating: ratings.length ? Math.round(ratings.reduce((s, n) => s + n, 0) / ratings.length) : null,
      avgHours: hours.length ? (hours.reduce((s, n) => s + n, 0) / hours.length).toFixed(1) : null,
      topName: top?.name || null,
    });
  });
  return stats;
}

function updateEraTooltip(chart, labelHit, decadeStats, evt) {
  const el = document.getElementById("chartReleasesEraTooltip");
  if (!el) return;
  if (!labelHit) {
    el.classList.remove("is-visible");
    el.hidden = true;
    return;
  }
  const stats = decadeStats.get(labelHit.era.start);
  if (!stats) {
    el.classList.remove("is-visible");
    el.hidden = true;
    return;
  }
  const end = labelHit.era.end > 2019 ? "today" : String(labelHit.era.end);
  const rows = [
    ["Games", formatNum(stats.count)],
    stats.avgRating != null ? ["Avg review", `${stats.avgRating}%`] : null,
    stats.avgHours != null ? ["Avg main", `${stats.avgHours}h`] : null,
    stats.topName ? ["Top", stats.topName] : null,
  ].filter(Boolean);
  el.innerHTML = `
    <div class="era-title" style="color:${labelHit.era.textColor}">${escapeHtml(labelHit.era.label)} <span style="font-weight:400;opacity:0.85">(${labelHit.era.start}–${end})</span></div>
    ${rows.map(([k, v]) => `<div class="era-row"><span>${escapeHtml(k)}</span><span>${escapeHtml(v)}</span></div>`).join("")}
  `;
  const wrap = chart.canvas.parentElement;
  const x = evt.x + 12;
  const y = evt.y - 8;
  el.style.left = `${Math.max(4, Math.min(x, wrap.clientWidth - 220))}px`;
  el.style.top = `${Math.max(4, y)}px`;
  el.hidden = false;
  el.classList.add("is-visible");
}

function makeEraBandsPlugin(yearLabels) {
  return {
    id: "eraBands",
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const xs = scales.x;
      if (!xs || yearLabels.length === 0) return;
      const halfBar = yearLabels.length > 1
        ? Math.abs(xs.getPixelForTick(1) - xs.getPixelForTick(0)) / 2
        : (chartArea.right - chartArea.left) / 2;
      ctx.save();
      chart._eraHits = [];
      ERA_BANDS.forEach(era => {
        let firstIdx = -1, lastIdx = -1;
        for (let i = 0; i < yearLabels.length; i++) {
          const y = +yearLabels[i];
          if (y >= era.start && y <= era.end) {
            if (firstIdx === -1) firstIdx = i;
            lastIdx = i;
          }
        }
        if (firstIdx === -1) return;
        const left = Math.max(chartArea.left, xs.getPixelForTick(firstIdx) - halfBar);
        const right = Math.min(chartArea.right, xs.getPixelForTick(lastIdx) + halfBar);
        if (right <= left) return;
        ctx.fillStyle = era.fill;
        ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
        let labelLeft = left;
        let labelRight = right;
        if (right - left > 36) {
          ctx.fillStyle = era.textColor;
          ctx.font = "600 10px system-ui, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          const cx = (left + right) / 2;
          const w = ctx.measureText(era.label).width;
          labelLeft = cx - w / 2 - 4;
          labelRight = cx + w / 2 + 4;
          ctx.fillText(era.label, cx, chartArea.top + 4);
        }
        chart._eraHits.push({
          era,
          bandLeft: left,
          bandRight: right,
          labelLeft,
          labelRight,
          labelTop: chartArea.top + 2,
          labelBottom: chartArea.top + 16,
        });
      });
      ctx.restore();
    },
  };
}

function makeBarEndLabelsPlugin(getLabelForBarIndex) {
  return {
    id: "barEndLabels",
    afterDatasetsDraw(chart) {
      const { ctx, data } = chart;
      const lastIdx = data.datasets.length - 1;
      const meta = chart.getDatasetMeta(lastIdx);
      if (!meta || !meta.data) return;
      ctx.save();
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "600 11px system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      meta.data.forEach((bar, i) => {
        const text = getLabelForBarIndex(i);
        if (text == null || text === "") return;
        ctx.fillText(String(text), bar.x + 6, bar.y);
      });
      ctx.restore();
    },
  };
}

/** Reset every active library filter except cross-store dedup before drilling. */
function dashResetLibraryFiltersExceptDedup() {
  const search = document.getElementById("search");
  if (search) search.value = "";
  const sf = document.getElementById("statusFilter");
  if (sf) sf.value = "";
  const unplayed = document.getElementById("unplayedOnly");
  if (unplayed) unplayed.checked = false;
  const ea = document.getElementById("earlyAccessOnly");
  if (ea) ea.checked = false;
  c('setCoopFilterMode')('off');
  const minR = document.getElementById("minRating");
  if (minR) minR.value = "0";
  const minRVal = document.getElementById("minRatingVal");
  if (minRVal) minRVal.textContent = "0";
  const maxH = document.getElementById("maxHours");
  if (maxH) maxH.value = "200";
  const maxHVal = document.getElementById("maxHoursVal");
  if (maxHVal) maxHVal.textContent = "200+";
  state.prefs.storeFilter = "";
  state.prefs.wishlistStoreFilter = "";
  state.prefs.releaseYearFilter = "";
  state.prefs.hltbBucket = null;
  state.prefs.genreFilters = [];
  state.prefs.tagFilters = [];
  state.prefs.tagFilterMode = "OR";
  state.cleanupModeActive = false;
  const tagModeEl = document.getElementById("tagFilterMode");
  if (tagModeEl) tagModeEl.value = "OR";
}

function dashDrillStore(store) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillStatus(status) {
  dashResetLibraryFiltersExceptDedup();
  const sf = document.getElementById("statusFilter");
  if (sf) sf.value = status || "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillStoreStatus(store, status) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.storeFilter = store || "";
  const sf = document.getElementById("statusFilter");
  if (sf) sf.value = status || "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashFinishDrillToLibrary() {
  c("savePrefs")();
  c("switchView")("library");
  c("renderStoreChips")();
  c("renderGenreChips")();
  c("refreshFilterUI")();
  scrollLibraryToPicks();
}

function scrollLibraryToPicks() {
  const land = () => {
    const picks = document.getElementById("picksSection");
    if (!picks) {
      window.scrollTo(0, 0);
      return;
    }
    const rect = picks.getBoundingClientRect();
    const targetY = Math.max(0, rect.top + window.scrollY - 8);
    try { window.scrollTo({ top: targetY, behavior: "auto" }); }
    catch (_) { window.scrollTo(0, targetY); }
  };
  // Run after the library render commits so layout is final.
  requestAnimationFrame(() => requestAnimationFrame(land));
}

function dashSetReleaseYear(value) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.releaseYearFilter = value || "";
  dashFinishDrillToLibrary();
}

function dashDrillHltbBucket(idx) {
  if (idx == null || !HLTB_BUCKETS[idx]) return;
  dashResetLibraryFiltersExceptDedup();
  const maxH = document.getElementById("maxHours");
  const maxHVal = document.getElementById("maxHoursVal");
  if (maxH) maxH.value = "200";
  if (maxHVal) maxHVal.textContent = "200+";
  state.prefs.hltbBucket = idx;
  dashFinishDrillToLibrary();
}

function dashDrillMinRating(minRating) {
  dashResetLibraryFiltersExceptDedup();
  const minR = document.getElementById("minRating");
  const minRVal = document.getElementById("minRatingVal");
  if (minR) minR.value = String(minRating);
  if (minRVal) minRVal.textContent = String(minRating);
  dashFinishDrillToLibrary();
}

function dashDrillGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  c('savePrefs')();
  c('switchView')("library");
  c('renderGenreChips')();
  c('refreshFilterUI')();
}

function dashDrillItchGenre(genre) {
  dashResetLibraryFiltersExceptDedup();
  state.prefs.genreFilters = [genre];
  c('savePrefs')();
  c('switchView')("itch");
  c('renderGenreChips')();
  c('refreshFilterUI')();
}

function itchBreakdownRows(entries, fillClass, action) {
  const max = Math.max(...entries.map(([, n]) => n), 1);
  return entries.map(([value, count, label]) => {
    const pct = Math.round((count / max) * 100);
    const display = label || value;
    const tag = action ? "button" : "div";
    const attrs = action
      ? ` type="button" data-action="${escapeAttr(action)}" data-value="${escapeAttr(value)}"`
      : "";
    return `<${tag} class="itch-breakdown-row${action ? "" : " itch-breakdown-row-static"}"${attrs} title="${escapeAttr(display)}: ${formatNum(count)}">
      <span class="itch-breakdown-name">${escapeHtml(display)}</span>
      <span class="itch-breakdown-bar" aria-hidden="true"><span class="itch-breakdown-fill ${fillClass}" style="width:${pct}%"></span></span>
      <span class="itch-breakdown-count">${formatNum(count)}</span>
    </${tag}>`;
  }).join("");
}

function bindItchRecapClick() {
  const el = document.getElementById("dashItchRecap");
  if (!el || el.dataset.itchBound) return;
  el.dataset.itchBound = "1";
  el.addEventListener("click", e => {
    const shuffle = e.target.closest('[data-action="itch-hero-shuffle"]');
    if (shuffle) {
      e.preventDefault();
      e.stopPropagation();
      itchHeroIndex += 1;
      renderDashboardItchRecap();
      return;
    }
    const genreRow = e.target.closest('[data-action="itch-drill-genre"]');
    if (genreRow?.dataset.value) {
      e.preventDefault();
      e.stopPropagation();
      dashDrillItchGenre(genreRow.dataset.value);
    }
  });
}

export function dashDrillCoop({ online = false, local = false, any = false } = {}) {
  let mode = "off";
  if (any) mode = "any";
  else if (online && local) mode = "both";
  else if (online) mode = "online";
  else if (local) mode = "local";
  c('setCoopFilterMode')(mode);
  document.getElementById("statusFilter").value = "";
  state.prefs.storeFilter = "";
  c('savePrefs')();
  c('invalidateTableCache')();
  if (state.activeView !== "library") c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
  c('renderTable')();
}

function renderDashboardCoopSpotlight(games) {
  const el = document.getElementById("dashboardCoopSpotlight");
  if (!el) return;
  const coopGames = games.filter(g => g.coop_online || g.coop_local);
  const onlineGames = games.filter(g => g.coop_online);
  const localGames = games.filter(g => g.coop_local);
  const bothGames = games.filter(g => g.coop_online && g.coop_local);

  if (coopGames.length === 0) {
    el.innerHTML = `
      <div class="coop-spotlight-header">
        <div class="coop-spotlight-title">Co-op spotlight</div>
      </div>
      <div class="coop-empty">
        No co-op games detected yet. Co-op flags come from Steam store categories — run <code>fetch_games.py</code> to refresh, or wait until you own a Steam title tagged <em>Online Co-op</em> or <em>Shared/Split Screen Co-op</em>.
      </div>`;
    return;
  }

  const sideHtml = (list, { sideClass, title, drillArgs }) => {
    const backlog = list.filter(g => c('getPersonal')(g).status === "backlog").length;
    const finished = list.filter(g => c('getPersonal')(g).status === "finished").length;
    const hltbValues = list.map(g => c('hltbMain')(g)).filter(h => h != null && h > 0);
    const avgHltb = hltbValues.length
      ? Math.round(hltbValues.reduce((s, h) => s + h, 0) / hltbValues.length)
      : null;
    const failedCoop = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
    const picks = list
      .filter(g => c('getPersonal')(g).status !== "finished" && (g.playtime_minutes || 0) === 0)
      .filter(g => c('ratingValue')(g) > 0 && c('hasEnoughReviews')(g))
      .filter(g => !!(g.library_image || g.header_image) && !failedCoop.has(c('gameKey')(g)))
      .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
      .slice(0, 3);
    const picksHtml = picks.length
      ? picks.map(g => {
          const cover = g.library_image || c('coverFallbackFor')(g);
          const key = c('gameKey')(g);
          return `<button type="button" class="coop-pick-row" data-action="coop-pick-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library">
            <img class="coop-pick-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
            <span class="coop-pick-name">${escapeHtml(g.name)}</span>
            <span class="coop-pick-rating">${c('ratingValue')(g)}%</span>
          </button>`;
        }).join("")
      : '<div class="coop-picks-empty">All started or finished — nothing unplayed.</div>';
    const drillJson = escapeAttr(JSON.stringify(drillArgs));
    return `
      <div class="coop-side ${sideClass}" role="button" tabindex="0" data-action="coop-drill" data-drill="${drillJson}" title="Filter the library by ${escapeAttr(title)}">
        <div class="coop-side-header">
          <div class="coop-side-title-row">
            <span class="coop-side-title">${escapeHtml(title)}</span>
          </div>
          <span class="coop-side-count">${list.length}</span>
        </div>
        <div class="coop-side-stats">
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Backlog</div>
            <div class="coop-side-stat-value ${backlog ? "" : "coop-side-stat-muted"}">${backlog}</div>
          </div>
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Finished</div>
            <div class="coop-side-stat-value ${finished ? "" : "coop-side-stat-muted"}">${finished}</div>
          </div>
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Avg HLTB</div>
            <div class="coop-side-stat-value ${avgHltb != null ? "" : "coop-side-stat-muted"}">${avgHltb != null ? avgHltb + "h" : "—"}</div>
          </div>
        </div>
        <div>
          <div class="coop-side-picks-label">Top unplayed picks</div>
          <div class="coop-side-picks-list">${picksHtml}</div>
        </div>
      </div>`;
  };

  const anyDrill = escapeAttr(JSON.stringify({ any: true }));
  const bothDrill = escapeAttr(JSON.stringify({ online: true, local: true }));
  const connector = `
    <div class="coop-connector">
      <button type="button" class="coop-connector-stat" data-action="coop-drill" data-drill="${anyDrill}" title="Filter the library by any game with an online or couch co-op flag">
        <div class="coop-connector-label">Total co-op</div>
        <div class="coop-connector-value">${coopGames.length}</div>
        <div class="coop-connector-sub">of ${games.length} games</div>
      </button>
      <div class="coop-connector-divider" aria-hidden="true"></div>
      <button type="button" class="coop-connector-stat" data-action="coop-drill" data-drill="${bothDrill}" title="Filter the library by games that support both online and couch co-op">
        <div class="coop-connector-label">Both flavors</div>
        <div class="coop-connector-value">${bothGames.length}</div>
        <div class="coop-connector-sub">online + couch</div>
      </button>
    </div>`;

  el.innerHTML = `
    <div class="coop-spotlight-header">
      <div class="coop-spotlight-title">Co-op spotlight</div>
      <div class="coop-spotlight-sub">Steam co-op signal · click a side to filter the library</div>
    </div>
    <div class="coop-versus">
      ${sideHtml(onlineGames, { sideClass: "coop-side-online", title: "Online co-op", drillArgs: { online: true, local: false } })}
      ${connector}
      ${sideHtml(localGames, { sideClass: "coop-side-local", title: "Couch co-op", drillArgs: { online: false, local: true } })}
    </div>
  `;
}
function buildInsightPool(games) {
  const insights = [];
  const backlog = games.filter(g => c('getPersonal')(g).status === 'backlog');

  const genreHrs = {};
  backlog.forEach(g => {
    c('gameGenresCanonical')(g).forEach(gen => {
      genreHrs[gen] = (genreHrs[gen] || 0) + (c('hltbMain')(g) || 0);
    });
  });
  const topGenre = Object.entries(genreHrs).sort((a, b) => b[1] - a[1])[0];
  if (topGenre && topGenre[1] > 0) {
    insights.push(`Biggest backlog: <strong>${escapeHtml(topGenre[0])}</strong> · ${escapeHtml(formatNum(Math.round(topGenre[1])))}h`);
  }

  const byPlay = [...games].filter(g => (g.playtime_minutes || 0) > 0).sort((a, b) => (b.playtime_minutes || 0) - (a.playtime_minutes || 0));
  if (byPlay[0]) {
    const hrs = Math.round((byPlay[0].playtime_minutes || 0) / 60);
    insights.push(`Most played: <strong>${escapeHtml(byPlay[0].name)}</strong> · ${escapeHtml(formatNum(hrs))}h`);
  }

  const hltbVals = backlog.map(g => c('hltbMain')(g)).filter(h => h != null && h > 0);
  if (hltbVals.length) {
    const avg = Math.round(hltbVals.reduce((s, h) => s + h, 0) / hltbVals.length);
    insights.push(`Avg HLTB main: <strong>${escapeHtml(formatNum(avg))}h</strong>`);
  }

  const unplayed = backlog.filter(g => !(g.playtime_minutes || 0)).sort((a, b) => (c('hltbMain')(b) || 0) - (c('hltbMain')(a) || 0));
  if (unplayed[0]) {
    const h = c('hltbMain')(unplayed[0]);
    insights.push(`Longest unplayed: <strong>${escapeHtml(unplayed[0].name)}</strong> · ${h != null ? escapeHtml(formatNum(Math.round(h))) + 'h' : '?'}`);
  }

  const deals = state.wishlistGames.filter(g => {
    const d = c('getDealInfo')(g);
    return d && (d.cut || 0) > 0;
  });
  if (deals.length) {
    const top = [...deals].sort((a, b) => c('dealScore')(b) - c('dealScore')(a))[0];
    const cut = c('getDealInfo')(top)?.cut || 0;
    insights.push(`Top deal: <strong>${escapeHtml(top.name)}</strong> · -${cut}%`);
  }

  const rated = games.filter(g => c('ratingValue')(g) > 0);
  if (rated.length) {
    const avg = Math.round(rated.reduce((s, g) => s + c('ratingValue')(g), 0) / rated.length);
    insights.push(`Average review: <strong>${avg}%</strong>`);
  }

  const withDate = games
    .map(g => ({ g, d: g.added_at || '' }))
    .filter(x => x.d)
    .sort((a, b) => b.d.localeCompare(a.d));
  if (withDate[0]) {
    insights.push(`Newest add: <strong>${escapeHtml(withDate[0].g.name)}</strong>`);
  }

  const playedHrs = games.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  if (games.length) {
    const ratio = (playedHrs / games.length).toFixed(1);
    insights.push(`Hours per game: <strong>${ratio}h</strong>`);
  }

  return insights;
}

function formatDollarMarquee(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

function gameSpotlightReason(g) {
  const rating = c('ratingValue')(g);
  const hltb = c('hltbMain')(g);
  const personal = c('getPersonal')(g);
  const enough = c('hasEnoughReviews')(g);
  const playtime = g.playtime_minutes || 0;
  const status = personal.status || 'backlog';
  if (['finished', 'skip', 'live'].includes(status)) return null;
  if (!['backlog', 'next', 'playing', 'unfinished'].includes(status)) return null;

  if ((status === 'playing' || status === 'unfinished') && playtime >= 30 && rating >= 70) {
    return { eyebrow: 'Return to', score: rating + 6 };
  }
  if (status === 'next' && rating >= 70) {
    return { eyebrow: 'Up next', score: rating + 10 };
  }
  if (rating >= 88 && enough && hltb && hltb <= 8) {
    return { eyebrow: 'Top-rated quick pick', score: rating + 8 };
  }
  if (rating >= 90 && enough) {
    return { eyebrow: 'Critically acclaimed', score: rating + 4 };
  }
  if (rating >= 78 && hltb && hltb <= 5) {
    return { eyebrow: 'Quick win', score: rating + 2 };
  }
  if (rating >= 82 && enough) {
    return { eyebrow: 'Highly rated', score: rating };
  }
  if (rating >= 80 && !enough) {
    return { eyebrow: 'Hidden gem', score: rating - 3 };
  }
  if (rating >= 75 && enough) {
    return { eyebrow: 'Solid pick', score: rating - 5 };
  }
  if (hltb && hltb <= 4 && rating > 0) {
    return { eyebrow: 'Fast finish', score: rating - 6 };
  }
  if (rating >= 70) {
    return { eyebrow: 'Worth a look', score: rating - 10 };
  }
  return null;
}

function pickSpotlightGames(games) {
  const failed = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const hasArt = g => !!(g.header_image || g.library_image) && !failed.has(c('gameKey')(g));
  const eligible = games.filter(hasArt);
  const target = Math.max(60, Math.round(eligible.length * 0.35));

  const tagged = [];
  for (const g of eligible) {
    const reason = gameSpotlightReason(g);
    if (reason) tagged.push({ g, reason });
  }
  tagged.sort((a, b) => b.reason.score - a.reason.score);
  const top = tagged.slice(0, target);

  for (let i = top.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [top[i], top[j]] = [top[j], top[i]];
  }
  const pool = top.map(({ g, reason }) => Object.assign({}, g, { _spotlightReason: reason }));

  // Preserve the previously-displayed game across dashboard revisits: if it's still
  // eligible, rotate it to index 0 so re-paint doesn't visibly switch games.
  if (_spotlightCurrentKey) {
    const idx = pool.findIndex(g => c('gameKey')(g) === _spotlightCurrentKey);
    if (idx > 0) {
      const [head] = pool.splice(idx, 1);
      pool.unshift(head);
    }
  }
  return pool;
}

const SPOTLIGHT_STATUS_LABEL = {
  backlog: 'in backlog',
  next: 'next up',
  playing: 'in progress',
  unfinished: 'unfinished',
};

function spotlightInnerHtml(g) {
  const art = g.header_image || g.library_image || c('coverFallbackFor')(g);
  const rating = c('ratingValue')(g);
  const hltb = c('hltbMain')(g);
  const hltbStr = hltb != null ? `${Math.round(hltb)}h` : '?';
  const status = (c('getPersonal')(g).status) || 'backlog';
  const statusLabel = SPOTLIGHT_STATUS_LABEL[status] || 'in your library';
  const eyebrow = g._spotlightReason?.eyebrow || 'Spotlight';
  return `
    <img class="dash-spotlight-art" src="${escapeAttr(art)}" alt="" loading="lazy" onload="this.classList.add('is-loaded')" onerror="this.classList.add('is-loaded');window.coverFallback(this)" />
    <div class="dash-spotlight-gradient" aria-hidden="true"></div>
    <div class="dash-spotlight-body">
      <span class="dash-spotlight-eyebrow">${escapeHtml(eyebrow)}</span>
      <span class="dash-spotlight-title">${escapeHtml(g.name)}</span>
      <span class="dash-spotlight-meta"><strong>${rating}%</strong> review · <strong>${escapeHtml(hltbStr)}</strong> main · ${escapeHtml(statusLabel)}</span>
    </div>`;
}

function renderSpotlightHtml(g) {
  const key = c('gameKey')(g);
  return `
    <button type="button" class="dash-spotlight" id="dashboardSpotlight" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in library">
      ${spotlightInnerHtml(g)}
    </button>`;
}

function primeSpotlightArt(btn) {
  const img = btn?.querySelector('.dash-spotlight-art');
  if (!img) return;
  if (img.complete && img.naturalWidth > 0) img.classList.add('is-loaded');
}

function wireSpotlightHover(el) {
  if (!el || el.dataset.hoverWired) return;
  el.dataset.hoverWired = '1';
  let paused = false;
  el.addEventListener('mouseenter', () => { paused = true; });
  el.addEventListener('mouseleave', () => { paused = false; });
  el._spotlightPaused = () => paused;
}

function startSpotlightRotation(pool) {
  if (!pool || pool.length <= 1) {
    stopSpotlightRotation();
    _spotlightPool = pool || [];
    return;
  }
  const el = document.getElementById('dashboardSpotlight');
  if (!el) return;
  const domMatches = !!pool[0] && el.dataset.key === c('gameKey')(pool[0]);
  _spotlightPool = pool;
  // Same slide still mounted: resume rotation only (no innerHTML swap / fade-in).
  if (domMatches) {
    if (_spotlightTimer) return;
    wireSpotlightHover(el);
    _spotlightTimer = setInterval(() => {
      const paused = el._spotlightPaused?.() ?? false;
      if (paused) return;
      if (!document.getElementById('dashboardSpotlight')) {
        stopSpotlightRotation();
        return;
      }
      _spotlightIndex = (_spotlightIndex + 1) % _spotlightPool.length;
      const next = _spotlightPool[_spotlightIndex];
      el.classList.add('is-fading');
      if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
      _spotlightFadeTimer = setTimeout(() => {
        el.innerHTML = spotlightInnerHtml(next);
        el.dataset.key = c('gameKey')(next);
        el.title = `Jump to ${next.name} in library`;
        el.classList.remove('is-fading');
        primeSpotlightArt(el);
        _spotlightCurrentKey = c('gameKey')(next);
      }, SPOTLIGHT_FADE_MS);
    }, SPOTLIGHT_INTERVAL_MS);
    return;
  }
  stopSpotlightRotation();
  // _spotlightIndex is intentionally NOT reset — pickSpotlightGames has already
  // arranged the pool so the previously-displayed game is at index 0; on first
  // load _spotlightIndex is already 0 from module init.
  _spotlightIndex = 0;
  wireSpotlightHover(el);
  _spotlightTimer = setInterval(() => {
    if (el._spotlightPaused?.()) return;
    if (!document.getElementById('dashboardSpotlight')) {
      stopSpotlightRotation();
      return;
    }
    _spotlightIndex = (_spotlightIndex + 1) % _spotlightPool.length;
    const next = _spotlightPool[_spotlightIndex];
    el.classList.add('is-fading');
    if (_spotlightFadeTimer) clearTimeout(_spotlightFadeTimer);
    _spotlightFadeTimer = setTimeout(() => {
      el.innerHTML = spotlightInnerHtml(next);
      el.dataset.key = c('gameKey')(next);
      el.title = `Jump to ${next.name} in library`;
      el.classList.remove('is-fading');
      primeSpotlightArt(el);
      _spotlightCurrentKey = c('gameKey')(next);
    }, SPOTLIGHT_FADE_MS);
  }, SPOTLIGHT_INTERVAL_MS);
}

function buildMarqueeItems(games) {
  const maxHrs = state.prefs.quickWinMaxHours || 15;
  const status = (g) => c('getPersonal')(g).status || 'backlog';
  const playMin = (g) => g.playtime_minutes || 0;
  const rating = (g) => c('ratingValue')(g);
  const hltb = (g) => c('hltbMain')(g);

  const total = games.length;
  const backlog = games.filter(g => status(g) === 'backlog');
  const playing = games.filter(g => status(g) === 'playing');
  const unfinished = games.filter(g => status(g) === 'unfinished');
  const next = games.filter(g => status(g) === 'next');
  const finished = games.filter(g => status(g) === 'finished');
  const touched = games.filter(g => playMin(g) > 0);
  const playedHrs = games.reduce((s, g) => s + playMin(g), 0) / 60;
  const backlogHrs = backlog.reduce((s, g) => s + (hltb(g) || 0), 0);
  const ratedGames = games.filter(g => rating(g) > 0);

  const wl = state.wishlistGames || [];
  const onSale = wl.filter(g => {
    const d = c('getDealInfo')(g);
    return d && (d.cut || 0) > 0;
  });
  const wlSources = new Set(
    wl.map(g => g.wishlist_store || g.store_target || (g.manual ? 'manual' : 'steam')).filter(Boolean)
  ).size;
  const itchGameCount = (state.itchGames || []).filter(c('itchIsGame')).length;

  const items = [];
  const push = (glyph, iconCls, value, label) => {
    items.push({ glyph, iconCls, valueHtml: escapeHtml(String(value)), label });
  };

  if (total > 0) push('>', '', formatNum(total), 'games owned');
  const stores = new Set(games.map(g => c('normalizeGame')(g).store)).size;
  if (stores > 0) push('>', '', String(stores), 'stores');
  if (wlSources > 0) push('*', 'is-violet', String(wlSources), 'wishlists tracked');
  if (itchGameCount > 0) push('>', '', formatNum(itchGameCount), 'itch games');
  if (backlog.length) push('~', 'is-amber', formatNum(backlog.length), 'in backlog');
  if (finished.length) push('+', 'is-emerald', formatNum(finished.length), 'completed');
  if (touched.length) push('>', '', formatNum(touched.length), 'games touched');
  if (playing.length) push('*', 'is-violet', formatNum(playing.length), 'in progress');
  if (next.length) push('*', 'is-amber', formatNum(next.length), 'queued next');
  if (unfinished.length) push('^', 'is-rose', formatNum(unfinished.length), 'left unfinished');

  if (total > 0) {
    const completionPct = Math.round((finished.length / total) * 100);
    push('+', 'is-emerald', `${completionPct}%`, 'library completion');
    const touchedPct = Math.round((touched.length / total) * 100);
    push('~', 'is-amber', `${touchedPct}%`, 'ever touched');
  }

  if (playedHrs > 0) push('~', 'is-amber', `${formatNum(Math.round(playedHrs))}h`, 'all-time played');
  if (touched.length) {
    const avgSession = Math.round(playedHrs / touched.length);
    if (avgSession > 0) push('~', 'is-amber', `${avgSession}h`, 'avg time per played game');
  }
  const mostPlayed = [...games].sort((a, b) => playMin(b) - playMin(a))[0];
  if (mostPlayed && playMin(mostPlayed) > 0) {
    push('^', 'is-rose', `${mostPlayed.name} · ${formatNum(Math.round(playMin(mostPlayed) / 60))}h`, 'most-played');
  }

  const hltbVals = backlog.map(hltb).filter(h => h != null && h > 0);
  if (hltbVals.length) {
    const avg = Math.round(hltbVals.reduce((s, h) => s + h, 0) / hltbVals.length);
    push('~', 'is-amber', `${formatNum(avg)}h`, 'avg backlog main');
    const med = [...hltbVals].sort((a, b) => a - b)[Math.floor(hltbVals.length / 2)];
    push('~', 'is-amber', `${formatNum(Math.round(med))}h`, 'median backlog main');
  }

  const longest = [...backlog].sort((a, b) => (hltb(b) || 0) - (hltb(a) || 0))[0];
  if (longest && hltb(longest)) {
    push('^', 'is-rose', `${longest.name} · ${formatNum(Math.round(hltb(longest)))}h`, 'longest backlog');
  }
  const shortest = [...backlog].filter(g => hltb(g) > 0).sort((a, b) => hltb(a) - hltb(b))[0];
  if (shortest) {
    push('>', '', `${shortest.name} · ${(hltb(shortest)).toFixed(1)}h`, 'shortest backlog');
  }

  const underTwo = backlog.filter(g => hltb(g) && hltb(g) <= 2).length;
  if (underTwo) push('>', '', formatNum(underTwo), 'under 2h to beat');
  const underFive = backlog.filter(g => hltb(g) && hltb(g) <= 5).length;
  if (underFive) push('>', '', formatNum(underFive), 'under 5h to beat');
  const marathons = backlog.filter(g => hltb(g) && hltb(g) >= 50).length;
  if (marathons) push('^', 'is-rose', formatNum(marathons), '50h+ marathons');
  const epics = backlog.filter(g => hltb(g) && hltb(g) >= 100).length;
  if (epics) push('^', 'is-rose', formatNum(epics), '100h+ epics');

  if (backlogHrs > 0) {
    const years2h = (backlogHrs / (2 * 365)).toFixed(1);
    push('~', 'is-amber', `${years2h} yrs`, 'to clear at 2h/day');
    const years4h = (backlogHrs / (4 * 365)).toFixed(1);
    push('~', 'is-amber', `${years4h} yrs`, 'to clear at 4h/day');
    const days8h = Math.round(backlogHrs / 8);
    push('~', 'is-amber', `${formatNum(days8h)} d`, 'non-stop at 8h/day');
  }

  if (ratedGames.length) {
    const avgRating = Math.round(ratedGames.reduce((s, g) => s + rating(g), 0) / ratedGames.length);
    push('+', 'is-emerald', `${avgRating}%`, 'avg review score');
    const backlogRated = backlog.filter(g => rating(g) > 0);
    if (backlogRated.length) {
      const avgBacklogRating = Math.round(backlogRated.reduce((s, g) => s + rating(g), 0) / backlogRated.length);
      push('+', 'is-emerald', `${avgBacklogRating}%`, 'avg backlog review');
    }
    const ratedPct = Math.round((ratedGames.length / total) * 100);
    push('~', 'is-amber', `${ratedPct}%`, 'of library rated');
  }

  const top90 = backlog.filter(g => rating(g) >= 90 && c('hasEnoughReviews')(g)).length;
  if (top90) push('*', 'is-amber', formatNum(top90), '90%+ unplayed');
  const top80 = backlog.filter(g => rating(g) >= 80 && c('hasEnoughReviews')(g)).length;
  if (top80) push('*', 'is-amber', formatNum(top80), '80%+ unplayed');
  const quickWins = backlog.filter(g => rating(g) >= 75 && (hltb(g) || 999) <= maxHrs).length;
  if (quickWins) push('>', '', formatNum(quickWins), 'quick wins ready');
  const hiddenGems = backlog.filter(g => rating(g) >= 90 && c('hasEnoughReviews')(g) && !playMin(g)).length;
  if (hiddenGems) push('*', 'is-amber', formatNum(hiddenGems), 'hidden gems');

  const topRated = [...backlog].filter(g => rating(g) > 0 && c('hasEnoughReviews')(g))
    .sort((a, b) => rating(b) - rating(a))[0];
  if (topRated) push('*', 'is-amber', `${topRated.name} · ${rating(topRated)}%`, 'top-rated unplayed');

  const stealsCount = wl.filter(c('isStealDeal')).length;
  if (stealsCount) push('+', 'is-emerald', formatNum(stealsCount), 'steal-tier deals');
  if (onSale.length) push('+', 'is-emerald', formatNum(onSale.length), 'on sale now');
  if (onSale.length) {
    const top = [...onSale].sort((a, b) => c('dealScore')(b) - c('dealScore')(a))[0];
    const cut = c('getDealInfo')(top)?.cut || 0;
    push('+', 'is-emerald', `${top.name} -${cut}%`, 'top deal');
    const cuts = onSale.map(g => c('getDealInfo')(g)?.cut || 0).filter(x => x > 0);
    if (cuts.length) {
      const avgCut = Math.round(cuts.reduce((s, c2) => s + c2, 0) / cuts.length);
      push('+', 'is-emerald', `${avgCut}%`, 'avg discount');
      const steepest = Math.max(...cuts);
      push('+', 'is-emerald', `-${steepest}%`, 'steepest cut');
    }
  }

  let wishlistValue = 0;
  let wishlistSaleNow = 0;
  for (const g of wl) {
    const d = c('getDealInfo')(g);
    if (d?.regular != null) wishlistValue += d.regular;
    if (d?.price != null) wishlistSaleNow += d.price;
  }
  if (wishlistValue > 0) push('#', 'is-violet', formatDollarMarquee(wishlistValue), 'wishlist value');
  if (wishlistSaleNow > 0 && wishlistSaleNow < wishlistValue) {
    push('#', 'is-violet', formatDollarMarquee(wishlistValue - wishlistSaleNow), 'savings if bought now');
  }

  let libraryMsrp = 0;
  for (const g of games) {
    const d = c('getDealInfo')(g);
    if (d?.regular != null) libraryMsrp += d.regular;
  }
  if (libraryMsrp > 0) push('#', 'is-violet', formatDollarMarquee(libraryMsrp), 'library at MSRP');

  const parseReleaseYear = (d) => {
    if (!d) return null;
    const s = String(d);
    const m = s.match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
    if (m) return parseInt(m[1], 10);
    const t = Date.parse(s);
    if (!isNaN(t)) return new Date(t).getUTCFullYear();
    return null;
  };
  const withReleaseYear = games
    .map(g => {
      const y = parseReleaseYear(g.release_date);
      return y != null ? { g, y } : null;
    })
    .filter(Boolean);
  if (withReleaseYear.length) {
    const oldest = withReleaseYear.reduce((a, b) => a.y < b.y ? a : b);
    push('^', 'is-rose', `${oldest.g.name} · ${oldest.y}`, 'oldest in library');
    const newest = withReleaseYear.reduce((a, b) => a.y > b.y ? a : b);
    push('*', 'is-violet', `${newest.g.name} · ${newest.y}`, 'newest release owned');
    const decadeCounts = {};
    for (const { y } of withReleaseYear) {
      const dec = Math.floor(y / 10) * 10;
      decadeCounts[dec] = (decadeCounts[dec] || 0) + 1;
    }
    const topDec = Object.entries(decadeCounts).sort((a, b) => b[1] - a[1])[0];
    if (topDec) push('>', '', `${topDec[0]}s · ${formatNum(topDec[1])}`, 'top decade');
    const oldUnplayed = backlog
      .map(g => ({ g, y: parseReleaseYear(g.release_date) }))
      .filter(x => x.y != null)
      .reduce((a, b) => (!a || a.y > b.y) ? b : a, null);
    if (oldUnplayed) push('^', 'is-rose', `${oldUnplayed.g.name} · ${oldUnplayed.y}`, 'oldest unplayed');
  }

  const withAddDate = games
    .map(g => ({ g, d: g.added_at || '' }))
    .filter(x => x.d)
    .sort((a, b) => b.d.localeCompare(a.d));
  if (withAddDate[0]) push('*', 'is-violet', withAddDate[0].g.name, 'newest add');

  const thisYear = new Date().getFullYear();
  const addedThisYear = games.filter(g => (g.added_at || '').startsWith(String(thisYear))).length;
  if (addedThisYear) push('+', 'is-emerald', formatNum(addedThisYear), `added in ${thisYear}`);

  const devCounts = {};
  const pubCounts = {};
  for (const g of games) {
    const ng = c('normalizeGame')(g);
    (ng.developers || g.developers || []).forEach(d => { if (d) devCounts[d] = (devCounts[d] || 0) + 1; });
    (ng.publishers || g.publishers || []).forEach(p => { if (p) pubCounts[p] = (pubCounts[p] || 0) + 1; });
  }
  const topDev = Object.entries(devCounts).sort((a, b) => b[1] - a[1])[0];
  if (topDev && topDev[1] > 1) push('*', 'is-violet', `${topDev[0]} · ${formatNum(topDev[1])}`, 'top developer');
  const topPub = Object.entries(pubCounts).sort((a, b) => b[1] - a[1])[0];
  if (topPub && topPub[1] > 1) push('*', 'is-violet', `${topPub[0]} · ${formatNum(topPub[1])}`, 'top publisher');
  const uniqueDevs = Object.keys(devCounts).length;
  if (uniqueDevs > 1) push('>', '', formatNum(uniqueDevs), 'unique developers');

  const genreCounts = {};
  for (const g of games) {
    const gens = c('gameGenresCanonical')(g);
    gens.forEach(genre => { if (genre) genreCounts[genre] = (genreCounts[genre] || 0) + 1; });
  }
  const topGenre = Object.entries(genreCounts).sort((a, b) => b[1] - a[1])[0];
  if (topGenre) push('*', 'is-amber', `${topGenre[0]} · ${formatNum(topGenre[1])}`, 'top genre');
  const uniqueGenres = Object.keys(genreCounts).length;
  if (uniqueGenres > 1) push('>', '', formatNum(uniqueGenres), 'unique genres');

  const storeCounts = {};
  for (const g of games) {
    const s = c('normalizeGame')(g).store;
    if (s) storeCounts[s] = (storeCounts[s] || 0) + 1;
  }
  const topStore = Object.entries(storeCounts).sort((a, b) => b[1] - a[1])[0];
  if (topStore) push('>', '', `${topStore[0]} · ${formatNum(topStore[1])}`, 'biggest store');

  if (stores > 0 && total > 0) {
    const avgPerStore = Math.round(total / stores);
    push('~', 'is-amber', formatNum(avgPerStore), 'games per store avg');
  }

  return items;
}

function renderMarqueeHtml(items) {
  if (!items.length) return '';
  const itemHtml = items.map(it => `
    <span class="dash-marquee-item">
      <span class="dash-marquee-icon ${escapeAttr(it.iconCls || '')}">${escapeHtml(it.glyph)}</span>
      <strong>${it.valueHtml}</strong>
      <span class="dash-marquee-label">${escapeHtml(it.label)}</span>
    </span>`).join('');
  return `
    <div class="dash-marquee" id="dashboardMarquee" aria-hidden="true">
      <div class="dash-marquee-track">${itemHtml}${itemHtml}</div>
    </div>`;
}

function startInsightRotation(insights) {
  stopInsightRotation();
  const el = document.getElementById('dashboardInsight');
  if (!el || !insights.length) {
    if (el) {
      el.innerHTML = '';
      el.classList.remove('is-visible');
    }
    return;
  }
  _insightIndex = 0;
  const show = (i) => {
    el.classList.remove('is-visible');
    if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
    _insightFadeTimer = setTimeout(() => {
      el.innerHTML = insights[i % insights.length];
      el.classList.add('is-visible');
    }, 250);
  };
  show(0);
  _insightTimer = setInterval(() => {
    _insightIndex += 1;
    show(_insightIndex);
  }, 6000);
}

function computeMegaHeroStats(games) {
  const backlog = games.filter(g => c('getPersonal')(g).status === "backlog");
  const backlogHrs = backlog.reduce((s, g) => s + (c('hltbMain')(g) || 0), 0);
  const playedHrs = games.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  const nonSkip = games.filter(g => c('getPersonal')(g).status !== "skip");
  const finished = games.filter(g => c('getPersonal')(g).status === "finished").length;
  const completion = nonSkip.length ? Math.round((finished / nonSkip.length) * 100) : 0;
  const rated = games.filter(g => c('ratingValue')(g) > 0);
  const avgRating = rated.length ? Math.round(rated.reduce((s, g) => s + c('ratingValue')(g), 0) / rated.length) : "—";
  const wlDeals = state.wishlistGames.filter(g => { const d = c('getDealInfo')(g); return d && (d.cut || 0) > 0; }).length;
  const stores = new Set(games.map(g => c('normalizeGame')(g).store)).size;
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

function syncSpotlightInMega(el, spotlight) {
  const hero = el.querySelector('.dash-mega-hero');
  const existing = document.getElementById('dashboardSpotlight');
  const newKey = spotlight ? c('gameKey')(spotlight) : null;
  if (spotlight && existing?.dataset.key === newKey) {
    primeSpotlightArt(existing);
    return;
  }
  if (spotlight && existing) {
    existing.outerHTML = renderSpotlightHtml(spotlight);
    primeSpotlightArt(document.getElementById('dashboardSpotlight'));
    return;
  }
  if (spotlight && !existing && hero) {
    hero.insertAdjacentHTML('afterbegin', renderSpotlightHtml(spotlight));
    primeSpotlightArt(document.getElementById('dashboardSpotlight'));
    return;
  }
  existing?.remove();
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
  const marquee = document.getElementById('dashboardMarquee');
  if (marquee) marquee.outerHTML = renderMarqueeHtml(marqueeItems);
  else {
    const divider = el.querySelector('.dash-mega-divider');
    divider?.insertAdjacentHTML('beforebegin', renderMarqueeHtml(marqueeItems));
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
  if (spotlight) _spotlightCurrentKey = c('gameKey')(spotlight);
  else _spotlightCurrentKey = null;
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

function applyItchVisibility() {
  const row = document.getElementById("dashboardPicksRow");
  const card = document.getElementById("dashItchCard");
  const has = (state.itchGames || []).length > 0;
  row?.classList.toggle("no-itch", !has);
  card?.classList.toggle("hidden", !has);
}

function renderDashboardPicksVersus(games) {
  const failed = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const hasCover = g => !!(g.library_image || g.header_image) && !failed.has(c('gameKey')(g));

  const ratedAll = games
    .filter(g => c('getPersonal')(g).status === "backlog"
      && c('ratingValue')(g) > 0
      && c('hasEnoughReviews')(g)
      && hasCover(g))
    .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a));

  const fastMax = state.prefs.quickWinMaxHours || 15;
  const fastAll = games
    .filter(g => c('getPersonal')(g).status === "backlog"
      && (c('hltbMain')(g) || 999) <= fastMax
      && c('ratingValue')(g) >= 80
      && hasCover(g))
    .sort((a, b) => {
      const ha = c('hltbMain')(a) || 999;
      const hb = c('hltbMain')(b) || 999;
      if (ha !== hb) return ha - hb;
      return c('ratingValue')(b) - c('ratingValue')(a);
    });

  const balanced = Math.min(ratedAll.length, fastAll.length, 10);
  const sliceCount = balanced > 0 ? balanced : Math.min(Math.max(ratedAll.length, fastAll.length), 10);
  const rated = ratedAll.slice(0, sliceCount);
  const fast = fastAll.slice(0, sliceCount);

  const ratedKeys = new Set(rated.map(g => c('gameKey')(g)));
  const fastKeys = new Set(fast.map(g => c('gameKey')(g)));
  const crossKeys = new Set([...ratedKeys].filter(k => fastKeys.has(k)));

  const row = (g, scoreFn, accentCls) => {
    const cover = g.library_image || c('coverFallbackFor')(g);
    const key = c('gameKey')(g);
    const isCross = crossKeys.has(key);
    const star = isCross ? ' <span class="dash-versus-star" title="Also in the other list">*</span>' : "";
    return `<button type="button" class="dash-list-row dash-versus-row ${accentCls}${isCross ? " is-cross" : ""}" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library"><img class="dash-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" /><span class="truncate flex-1">${escapeHtml(g.name)}${star}</span><span class="text-slate-400">${escapeHtml(scoreFn(g))}</span></button>`;
  };

  const empty = '<p class="text-xs text-slate-500 italic">No matches yet.</p>';
  const ratedEl = document.getElementById("dashVersusRated");
  const fastEl = document.getElementById("dashVersusFast");
  if (ratedEl) {
    ratedEl.innerHTML = rated.length
      ? rated.map(g => row(g, gg => `${c('ratingValue')(gg)}%`, "dash-versus-row--rated")).join("")
      : empty;
  }
  if (fastEl) {
    fastEl.innerHTML = fast.length
      ? fast.map(g => row(g, gg => `${c('hltbMain')(gg) || "?"}h`, "dash-versus-row--fast")).join("")
      : empty;
  }

  const badge = document.getElementById("dashVersusBadge");
  if (badge) {
    if (crossKeys.size) {
      const names = [...crossKeys]
        .map(k => (rated.find(g => c('gameKey')(g) === k) || fast.find(g => c('gameKey')(g) === k))?.name || "")
        .filter(Boolean)
        .join(", ");
      badge.textContent = `${crossKeys.size} cross-list pick${crossKeys.size === 1 ? "" : "s"}`;
      badge.title = names;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
      badge.textContent = "";
      badge.removeAttribute("title");
    }
  }

  applyItchVisibility();
}

function buildWishlistStatsHtml() {
  const wl = state.wishlistGames;
  if (!wl.length) {
    return `<div class="dash-card sm:col-span-3"><div class="text-sm text-slate-400">No wishlist data — run <code class="text-slate-200">fetch_wishlist.py</code>, then reload.</div></div>`;
  }

  const onSale = wl.filter(g => { const d = c('getDealInfo')(g); return d && (d.cut || 0) > 0; });
  const withDeals = c('wishlistGamesWithDeals')(wl);
  const topDeal = withDeals.length
    ? [...withDeals].sort((a, b) => c('dealScore')(b) - c('dealScore')(a))[0]
    : null;

  let hasPricing = false;
  let bestCut = 0;
  let bestCutGame = "";
  let cutSum = 0;
  const cuts = [];
  for (const g of wl) {
    const d = c('getDealInfo')(g);
    if (!d) continue;
    if (d.price != null || d.regular != null || d.cut) hasPricing = true;
    const cut = d.cut || 0;
    if (cut > 0) {
      cutSum += cut;
      cuts.push(cut);
      if (cut > bestCut) {
        bestCut = cut;
        bestCutGame = g.name || "";
      }
    }
  }
  const avgCut = onSale.length ? Math.round(cutSum / onSale.length) : 0;
  const steals = wl.filter(c('isStealDeal'));

  return [
    topDeal ? c('dealHeroCardHtml')(topDeal) : c('dealHeroEmptyHtml')(),
    c('dealSaleScoreboardCardHtml')({
      onSaleCount: onSale.length,
      totalCount: wl.length,
      avgCut,
      bestCut,
      bestCutGame,
      hasPricing,
      cuts,
    }),
    c('dealStealsCardHtml')(steals),
  ].join("");
}

function renderDashboardWishlistStats() {
  // Re-used by both the dashboard mega-grid and the standalone wishlist deal
  // radar shown above the table on the Wishlist view. Iterating over all
  // matching targets keeps a single source of truth for the markup + math.
  const targets = document.querySelectorAll(".dash-wishlist-stats-target");
  if (!targets.length) return;
  const html = buildWishlistStatsHtml();
  for (const el of targets) el.innerHTML = html;
}

export { renderDashboardWishlistStats };

function renderItchHeroHtml(candidates) {
  if (!candidates.length) {
    return `<div class="itch-hero">
      <div class="itch-hero-label"><span>Featured unplayed pick</span></div>
      <div class="itch-hero-empty">No rated picks yet — run <code class="text-slate-200">enrich_steam_reviews.py --stores itch</code> to backfill ratings.</div>
    </div>`;
  }
  const idx = ((itchHeroIndex % candidates.length) + candidates.length) % candidates.length;
  const g = candidates[idx];
  const cover = g.library_image || c('coverFallbackFor')(g);
  const fb = c('coverFallbackFor')(g);
  const key = c('gameKey')(g);
  const rating = c('ratingValue')(g);
  const hltb = c('hltbMain')(g);
  const metaParts = [];
  if (g.publisher) metaParts.push(`by ${escapeHtml(g.publisher)}`);
  if (hltb) metaParts.push(`~${hltb}h`);
  const metaHtml = metaParts.length ? `<div class="itch-hero-meta">${metaParts.join(" · ")}</div>` : "";
  const desc = g.short_text ? `<p class="itch-hero-desc">${escapeHtml(g.short_text)}</p>` : "";
  const tags = c('gameGenresCanonical')(g).slice(0, 3);
  const tagsHtml = tags.length
    ? `<div class="itch-hero-tags">${tags.map(t => `<span class="itch-hero-tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";
  const shuffleBtn = candidates.length > 1
    ? `<button type="button" class="itch-hero-shuffle" data-action="itch-hero-shuffle" title="Cycle picks">↻</button>`
    : "";
  return `<div class="itch-hero">
    <div class="itch-hero-label">
      <span>Featured unplayed pick</span>
      ${shuffleBtn}
    </div>
    <button type="button" class="itch-hero-card" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} on itch.io">
      <img class="itch-hero-cover" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(fb)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
      <div class="itch-hero-body">
        <div class="itch-hero-head">
          <span class="itch-hero-name">${escapeHtml(g.name)}</span>
          <span class="itch-hero-rating">${rating}%</span>
        </div>
        ${metaHtml}
        ${desc}
        ${tagsHtml}
      </div>
    </button>
  </div>`;
}

function renderDashboardItchRecap() {
  const el = document.getElementById("dashItchRecap");
  if (!el) return;
  bindItchRecapClick();
  if (dashboardCharts.chartItchStatus) {
    dashboardCharts.chartItchStatus.destroy();
    delete dashboardCharts.chartItchStatus;
  }

  const total = state.itchGames.length;
  applyItchVisibility();
  if (!total) {
    el.innerHTML = `<p class="text-sm text-slate-400">No itch.io data loaded. Run <code class="text-slate-200">fetch_itch.py</code>, then reload.</p>`;
    return;
  }

  const gamesOnly = state.itchGames.filter(c('itchIsGame'));
  const videogames = gamesOnly.length;
  const rated = gamesOnly.filter(g => c('ratingValue')(g) > 0).length;
  const unrated = videogames - rated;
  const nonGames = total - videogames;
  const backlogged = gamesOnly.filter(g => c('getPersonal')(g).status === "backlog").length;

  const segments = [
    { id: "rated", label: "Rated", count: rated },
    { id: "unrated", label: "Unrated", count: unrated },
    { id: "non", label: "Non-game", count: nonGames },
  ];
  const segSum = segments.reduce((a, s) => a + s.count, 0);
  const segHtml = segSum
    ? `<div class="itch-distribution">
        <div class="itch-distribution-label">Library composition</div>
        <div class="sale-distribution-bar" role="img" aria-label="itch.io library composition">
          ${segments.map(s => s.count
            ? `<span class="sale-distribution-seg itch-seg-${s.id}" style="flex: ${s.count};" title="${s.label}: ${formatNum(s.count)}"></span>`
            : ""
          ).join("")}
        </div>
        <div class="sale-distribution-legend">
          ${segments.map(s => `<span class="sale-distribution-tick ${s.count ? "" : "sale-distribution-tick-empty"}" title="${s.label}: ${formatNum(s.count)}">
            <span class="sale-distribution-swatch itch-seg-${s.id}"></span>
            <span class="sale-distribution-tick-label">${s.label}</span>
            <span class="sale-distribution-tick-count">${formatNum(s.count)}</span>
          </span>`).join("")}
        </div>
      </div>`
    : "";

  const failedItch = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const heroCandidates = gamesOnly
    .filter(g => c('getPersonal')(g).status !== "finished" && (g.playtime_minutes || 0) === 0)
    .filter(g => c('ratingValue')(g) > 0 && c('hasEnoughReviews')(g))
    .filter(g => !!(g.library_image || g.header_image) && !failedItch.has(c('gameKey')(g)))
    .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
    .slice(0, 10);
  if (heroCandidates.length) itchHeroIndex %= heroCandidates.length;
  else itchHeroIndex = 0;
  const heroHtml = videogames ? renderItchHeroHtml(heroCandidates) : "";

  const classCounts = {};
  state.itchGames.forEach(g => {
    const cls = g.classification || "game";
    classCounts[cls] = (classCounts[cls] || 0) + 1;
  });
  const classEntries = Object.entries(classCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([cls, count]) => [cls, count, ITCH_CLASS_LABELS[cls] || cls]);
  const classHtml = classEntries.length
    ? `<div class="itch-breakdown">
        <div class="itch-distribution-label">What's in your library</div>
        <div class="itch-breakdown-list">${itchBreakdownRows(classEntries, "itch-bar-class", null)}</div>
      </div>`
    : "";

  const genreCounts = {};
  gamesOnly.forEach(g => {
    c('gameGenresCanonical')(g).forEach(genre => {
      genreCounts[genre] = (genreCounts[genre] || 0) + 1;
    });
  });
  const genreEntries = Object.entries(genreCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([genre, count]) => [genre, count, genre]);
  const genreHtml = genreEntries.length
    ? `<div class="itch-breakdown">
        <div class="itch-distribution-label">Top itch genres</div>
        <div class="itch-breakdown-list">${itchBreakdownRows(genreEntries, "itch-bar-genre", "itch-drill-genre")}</div>
      </div>`
    : "";

  el.innerHTML = `
    <div class="sale-scoreboard">
      <div class="sale-stat">
        <div class="sale-stat-label">Videogames</div>
        <div class="sale-stat-value">${formatNum(videogames)}<span class="sale-stat-suffix"> / ${formatNum(total)}</span></div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Backlog</div>
        <div class="sale-stat-value ${backlogged ? "" : "sale-stat-muted"}">${backlogged ? formatNum(backlogged) : "—"}</div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Rated</div>
        <div class="sale-stat-value ${rated ? "" : "sale-stat-muted"}">${rated ? formatNum(rated) : "—"}</div>
      </div>
    </div>
    ${segHtml}
    ${heroHtml}
    ${classHtml}
    ${genreHtml}
    <div class="itch-footer">
      <button type="button" class="summary-jump-chip px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs border border-slate-600 cursor-pointer" data-jump-view="itch">Open itch.io tab →</button>
    </div>`;
}

// --- Scatter cluster + inline list (HLTB vs review chart) ---

const SCATTER_HIT_RADIUS_PX = 8;
const SCATTER_STATUS_PRIORITY = { next: 0, playing: 1, unfinished: 2, backlog: 3, finished: 4, live: 5, skip: 6 };
let _scatterListLastKey = null;
let _scatterListClickBound = false;
let _scatterListFrozen = false;
let _scatterListFrozenKey = null;

function hitsAtScatterClick(chart, canvasX, canvasY) {
  const pts = chart._scatterPts;
  const px = chart._scatterPxX;
  const py = chart._scatterPxY;
  if (!pts || !px || !py) return [];
  const r2 = SCATTER_HIT_RADIUS_PX * SCATTER_HIT_RADIUS_PX;
  const hits = [];
  for (let i = 0; i < pts.length; i++) {
    const dx = px[i] - canvasX;
    const dy = py[i] - canvasY;
    if (dx * dx + dy * dy <= r2) hits.push({ pt: pts[i], i, d2: dx * dx + dy * dy });
  }
  hits.sort((a, b) => a.d2 - b.d2);
  return hits;
}

function sortClusterForPicker(hits) {
  return hits.slice().sort((a, b) => {
    const pa = SCATTER_STATUS_PRIORITY[a.pt.status] ?? 99;
    const pb = SCATTER_STATUS_PRIORITY[b.pt.status] ?? 99;
    if (pa !== pb) return pa - pb;
    if (b.pt.y !== a.pt.y) return b.pt.y - a.pt.y;
    return a.pt.x - b.pt.x;
  });
}

function ensureScatterListClickHandler() {
  if (_scatterListClickBound) return;
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  _scatterListClickBound = true;
  el.addEventListener('click', (e) => {
    const row = e.target.closest('.dash-scatter-list-row');
    if (!row?.dataset.key) return;
    e.preventDefault();
    e.stopPropagation();
    dashResetLibraryFiltersExceptDedup();
    c('focusGame')(row.dataset.key);
  });
}

function clearScatterList() {
  _scatterListLastKey = null;
  _scatterListFrozen = false;
  _scatterListFrozenKey = null;
  hideScatterCursorTooltip();
  renderScatterList([]);
}

function pulseScatterList() {
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  el.classList.remove('is-pulsing');
  // Reflow so the animation restarts.
  void el.offsetWidth;
  el.classList.add('is-pulsing');
}

function setScatterListFrozen(frozen) {
  _scatterListFrozen = frozen;
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  el.classList.toggle('is-frozen', frozen);
  if (frozen) pulseScatterList();
  // Force the next render() to repaint so the pin badge appears/disappears.
  _scatterListLastKey = null;
}

function renderScatterList(hits) {
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  ensureScatterListClickHandler();

  if (!hits.length) {
    el.innerHTML = '<div class="dash-scatter-list-hint">Hover a point or cluster to inspect</div>';
    return;
  }

  const key = hits.map(h => h.pt.key).join('|');
  if (key === _scatterListLastKey) return;
  _scatterListLastKey = key;

  const CAP = 12;
  const sorted = sortClusterForPicker(hits);
  const shown = sorted.slice(0, CAP);
  const extra = sorted.length - shown.length;
  const isCluster = hits.length >= 2;
  const pinBadge = _scatterListFrozen
    ? '<span class="dash-scatter-list-pin" title="Click the chart background or another cluster to unpin">Pinned</span>'
    : '';
  const headLabel = isCluster
    ? `${hits.length} games here · click to jump`
    : `${shown[0].pt.label} · click to jump`;
  const headText = `${headLabel}${pinBadge}`;

  const rowHtml = shown.map(({ pt }) => {
    const cover = pt.cover || '';
    const coverHtml = cover
      ? `<img class="dash-scatter-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'" />`
      : `<span class="dash-scatter-list-cover" aria-hidden="true"></span>`;
    return `<button type="button" class="dash-scatter-list-row" data-key="${escapeAttr(pt.key)}" title="Jump to ${escapeAttr(pt.label)} in the library">
      ${coverHtml}
      <span class="dash-scatter-list-name">${escapeHtml(pt.label)}</span>
      <span class="dash-scatter-list-meta">${pt.y}% · ${pt.x}h</span>
    </button>`;
  }).join('');

  el.innerHTML = `
    <div class="dash-scatter-list-head">${headText}</div>
    <div class="dash-scatter-list-strip">${rowHtml}</div>
    ${extra > 0 ? `<div class="dash-scatter-list-foot">+${extra} more — refine with a filter</div>` : ''}
  `;
}

const SCATTER_TIP_MAX = 6;

function hideScatterCursorTooltip() {
  const tip = document.getElementById('chartScatterTooltip');
  if (!tip) return;
  tip.classList.remove('is-visible');
  tip.hidden = true;
}

function ensureScatterWrapListeners(chart) {
  const wrap = chart?.canvas?.parentElement;
  if (!wrap || wrap.dataset.scatterWrapBound) return;
  wrap.dataset.scatterWrapBound = '1';
  wrap.addEventListener('mouseleave', hideScatterCursorTooltip);
}

function showScatterCursorTooltip(chart, hits, canvasX, canvasY) {
  const tip = document.getElementById('chartScatterTooltip');
  const wrap = chart?.canvas?.parentElement;
  if (!tip || !wrap || !hits.length) {
    hideScatterCursorTooltip();
    return;
  }
  ensureScatterWrapListeners(chart);
  const sorted = sortClusterForPicker(hits);
  const shown = sorted.slice(0, SCATTER_TIP_MAX);
  const extra = sorted.length - shown.length;
  const rows = shown.map(({ pt }) =>
    `<div class="dash-scatter-cursor-tip-row">${escapeHtml(pt.label)}</div>`
  ).join('');
  const more = extra > 0
    ? `<div class="dash-scatter-cursor-tip-more">+${extra} more</div>`
    : '';
  tip.innerHTML = `${rows}${more}`;
  tip.hidden = false;
  // Force layout so offsetWidth/Height are valid this frame.
  const tipW = tip.offsetWidth || 180;
  const tipH = tip.offsetHeight || 60;
  const margin = 8;
  let left = canvasX + 14;
  let top = canvasY + 14;
  if (left + tipW > wrap.clientWidth - margin) left = Math.max(margin, canvasX - tipW - 14);
  if (top + tipH > wrap.clientHeight - margin) top = Math.max(margin, canvasY - tipH - 14);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  tip.classList.add('is-visible');
}

function renderDashboardCharts(games) {
  const storeCounts = {};
  games.forEach(g => {
    const s = c('normalizeGame')(g).store;
    storeCounts[s] = (storeCounts[s] || 0) + 1;
  });
  const storeEntries = Object.entries(storeCounts).sort((a, b) => b[1] - a[1]);
  setDashboardChart("chartStoreDonut", {
    type: "doughnut",
    data: {
      labels: storeEntries.map(([k]) => DASH_STORE_LABELS[k] || k),
      datasets: [{ data: storeEntries.map(([, v]) => v), backgroundColor: storeEntries.map(([k]) => DASH_STORE_COLORS[k] || "#64748b"), borderWidth: 0 }],
    },
    options: dashChartOptions({
      plugins: { legend: donutLegendHighlight() },
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillStore(storeEntries[elements[0].index][0]);
      },
    }),
  });

  const statusCounts = {};
  STATUS_CHIP_DEFS.forEach(d => { statusCounts[d.key] = 0; });
  games.forEach(g => { statusCounts[c('chipStatusKey')(g)]++; });
  const statusEntries = STATUS_CHIP_DEFS.filter(d => statusCounts[d.key] > 0 && (d.key !== "__none__" || statusCounts[d.key] > 0));
  setDashboardChart("chartStatusDonut", {
    type: "doughnut",
    data: {
      labels: statusEntries.map(d => d.label),
      datasets: [{ data: statusEntries.map(d => statusCounts[d.key]), backgroundColor: statusEntries.map(d => DASH_STATUS_COLORS[d.key]), borderWidth: 0 }],
    },
    options: dashChartOptions({
      plugins: { legend: donutLegendHighlight() },
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillStatus(statusEntries[elements[0].index].key);
      },
    }),
  });

  const genreCounts = {};
  games.forEach(g => c('gameGenresCanonical')(g).forEach(c => {
    genreCounts[c] = (genreCounts[c] || 0) + 1;
  }));
  const topGenres = Object.entries(genreCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  setDashboardChart("chartGenresBar", {
    type: "bar",
    data: {
      labels: topGenres.map(([g]) => g),
      datasets: [{
        label: "Games",
        data: topGenres.map(([, n]) => n),
        backgroundColor: "#38bdf8",
      }],
    },
    options: dashChartOptions({
      indexAxis: "y",
      layout: { padding: { right: 30 } },
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onClick(_evt, elements) { if (elements.length) dashDrillGenre(topGenres[elements[0].index][0]); },
    }),
    plugins: [makeBarEndLabelsPlugin(i => topGenres[i]?.[1])],
  });

  const stores = [...new Set(games.map(g => c('normalizeGame')(g).store))];
  const backlogByStore = { backlog: {}, finished: {} };
  stores.forEach(s => { backlogByStore.backlog[s] = 0; backlogByStore.finished[s] = 0; });
  games.forEach(g => {
    const st = c('getPersonal')(g).status;
    const store = c('normalizeGame')(g).store;
    const hrs = c('hltbMain')(g) || 0;
    if (st === "backlog") backlogByStore.backlog[store] += hrs;
    else if (st === "finished") backlogByStore.finished[store] += hrs;
  });
  const sortedStores = stores.sort((a, b) => {
    const totalA = (backlogByStore.backlog[a] || 0) + (backlogByStore.finished[a] || 0);
    const totalB = (backlogByStore.backlog[b] || 0) + (backlogByStore.finished[b] || 0);
    return totalB - totalA;
  });
  const storeBrandColors = sortedStores.map(s => DASH_STORE_COLORS[s] || "#64748b");
  setDashboardChart("chartBacklogStore", {
    type: "bar",
    data: {
      labels: sortedStores.map(s => DASH_STORE_LABELS[s] || s),
      datasets: [
        {
          label: "Backlog",
          data: sortedStores.map(s => backlogByStore.backlog[s]),
          backgroundColor: storeBrandColors.map(c => c + "FF"),
        },
        {
          label: "Finished",
          data: sortedStores.map(s => backlogByStore.finished[s]),
          backgroundColor: storeBrandColors.map(c => c + "55"),
        },
      ],
    },
    options: dashChartOptions({
      indexAxis: "y",
      layout: { padding: { right: 60 } },
      plugins: { legend: { display: false } },
      scales: { x: { stacked: true, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { stacked: true, ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onClick(_evt, elements) {
        if (!elements.length) return;
        const el = elements[0];
        const store = sortedStores[el.index];
        const status = el.datasetIndex === 0 ? "backlog" : "finished";
        dashDrillStoreStatus(store, status);
      },
    }),
    plugins: [makeBarEndLabelsPlugin(i => {
      const s = sortedStores[i];
      const total = Math.round((backlogByStore.backlog[s] || 0) + (backlogByStore.finished[s] || 0));
      return total > 0 ? formatNum(total) : "";
    })],
  });

  const buckets = ["0–2h", "2–5h", "5–10h", "10–20h", "20–40h", "40h+"];
  const bucketCounts = [0, 0, 0, 0, 0, 0];
  games.filter(g => c('getPersonal')(g).status === "backlog").forEach(g => {
    const h = c('hltbMain')(g);
    if (h == null) return;
    if (h <= 2) bucketCounts[0]++;
    else if (h <= 5) bucketCounts[1]++;
    else if (h <= 10) bucketCounts[2]++;
    else if (h <= 20) bucketCounts[3]++;
    else if (h <= 40) bucketCounts[4]++;
    else bucketCounts[5]++;
  });
  const hltbBucketColors = ["#22c55e", "#84cc16", "#eab308", "#f59e0b", "#ef4444", "#b91c1c"];
  setDashboardChart("chartHltbHist", {
    type: "bar",
    data: { labels: buckets, datasets: [{ label: "Backlog games", data: bucketCounts, backgroundColor: hltbBucketColors, borderColor: hltbBucketColors, borderWidth: 1 }] },
    options: dashChartOptions({
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } } },
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillHltbBucket(elements[0].index);
      },
    }),
  });

  const reviewBuckets = {
    "Overwhelmingly Positive": 0, "Very Positive": 0, "Mostly Positive": 0,
    "Mixed": 0, "Mostly Negative": 0, "Negative": 0, "Unreviewed": 0,
  };
  games.forEach(g => {
    const d = g.steam_review_desc;
    if (d && reviewBuckets[d] !== undefined) reviewBuckets[d]++;
    else if (c('ratingValue')(g) > 0) reviewBuckets.Mixed++;
    else reviewBuckets.Unreviewed++;
  });
  const revEntries = Object.entries(reviewBuckets).filter(([, n]) => n > 0);
  setDashboardChart("chartReviewDonut", {
    type: "doughnut",
    data: {
      labels: revEntries.map(([k]) => k),
      datasets: [{ data: revEntries.map(([, n]) => n), backgroundColor: revEntries.map(([k]) => DASH_REVIEW_COLORS[k] || "#475569"), borderWidth: 0 }],
    },
    options: dashChartOptions({
      plugins: { legend: donutLegendHighlight() },
      onClick(_evt, elements) {
        if (!elements.length) return;
        const label = revEntries[elements[0].index][0];
        const minRating = DASH_REVIEW_MIN_RATING[label];
        if (minRating == null) return;
        dashDrillMinRating(minRating);
      },
    }),
  });

  const total = games.length;
  const topStore = storeEntries[0] || [null, 0];
  const storePct = total ? Math.round(topStore[1] / total * 100) : 0;
  const storeHeadlineEl = document.getElementById('ribbonStoreHeadline');
  if (storeHeadlineEl) {
    storeHeadlineEl.innerHTML = topStore[0]
      ? `<strong>${escapeHtml(DASH_STORE_LABELS[topStore[0]] || topStore[0])}</strong> ${storePct}%`
      : '<strong>—</strong>';
  }

  const backlogCount = games.filter(g => c('getPersonal')(g).status === 'backlog').length;
  const statusHeadlineEl = document.getElementById('ribbonStatusHeadline');
  if (statusHeadlineEl) {
    statusHeadlineEl.innerHTML = `<strong>${escapeHtml(formatNum(backlogCount))}</strong> in backlog`;
  }

  const positive = ['Overwhelmingly Positive', 'Very Positive', 'Mostly Positive']
    .reduce((s, k) => s + (reviewBuckets[k] || 0), 0);
  const ratedTotal = Object.entries(reviewBuckets)
    .filter(([k]) => k !== 'Unreviewed')
    .reduce((s, [, n]) => s + n, 0);
  const positivePct = ratedTotal ? Math.round(positive / ratedTotal * 100) : 0;
  const reviewHeadlineEl = document.getElementById('ribbonReviewHeadline');
  if (reviewHeadlineEl) {
    reviewHeadlineEl.innerHTML = `<strong>${positivePct}%</strong> positive`;
  }

  const yearCounts = {};
  games.forEach(g => {
    const y = (g.release_date || "").slice(0, 4);
    if (y && /^\d{4}$/.test(y) && +y >= 1990) yearCounts[y] = (yearCounts[y] || 0) + 1;
  });
  const years = Object.keys(yearCounts).sort();
  const trendData = years.map(y => yearCounts[y]);
  const rolling = years.map((_, i) => {
    const lo = Math.max(0, i - 1);
    const hi = Math.min(years.length - 1, i + 1);
    let sum = 0, n = 0;
    for (let j = lo; j <= hi; j++) { sum += trendData[j]; n++; }
    return n > 0 ? sum / n : 0;
  });
  const decadeStats = buildDecadeStats(games);
  setDashboardChart("chartReleases", {
    type: "line",
    data: {
      labels: years,
      datasets: [
        {
          label: "Games / year",
          data: trendData,
          borderColor: "rgba(56, 189, 248, 0.95)",
          backgroundColor: "rgba(56, 189, 248, 0.18)",
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.25,
          fill: true,
        },
        {
          label: "3-yr rolling avg",
          data: rolling,
          borderColor: "rgba(52, 211, 153, 0.95)",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.4,
          borderDash: [4, 3],
          fill: false,
        },
      ],
    },
    options: dashChartOptions({
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            color: "#cbd5e1",
            boxWidth: 14,
            boxHeight: 8,
            font: { size: 11 },
            usePointStyle: true,
            pointStyle: "rectRounded",
          },
        },
        tooltip: {
          mode: "index",
          intersect: false,
          filter(item) {
            const chart = item.chart;
            return !chart._eraHover;
          },
        },
      },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { color: "#94a3b8", maxRotation: 45 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } },
      },
      onHover(evt, _els, chart) {
        const labelHit = findEraLabelHit(chart, evt.x, evt.y);
        chart._eraHover = labelHit?.era ?? null;
        updateEraTooltip(chart, labelHit, decadeStats, evt);
        if (labelHit) chart.tooltip?.setActiveElements([], { x: 0, y: 0 });
      },
      onClick(evt, els, chart) {
        if (els.length) {
          dashSetReleaseYear(String(chart.data.labels[els[0].index]));
          return;
        }
        const bandHit = findEraBandAtPixel(chart, evt.x);
        if (bandHit) dashSetReleaseYear(`${bandHit.era.start}s`);
      },
    }),
    plugins: [makeEraBandsPlugin(years)],
  });
  const releasesCanvas = document.getElementById("chartReleases");
  if (releasesCanvas && !releasesCanvas.dataset.eraLeaveBound) {
    releasesCanvas.dataset.eraLeaveBound = "1";
    releasesCanvas.addEventListener("mouseleave", () => {
      const tip = document.getElementById("chartReleasesEraTooltip");
      tip?.classList.remove("is-visible");
      if (tip) tip.hidden = true;
      const ch = dashboardCharts.chartReleases;
      if (ch) ch._eraHover = null;
    });
  }

  const scatterPts = games.filter(g => c('ratingValue')(g) > 0 && c('hltbMain')(g) != null && c('hltbMain')(g) > 0).map(g => ({
    x: c('hltbMain')(g),
    y: c('ratingValue')(g),
    label: g.name,
    key: c('gameKey')(g),
    status: (c('getPersonal')(g).status) || 'backlog',
    cover: g.library_image || g.header_image || c('coverFallbackFor')(g),
  }));
  const scatterClusterPlugin = {
    id: 'scatterCluster',
    afterLayout(chart) {
      const xs = chart.scales?.x;
      const ys = chart.scales?.y;
      if (!xs || !ys) return;
      const px = new Array(scatterPts.length);
      const py = new Array(scatterPts.length);
      for (let i = 0; i < scatterPts.length; i++) {
        px[i] = xs.getPixelForValue(scatterPts[i].x);
        py[i] = ys.getPixelForValue(scatterPts[i].y);
      }
      chart._scatterPts = scatterPts;
      chart._scatterPxX = px;
      chart._scatterPxY = py;
      // Cluster count per data index: how many *other* points fall within hit radius.
      const r2 = SCATTER_HIT_RADIUS_PX * SCATTER_HIT_RADIUS_PX;
      const counts = new Array(scatterPts.length).fill(0);
      for (let i = 0; i < scatterPts.length; i++) {
        for (let j = i + 1; j < scatterPts.length; j++) {
          const dx = px[i] - px[j];
          const dy = py[i] - py[j];
          if (dx * dx + dy * dy <= r2) {
            counts[i]++;
            counts[j]++;
          }
        }
      }
      chart._scatterClusterCounts = counts;
    },
  };
  const ratingGradient = (rating, alpha) => {
    const t = Math.max(0, Math.min(1, rating / 100));
    const r = Math.round(245 + (16 - 245) * t);
    const g = Math.round(158 + (185 - 158) * t);
    const b = Math.round(11 + (129 - 11) * t);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  };
  setDashboardChart("chartScatter", {
    type: "scatter",
    data: {
      datasets: [{
        label: "Games",
        data: scatterPts.map(p => ({ x: p.x, y: p.y })),
        backgroundColor: scatterPts.map(p => ratingGradient(p.y, 0.55)),
        borderColor: scatterPts.map(p => ratingGradient(p.y, 0.95)),
        borderWidth: 0.6,
        pointRadius: 4,
        pointHoverRadius: 7,
      }],
    },
    options: dashChartOptions({
      animation: {
        duration: 900,
        easing: "easeOutQuart",
      },
      animations: {
        y: {
          type: "number",
          duration: 900,
          easing: "easeOutQuart",
          from: (ctx) => {
            if (ctx.type !== "data") return undefined;
            const yScale = ctx.chart.scales?.y;
            return yScale ? yScale.getPixelForValue(0) : undefined;
          },
        },
        backgroundColor: {
          type: "color",
          duration: 900,
          easing: "easeOutQuart",
          from: "rgba(148, 163, 184, 0)",
        },
        borderColor: {
          type: "color",
          duration: 900,
          easing: "easeOutQuart",
          from: "rgba(148, 163, 184, 0)",
        },
      },
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "HLTB main (hours, log scale)", color: "#94a3b8" },
          min: 0.5,
          ticks: {
            color: "#94a3b8",
            autoSkip: false,
            callback(v) {
              const allowed = new Set([1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2000]);
              return allowed.has(Number(v)) ? `${v}h` : "";
            },
          },
          grid: { color: "#334155" },
        },
        y: { title: { display: true, text: "Steam review %", color: "#94a3b8" }, min: 0, max: 100, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: "nearest",
          intersect: true,
          // Show the tooltip only when there is a single point under the cursor.
          // Clusters are handled by the inline list below the chart.
          filter(item) {
            const counts = item.chart._scatterClusterCounts;
            const extra = counts ? (counts[item.dataIndex] || 0) : 0;
            return extra === 0;
          },
          callbacks: {
            title(items) {
              const it = items[0];
              if (!it) return "";
              const pt = scatterPts[it.dataIndex];
              return pt ? pt.label : "";
            },
            label(ctx) {
              const pt = scatterPts[ctx.dataIndex];
              return pt ? `${pt.x}h · ${pt.y}%` : "";
            },
          },
        },
      },
      onHover(evt, _elements, chart) {
        if (!evt) return;
        if (evt.native?.type === "mouseout") {
          hideScatterCursorTooltip();
          return;
        }
        const cx = evt.x ?? (evt.native?.offsetX ?? 0);
        const cy = evt.y ?? (evt.native?.offsetY ?? 0);
        const hits = hitsAtScatterClick(chart, cx, cy);
        if (hits.length >= 2) {
          showScatterCursorTooltip(chart, hits, cx, cy);
        } else {
          hideScatterCursorTooltip();
        }
        if (_scatterListFrozen) return;
        if (hits.length >= 1) renderScatterList(hits);
        // hits.length === 0 (and not frozen): leave the list sticky until another hover replaces it.
      },
      onClick(evt, _elements, chart) {
        const cx = evt.x ?? (evt.native?.offsetX ?? 0);
        const cy = evt.y ?? (evt.native?.offsetY ?? 0);
        const hits = hitsAtScatterClick(chart, cx, cy);
        if (!hits.length) {
          if (_scatterListFrozen) {
            _scatterListFrozenKey = null;
            setScatterListFrozen(false);
            renderScatterList([]);
          }
          return;
        }
        if (hits.length === 1) {
          dashResetLibraryFiltersExceptDedup();
          c("focusGame")(hits[0].pt.key);
          return;
        }
        const key = hits.map(h => h.pt.key).join('|');
        if (_scatterListFrozen && key === _scatterListFrozenKey) {
          _scatterListFrozenKey = null;
          setScatterListFrozen(false);
          renderScatterList(hits);
          return;
        }
        _scatterListFrozenKey = key;
        setScatterListFrozen(true);
        renderScatterList(hits);
        hideScatterCursorTooltip();
      },
    }),
    plugins: [scatterClusterPlugin],
  });
  renderScatterList([]);

}

export function renderDashboard(opts = {}) {
  if (state.activeView !== "dashboard") return;
  const loading = document.getElementById("dashboardLoading");
  const content = document.getElementById("dashboardContent");
  if (typeof Chart === "undefined") {
    loading?.classList.remove("hidden");
    content?.classList.add("hidden");
    if (loading) loading.textContent = "Loading charts…";
    return;
  }
  if (!state.dashboardDataReady) {
    loading?.classList.remove("hidden");
    content?.classList.add("hidden");
    if (loading) loading.textContent = "Loading library…";
    return;
  }
  loading?.classList.add("hidden");
  content?.classList.remove("hidden");

  // Same-data revisit: skip the full re-render (charts stay built), just
  // replay the entrance animations and resume the rotation timers.
  const fp = dashboardFingerprint();
  if (!opts.force && fp === _dashRenderedFingerprint && _dashMegaShellBuilt) {
    const games = dashboardLibraryGames();
    const spotlightPool = _spotlightPool.length ? _spotlightPool : pickSpotlightGames(games);
    startSpotlightRotation(spotlightPool);
    startInsightRotation(buildInsightPool(games));
    replayDashboardChartAnimations();
    return;
  }

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
  _dashRenderedFingerprint = fp;
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
