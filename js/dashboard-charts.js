// Chart.js setup for the dashboard: chart instance cache, lazy render queue, era bands, scatter cluster picker, renderDashboardCharts. Biggest module.
// Extracted from dashboard.js as part of the dashboard module split.

import { state, STATUS_CHIP_DEFS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { gameKey, normalizeGame, hltbMain, ratingValue, hasEnoughReviews, coverFallbackFor, libraryCoverFor, sanitizeCoverUrl, itchIsGame, chipStatusKey } from './game-core.js';
import { gameGenresCanonical } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { focusGame } from './table-ui.js';
import { dashStoreColor, DASH_STATUS_COLORS, DASH_REVIEW_COLORS, DASH_STORE_LABELS, HLTB_BUCKETS, ITCH_CLASS_LABELS } from './dashboard-shared.js';
import { prefersReducedMotion } from './motion.js';
// Click handlers route into drilldown helpers. One-way import; drilldown
// does not import this module.
import { dashDrillStore, dashDrillStatus, dashDrillStoreStatus, dashSetReleaseYear, dashDrillHltbBucket, dashDrillMinRating, dashDrillGenre, dashFinishDrillToLibrary } from './dashboard-drilldown.js';

export const dashboardCharts = {};
const pendingChartRenders = new Map();

function cssAccentVar(name) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || null;
}

/** Live theme accent (falls back to default sky if the token is missing). */
function accentColor() {
  return cssAccentVar('--accent') || '#38bdf8';
}

function accentRgba(alpha, varName = '--accent') {
  const c = cssAccentVar(varName) || '#38bdf8';
  if (!c.startsWith('#')) return c;
  const hex = c.slice(1);
  const full = hex.length === 3 ? hex.split('').map((x) => x + x).join('') : hex;
  const n = parseInt(full, 16);
  const r = (n >> 16) & 255;
  const g = (n >> 8) & 255;
  const b = n & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
let chartLazyObserver = null;

const CHART_STAGGER_MS = 120;
const chartRenderQueue = [];
let chartRenderTimer = null;
let lastChartRenderAt = 0;
let _chartStaggerSuppressedUntil = 0;

/** Batch lazy chart paints when the boot curtain reveals the dashboard (log: stagger queue caused 6×120ms pop-in). */
export function suppressChartStaggerForBoot(ms = 900) {
  const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
  _chartStaggerSuppressedUntil = now + ms;
}

export function resizeRibbonCharts() {
  for (const chart of Object.values(dashboardCharts)) {
    const canvas = chart?.canvas;
    if (!canvas || !canvas.parentNode || !canvas.closest('.dash-ribbon-chart')) continue;
    if (!document.body.contains(canvas)) continue;
    try { chart.resize(); } catch (_) { /* disposed */ }
  }
}

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
  const now = (typeof performance !== "undefined" ? performance.now() : Date.now());
  if (now < _chartStaggerSuppressedUntil) {
    try { fn(); } catch (err) { console.error("Lazy chart render failed:", err); }
    return;
  }
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

/** Pause or resume Chart.js responsive resize on mega-hero ribbon donuts during
 *  a window drag (log: 72 resize events/gesture still triggered chart relayout). */
export function setRibbonChartsResponsive(enabled) {
  let touched = 0;
  for (const chart of Object.values(dashboardCharts)) {
    if (!chart?.canvas?.closest('.dash-ribbon-chart')) continue;
    touched++;
    if (enabled) {
      if (chart._resizeQuietSaved == null) continue;
      chart.options.responsive = chart._resizeQuietSaved;
      delete chart._resizeQuietSaved;
      try { chart.resize(); } catch (_) { /* disposed */ }
    } else if (chart.options.responsive) {
      chart._resizeQuietSaved = chart.options.responsive;
      chart.options.responsive = false;
    }
  }
  return touched;
}

export function destroyDashboardCharts() {
  // Rotations (insight + spotlight) are deliberately NOT stopped here so an in-place
  // dashboard re-render doesn't reset the spotlight. Use stopDashboardRotations()
  // from the actual teardown sites (view switch).
  cancelScatterHoverFrame();
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

/** Replay the entrance animation on live charts without rebuilding them. */
export function replayDashboardChartAnimations({ ribbonOnly = false } = {}) {
  // Tab return: ribbonOnly skips scatter / bar charts — reset+update on thousands
  // of scatter points blocked the main thread and froze the dashboard.
  for (const chart of Object.values(dashboardCharts)) {
    if (ribbonOnly && !chart?.canvas?.closest('.dash-ribbon-chart')) continue;
    try {
      chart.reset();
      chart.update();
    } catch (_) { /* chart was disposed externally */ }
  }
}

function dashChartOptions(extra = {}) {
  const { animations: extraAnim, animation: extraAnimation, ...rest } = extra;
  const reduced = prefersReducedMotion();
  return {
    responsive: true,
    maintainAspectRatio: false,
    // Debounce Chart.js resize so a continuous viewport drag coalesces into one
    // re-layout after it settles (mirrors the landing demo donut precaution).
    resizeDelay: 200,
    plugins: { legend: { labels: { color: "#ffffff", boxWidth: 12 } } },
    ...(reduced || extraAnimation != null ? {
      animation: reduced ? { duration: 0 } : extraAnimation,
    } : {}),
    animations: {
      resize: { duration: 0 },
      ...(reduced ? {} : extraAnim),
    },
    ...rest,
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
    // Chart.js responsive init reads the canvas's parent box; a chart built while
    // #dashboardContainer is display:none (boot curtain) crashes in getMaximumSize.
    if (canvas.offsetParent === null && canvas.getClientRects().length === 0) {
      pendingChartRenders.set(id, build);
      ensureChartObserver()?.observe(canvas);
      return;
    }
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

export const ERA_BANDS = [
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
    const ratings = eraGames.map(g => ratingValue(g)).filter(n => n > 0);
    const hours = eraGames.map(g => hltbMain(g)).filter(n => n != null && n > 0);
    const top = eraGames.slice().sort((a, b) => ratingValue(b) - ratingValue(a))[0];
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

const SCATTER_HIT_RADIUS_PX = 8;
/** Spatial hash cell size — matches hit radius so only 3×3 neighbor cells are scanned. */
const SCATTER_CELL_PX = SCATTER_HIT_RADIUS_PX;
const SCATTER_STATUS_PRIORITY = { next: 0, playing: 1, unfinished: 2, backlog: 3, finished: 4, live: 5, skip: 6 };
const SCATTER_TIP_MAX = 6;

let _scatterHoverRaf = null;
let _scatterHoverPending = null;
let _scatterHoverLastKey = null;

let _scatterListClickBound = false;
let _scatterListEscBound = false;
let _scatterListLastKey = null;
let _scatterListLastFitCount = 0;
let _scatterListLastHits = null;
let _scatterListResizeObs = null;
let _scatterListFrozen = false;
let _scatterListFrozenKey = null;

const SCATTER_TILE_W = 72;
const SCATTER_TILE_GAP = 6;
const SCATTER_STRIP_PAD_X = 16;

function computeScatterFitCount(stripEl) {
  if (!stripEl) return 0;
  const w = stripEl.clientWidth - SCATTER_STRIP_PAD_X;
  if (w <= 0) return 0;
  // Each tile + gap takes (W + GAP), but the last tile doesn't need a trailing gap.
  return Math.max(1, Math.floor((w + SCATTER_TILE_GAP) / (SCATTER_TILE_W + SCATTER_TILE_GAP)));
}

function ensureScatterListResizeObserver() {
  if (_scatterListResizeObs || typeof ResizeObserver === "undefined") return;
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  _scatterListResizeObs = new ResizeObserver(() => {
    if (!_scatterListLastHits?.length) return;
    const stripEl = el.querySelector('.dash-scatter-list-strip');
    const next = computeScatterFitCount(stripEl);
    if (next === _scatterListLastFitCount) return;
    _scatterListLastKey = null;
    renderScatterList(_scatterListLastHits);
  });
  _scatterListResizeObs.observe(el);
}

function scatterGridKey(gx, gy) {
  return `${gx},${gy}`;
}

/** Bucket point indices by canvas pixel cell — O(n) build, O(1) neighbor lookup. */
function buildScatterSpatialGrid(px, py) {
  const grid = new Map();
  const cell = SCATTER_CELL_PX;
  for (let i = 0; i < px.length; i++) {
    const key = scatterGridKey(Math.floor(px[i] / cell), Math.floor(py[i] / cell));
    let bucket = grid.get(key);
    if (!bucket) {
      bucket = [];
      grid.set(key, bucket);
    }
    bucket.push(i);
  }
  return grid;
}

function countScatterClusters(px, py, grid) {
  const counts = new Array(px.length).fill(0);
  const r2 = SCATTER_HIT_RADIUS_PX * SCATTER_HIT_RADIUS_PX;
  const cell = SCATTER_CELL_PX;
  for (let i = 0; i < px.length; i++) {
    const gx = Math.floor(px[i] / cell);
    const gy = Math.floor(py[i] / cell);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        const bucket = grid.get(scatterGridKey(gx + dx, gy + dy));
        if (!bucket) continue;
        for (const j of bucket) {
          if (j <= i) continue;
          const ddx = px[i] - px[j];
          const ddy = py[i] - py[j];
          if (ddx * ddx + ddy * ddy <= r2) {
            counts[i]++;
            counts[j]++;
          }
        }
      }
    }
  }
  return counts;
}

function hitsAtScatterClick(chart, canvasX, canvasY) {
  const pts = chart._scatterPts;
  const px = chart._scatterPxX;
  const py = chart._scatterPxY;
  const grid = chart._scatterGrid;
  if (!pts || !px || !py || !grid) return [];
  const r2 = SCATTER_HIT_RADIUS_PX * SCATTER_HIT_RADIUS_PX;
  const cell = SCATTER_CELL_PX;
  const gx = Math.floor(canvasX / cell);
  const gy = Math.floor(canvasY / cell);
  const hits = [];
  for (let dx = -1; dx <= 1; dx++) {
    for (let dy = -1; dy <= 1; dy++) {
      const bucket = grid.get(scatterGridKey(gx + dx, gy + dy));
      if (!bucket) continue;
      for (const i of bucket) {
        const ddx = px[i] - canvasX;
        const ddy = py[i] - canvasY;
        if (ddx * ddx + ddy * ddy <= r2) hits.push({ pt: pts[i], i, d2: ddx * ddx + ddy * ddy });
      }
    }
  }
  hits.sort((a, b) => a.d2 - b.d2);
  return hits;
}

function scatterHitsKey(hits) {
  if (!hits.length) return "";
  return hits.map((h) => h.i).join(",");
}

function cancelScatterHoverFrame() {
  if (_scatterHoverRaf != null) {
    cancelAnimationFrame(_scatterHoverRaf);
    _scatterHoverRaf = null;
  }
  _scatterHoverPending = null;
}

function runScatterHover(evt, chart) {
  if (!evt) return;
  if (evt.native?.type === "mouseout") {
    _scatterHoverLastKey = null;
    hideScatterCursorTooltip();
    return;
  }
  const cx = evt.x ?? (evt.native?.offsetX ?? 0);
  const cy = evt.y ?? (evt.native?.offsetY ?? 0);
  const hits = hitsAtScatterClick(chart, cx, cy);
  const key = scatterHitsKey(hits);
  if (key === _scatterHoverLastKey) return;
  _scatterHoverLastKey = key;
  if (hits.length >= 2) {
    showScatterCursorTooltip(chart, hits, cx, cy);
  } else {
    hideScatterCursorTooltip();
  }
}

function scheduleScatterHover(evt, chart) {
  if (evt?.native?.type === "mouseout") {
    cancelScatterHoverFrame();
    runScatterHover(evt, chart);
    return;
  }
  _scatterHoverPending = { evt, chart };
  if (_scatterHoverRaf != null) return;
  _scatterHoverRaf = requestAnimationFrame(() => {
    _scatterHoverRaf = null;
    const pending = _scatterHoverPending;
    _scatterHoverPending = null;
    if (!pending) return;
    runScatterHover(pending.evt, pending.chart);
  });
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

function collapseScatterList() {
  _scatterListFrozenKey = null;
  setScatterListFrozen(false);
  renderScatterList([]);
}

export function resetScatterListView() {
  clearScatterList();
}

function ensureScatterListEscHandler() {
  if (_scatterListEscBound || typeof document === 'undefined') return;
  _scatterListEscBound = true;
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || !_scatterListFrozen) return;
    const el = document.getElementById('chartScatterList');
    if (!el?.classList.contains('is-open')) return;
    e.preventDefault();
    collapseScatterList();
  });
}

function ensureScatterListClickHandler() {
  if (_scatterListClickBound) return;
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  _scatterListClickBound = true;
  ensureScatterListEscHandler();
  el.addEventListener('click', (e) => {
    if (e.target.closest('[data-scatter-collapse]')) {
      e.preventDefault();
      e.stopPropagation();
      collapseScatterList();
      return;
    }
    const row = e.target.closest('.dash-scatter-list-row');
    if (!row?.dataset.key) return;
    e.preventDefault();
    e.stopPropagation();
    focusGame(row.dataset.key);
  });
}

function clearScatterList() {
  _scatterListLastKey = null;
  _scatterListLastHits = null;
  _scatterListLastFitCount = 0;
  _scatterListFrozen = false;
  _scatterListFrozenKey = null;
  hideScatterCursorTooltip();
  renderScatterList([]);
}

function pulseScatterList() {
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  el.classList.remove('is-pulsing');
  requestAnimationFrame(() => el.classList.add('is-pulsing'));
}

function setScatterListFrozen(frozen) {
  _scatterListFrozen = frozen;
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  el.classList.toggle('is-frozen', frozen);
  el.classList.toggle('is-open', frozen);
  el.setAttribute('aria-expanded', frozen ? 'true' : 'false');
  if (frozen) pulseScatterList();
  _scatterListLastKey = null;
}

function renderScatterList(hits) {
  const el = document.getElementById('chartScatterList');
  if (!el) return;
  ensureScatterListClickHandler();
  ensureScatterListResizeObserver();

  if (!hits.length) {
    el.classList.remove('is-open', 'is-frozen');
    el.setAttribute('aria-expanded', 'false');
    el.innerHTML = '<div class="dash-scatter-list-hint" title="Overlapping points open this inspector; a single point jumps to the library">Click a cluster of games to inspect</div>';
    _scatterListLastKey = null;
    _scatterListLastHits = null;
    _scatterListLastFitCount = 0;
    return;
  }

  _scatterListLastHits = hits;
  const sorted = sortClusterForPicker(hits);
  // Width-driven cap. Measure the strip we'll paint into; on first render
  // (.strip not in DOM yet) fall back to the container width minus chrome.
  const measureEl = el.querySelector('.dash-scatter-list-strip') || el;
  const fitCount = Math.max(1, computeScatterFitCount(measureEl));
  _scatterListLastFitCount = fitCount;
  // Reserve one tile for the "+N more" badge when we actually have overflow.
  const overflow = Math.max(0, sorted.length - fitCount);
  const visibleCount = overflow > 0 ? Math.max(1, fitCount - 1) : sorted.length;
  const shown = sorted.slice(0, visibleCount);
  const remaining = sorted.length - visibleCount;

  const key = `${hits.map(h => h.pt.key).join('|')}|fit=${fitCount}|frozen=${_scatterListFrozen ? 1 : 0}`;
  if (key === _scatterListLastKey) return;
  _scatterListLastKey = key;

  const isCluster = hits.length >= 2;
  const headLabel = isCluster
    ? `${hits.length} games here · click to jump`
    : `${sorted[0].pt.label} · click to jump`;
  const closeBtn = '<button type="button" class="dash-scatter-list-close" data-scatter-collapse aria-label="Collapse inspector" title="Collapse (Esc)">×</button>';

  const rowHtml = shown.map(({ pt }) => {
    const cover = pt.cover || '';
    const coverHtml = cover
      ? `<img class="dash-scatter-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'" />`
      : `<span class="dash-scatter-list-cover" aria-hidden="true"></span>`;
    return `<button type="button" class="dash-scatter-list-row" data-key="${escapeAttr(pt.key)}" title="Jump to ${escapeAttr(pt.label)} in Library">
      ${coverHtml}
      <span class="dash-scatter-list-name">${escapeHtml(pt.label)}</span>
      <span class="dash-scatter-list-meta" title="Steam review % · HLTB main hours">${pt.y}% · ${pt.x}h</span>
    </button>`;
  }).join('');

  const overflowTile = remaining > 0
    ? `<div class="dash-scatter-list-more" aria-hidden="true" title="${remaining} more game${remaining === 1 ? '' : 's'} in this cluster - narrows as the window widens">
        <span class="dash-scatter-list-more-num">+${remaining}</span>
        <span class="dash-scatter-list-more-label">more</span>
      </div>`
    : '';

  el.innerHTML = `
    <div class="dash-scatter-list-head">
      <span class="dash-scatter-list-head-label" title="${isCluster ? 'Overlapping scatter points in this cluster' : 'Single scatter point - click row to jump'}">${headLabel}</span>
      ${closeBtn}
    </div>
    <div class="dash-scatter-list-strip">${rowHtml}${overflowTile}</div>
  `;
}

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

export function renderDashboardCharts(games) {
  const storeCounts = {};
  games.forEach(g => {
    const s = normalizeGame(g).store;
    storeCounts[s] = (storeCounts[s] || 0) + 1;
  });
  const storeEntries = Object.entries(storeCounts).sort((a, b) => b[1] - a[1]);
  setDashboardChart("chartStoreDonut", {
    type: "doughnut",
    data: {
      labels: storeEntries.map(([k]) => DASH_STORE_LABELS[k] || k),
      datasets: [{ data: storeEntries.map(([, v]) => v), backgroundColor: storeEntries.map(([k]) => dashStoreColor(k)), borderWidth: 0 }],
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
  games.forEach(g => { statusCounts[chipStatusKey(g)]++; });
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
  games.forEach(g => gameGenresCanonical(g).forEach(c => {
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
        backgroundColor: accentColor(),
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

  const stores = [...new Set(games.map(g => normalizeGame(g).store))];
  const backlogByStore = { backlog: {}, finished: {} };
  stores.forEach(s => { backlogByStore.backlog[s] = 0; backlogByStore.finished[s] = 0; });
  games.forEach(g => {
    const st = getPersonal(g).status;
    const store = normalizeGame(g).store;
    const hrs = hltbMain(g) || 0;
    if (st === "backlog") backlogByStore.backlog[store] += hrs;
    else if (st === "finished") backlogByStore.finished[store] += hrs;
  });
  const sortedStores = stores.sort((a, b) => {
    const totalA = (backlogByStore.backlog[a] || 0) + (backlogByStore.finished[a] || 0);
    const totalB = (backlogByStore.backlog[b] || 0) + (backlogByStore.finished[b] || 0);
    return totalB - totalA;
  });
  const storeBrandColors = sortedStores.map(s => dashStoreColor(s));
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
  games.filter(g => getPersonal(g).status === "backlog").forEach(g => {
    const h = hltbMain(g);
    if (h == null) return;
    if (h <= 2) bucketCounts[0]++;
    else if (h <= 5) bucketCounts[1]++;
    else if (h <= 10) bucketCounts[2]++;
    else if (h <= 20) bucketCounts[3]++;
    else if (h <= 40) bucketCounts[4]++;
    else bucketCounts[5]++;
  });
  const hltbBucketColors = ["#22c55e", "#84cc16", "#eab308", "#f59e0b", "#ef4444", "#b91c1c"];
  const hltbBarDuration = 600;
  // Slight left-to-right stagger: each bar starts a touch after the one to its left.
  const hltbBarDelay = (ctx) =>
    ctx.type === "data" && ctx.mode === "default" ? ctx.dataIndex * 60 : 0;
  setDashboardChart("chartHltbHist", {
    type: "bar",
    data: { labels: buckets, datasets: [{ label: "Backlog games", data: bucketCounts, backgroundColor: hltbBucketColors, borderColor: hltbBucketColors, borderWidth: 1 }] },
    options: dashChartOptions({
      // easeOutBack overshoots the final height a hair then settles — a slight
      // bounce as each bar hits the top. Delay creates the left-to-right cascade.
      animation: { duration: hltbBarDuration, easing: "easeOutBack", delay: hltbBarDelay },
      animations: {
        y: { type: "number", duration: hltbBarDuration, easing: "easeOutBack", delay: hltbBarDelay },
      },
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
    else if (ratingValue(g) > 0) reviewBuckets.Mixed++;
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
      : '<strong> - </strong>';
    storeHeadlineEl.title = topStore[0]
      ? `Largest store share: ${DASH_STORE_LABELS[topStore[0]] || topStore[0]} (${storePct}% of library)`
      : '';
  }

  const backlogCount = games.filter(g => getPersonal(g).status === 'backlog').length;
  const statusHeadlineEl = document.getElementById('ribbonStatusHeadline');
  if (statusHeadlineEl) {
    statusHeadlineEl.innerHTML = `<strong>${escapeHtml(formatNum(backlogCount))}</strong> in backlog`;
    statusHeadlineEl.title = `${backlogCount} games marked backlog - click chart to filter`;
  }

  const positive = ['Overwhelmingly Positive', 'Very Positive', 'Mostly Positive']
    .reduce((s, k) => s + (reviewBuckets[k] || 0), 0);
  const ratedTotal = Object.entries(reviewBuckets)
    .filter(([k]) => k !== 'Unreviewed')
    .reduce((s, [, n]) => s + n, 0);
  const positivePct = ratedTotal
    ? (positive >= ratedTotal ? 100 : Math.floor(positive / ratedTotal * 100))
    : 0;
  const reviewHeadlineEl = document.getElementById('ribbonReviewHeadline');
  if (reviewHeadlineEl) {
    reviewHeadlineEl.innerHTML = `<strong>${positivePct}%</strong> positive`;
    reviewHeadlineEl.title = `${positivePct}% of rated games are Mostly Positive or better`;
  }

  const yearCounts = {};
  games.forEach(g => {
    // Use the shared robust parser (handles "Feb 11, 2026", "1998", ISO, etc.)
    // — the old release_date.slice(0,4) only kept ISO-prefixed dates, dropping
    // the vast majority of Steam titles and truncating the axis to ~2001.
    const y = parseReleaseYear(g.release_date);
    if (y != null && y >= 1990) yearCounts[y] = (yearCounts[y] || 0) + 1;
  });
  // Continuous year axis (fill gaps with 0) so the timeline and era bands span
  // every year from the oldest release through the newest — no compression.
  const presentYears = Object.keys(yearCounts).map(Number).sort((a, b) => a - b);
  const years = [];
  if (presentYears.length) {
    for (let y = presentYears[0]; y <= presentYears[presentYears.length - 1]; y++) {
      years.push(String(y));
    }
  }
  const trendData = years.map(y => yearCounts[y] || 0);
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
          borderColor: accentRgba(0.95),
          backgroundColor: accentRgba(0.18),
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.25,
          fill: true,
        },
        {
          label: "3-yr rolling avg",
          data: rolling,
          borderColor: accentRgba(0.95, '--accent-bright'),
          backgroundColor: "transparent",
          borderWidth: 2.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.4,
          borderDash: [0, 7],
          borderCapStyle: "round",
          borderJoinStyle: "round",
          fill: false,
        },
      ],
    },
    options: dashChartOptions({
      animation: { duration: 400, easing: "easeOutQuart" },
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            color: "#cbd5e1",
            boxWidth: 16,
            boxHeight: 10,
            font: { size: 11 },
            usePointStyle: true,
            // Match each marker to its line: a rounded-rect swatch for the solid
            // "Games / year" series and a round-dotted line for the rolling avg.
            generateLabels(chart) {
              const items = Chart.defaults.plugins.legend.labels.generateLabels(chart);
              for (const item of items) {
                if (item.datasetIndex === 0) {
                  item.pointStyle = "rectRounded";
                } else if (item.datasetIndex === 1) {
                  item.pointStyle = "line";
                  item.lineDash = [0, 5];
                  item.lineCap = "round";
                  item.lineWidth = 2.5;
                }
              }
              return items;
            },
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

  const scatterPts = games.filter(g => ratingValue(g) > 0 && hltbMain(g) != null && hltbMain(g) > 0).map(g => ({
    x: hltbMain(g),
    y: ratingValue(g),
    label: g.name,
    key: gameKey(g),
    status: (getPersonal(g).status) || 'backlog',
    cover: sanitizeCoverUrl(g.header_image) || libraryCoverFor(g),
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
      const grid = buildScatterSpatialGrid(px, py);
      chart._scatterGrid = grid;
      chart._scatterClusterCounts = countScatterClusters(px, py, grid);
    },
  };
  const scatterAnimReduced = prefersReducedMotion();
  const scatterAnimDuration = 1000;
  setDashboardChart("chartScatter", {
    type: "scatter",
    data: {
      datasets: [{
        label: "Games",
        data: scatterPts.map(p => ({ x: p.x, y: p.y })),
        backgroundColor: accentRgba(0.55),
        borderColor: accentRgba(0.95),
        borderWidth: 0.6,
        pointRadius: 4,
        pointHoverRadius: 7,
      }],
    },
    options: dashChartOptions({
      ...(scatterAnimReduced ? {
        animation: { duration: 0 },
        animations: {},
      } : {
        animation: { duration: scatterAnimDuration, easing: "easeOutQuart" },
        animations: {
          // Points-only entrance: each point rises from the x-axis (y) and
          // pops from r=0 (radius). The grid and axes are part of the chart
          // frame and stay still. No per-point color interpolation — that was
          // the ~3× canvas cost that chugged at scale.
          y: {
            type: "number",
            duration: scatterAnimDuration,
            easing: "easeOutQuart",
            from: (ctx) => {
              if (ctx.type !== "data") return undefined;
              const yScale = ctx.chart.scales?.y;
              return yScale ? yScale.getPixelForValue(0) : undefined;
            },
          },
          radius: {
            type: "number",
            duration: scatterAnimDuration,
            easing: "easeOutQuart",
            from: 0,
          },
        },
      }),
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
        scheduleScatterHover(evt, chart);
      },
      onClick(evt, _elements, chart) {
        const cx = evt.x ?? (evt.native?.offsetX ?? 0);
        const cy = evt.y ?? (evt.native?.offsetY ?? 0);
        const hits = hitsAtScatterClick(chart, cx, cy);
        if (!hits.length) {
          if (_scatterListFrozen) collapseScatterList();
          return;
        }
        if (hits.length === 1) {
          focusGame(hits[0].pt.key);
          return;
        }
        const key = hits.map(h => h.pt.key).join('|');
        if (_scatterListFrozen && key === _scatterListFrozenKey) {
          collapseScatterList();
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
