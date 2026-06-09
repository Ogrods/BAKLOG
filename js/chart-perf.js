/**
 * Debug-gated instrumentation for dashboard chart + hero render timing.
 * Enable: ?debug=1 or ?perf=1 in the URL, or localStorage.setItem('baklog-perf', '1')
 * Read last run: window.__baklogChartPerf.last
 */

const PERF_STORAGE_KEY = 'baklog-perf';
const MAX_HISTORY = 8;
const FRAME_BUDGET_MS = 16.7;
const JANK_FRAME_MS = 33;
/** Keep the frame monitor running past chart build so entrance animations are captured. */
const SETTLE_MS = 1500;
let _endTimer = null;

/** @type {ChartPerfRun | null} */
let _activeRun = null;
/** @type {ChartPerfRun[]} */
const _history = [];

/** @type {number | null} */
let _frameRaf = null;
/** @type {number | null} */
let _frameLastTs = null;
/** @type {((run: ChartPerfRun) => void) | null} */
let _onIdleCallback = null;

/**
 * @typedef {object} ChartPerfRun
 * @property {Record<string, unknown>} meta
 * @property {number} t0
 * @property {Record<string, number>} marks
 * @property {{ name: string, ms: number, detail?: Record<string, unknown> }[]} measures
 * @property {{ frames: number, overBudget: number, janky: number, maxGapMs: number }} frames
 * @property {number} [totalMs]
 */

export function isChartPerfEnabled() {
  if (typeof window === 'undefined') return false;
  if (window.__baklogChartPerfForce) return true;
  try {
    if (localStorage.getItem(PERF_STORAGE_KEY) === '1') return true;
  } catch (_) { /* private mode */ }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has('debug') || q.has('perf')) return true;
  } catch (_) { /* file:// */ }
  return false;
}

let _bootLogged = false;
function logBootOnce() {
  if (_bootLogged) return;
  _bootLogged = true;
  console.log(
    '%c[baklog-chart-perf] enabled%c · dashboard chart instrumentation active. '
    + 'Inspect window.__baklogChartPerf.last after a dashboard refresh.',
    'background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:3px;font-weight:600',
    'color:#94a3b8',
  );
}

/** @returns {ChartPerfRun | null} */
export function perfBeginRun(meta) {
  if (!isChartPerfEnabled()) return null;
  logBootOnce();
  const t = now();
  if (_endTimer) {
    clearTimeout(_endTimer);
    _endTimer = null;
  }
  _activeRun = {
    meta: { ...meta },
    t0: t,
    marks: { 'run:start': t },
    measures: [],
    frames: { frames: 0, overBudget: 0, janky: 0, maxGapMs: 0 },
  };
  // Expose the in-progress run immediately so a live read works mid-flight.
  if (typeof window !== 'undefined') {
    window.__baklogChartPerf = {
      enabled: true,
      last: _activeRun,
      history: _history.slice(),
      inProgress: true,
      help: 'Enable: ?perf=1 or localStorage baklog-perf=1',
    };
  }
  return _activeRun;
}

/** @param {ChartPerfRun | null} run */
export function perfMark(run, name) {
  if (!run) return;
  run.marks[name] = now();
  try { performance.mark(`baklog-chart:${name}`); } catch (_) { /* noop */ }
}

/**
 * @param {ChartPerfRun | null} run
 * @param {string} name
 * @param {string} startMark
 * @param {Record<string, unknown>} [detail]
 */
export function perfMeasure(run, name, startMark, detail) {
  if (!run || run.marks[startMark] == null) return;
  const ms = now() - run.marks[startMark];
  run.measures.push({ name, ms, detail });
  try { performance.measure(`baklog-chart:${name}`, `baklog-chart:${startMark}`); } catch (_) { /* noop */ }
}

/** @param {ChartPerfRun | null} run */
export function startFrameMonitor(run) {
  if (!run) return;
  stopFrameMonitor();
  _frameLastTs = null;
  const tick = (ts) => {
    if (_activeRun !== run) return;
    if (_frameLastTs != null) {
      const gap = ts - _frameLastTs;
      run.frames.frames++;
      if (gap > FRAME_BUDGET_MS) run.frames.overBudget++;
      if (gap > JANK_FRAME_MS) run.frames.janky++;
      if (gap > run.frames.maxGapMs) run.frames.maxGapMs = gap;
    }
    _frameLastTs = ts;
    _frameRaf = requestAnimationFrame(tick);
  };
  _frameRaf = requestAnimationFrame(tick);
}

export function stopFrameMonitor() {
  if (_frameRaf != null) {
    cancelAnimationFrame(_frameRaf);
    _frameRaf = null;
  }
  _frameLastTs = null;
}

/** Called from dashboard-charts when the visible chart build queue drains.
 *  Keeps the frame monitor running through entrance animations, then ends. */
export function notifyChartRenderIdle() {
  const run = _activeRun;
  if (!run || run.marks['queue:idle']) return;
  perfMark(run, 'queue:idle');
  if (_endTimer) clearTimeout(_endTimer);
  _endTimer = setTimeout(() => {
    _endTimer = null;
    stopFrameMonitor();
    perfEndRun(run);
  }, SETTLE_MS);
}

/** @param {(run: ChartPerfRun) => void} cb */
export function onChartRenderIdle(cb) {
  _onIdleCallback = cb;
}

/** @param {ChartPerfRun | null} run */
export function perfEndRun(run) {
  if (!run) return;
  stopFrameMonitor();
  run.totalMs = now() - run.t0;
  _history.unshift(run);
  while (_history.length > MAX_HISTORY) _history.pop();
  if (typeof window !== 'undefined') {
    window.__baklogChartPerf = {
      enabled: true,
      last: run,
      history: _history.slice(),
      help: 'Enable: ?perf=1 or localStorage baklog-perf=1',
    };
  }
  logRunSummary(run);
  if (_activeRun === run) _activeRun = null;
  try { _onIdleCallback?.(run); } catch (_) { /* noop */ }
}

export function perfActiveRun() {
  return _activeRun;
}

/** @param {string} chartId */
export function perfMarkChartBuilt(chartId) {
  const run = _activeRun;
  if (!run) return;
  if (!run.marks['chart:first']) perfMark(run, 'chart:first');
  if (chartId === 'chartScatter' && !run.marks['chart:scatter']) perfMark(run, 'chart:scatter');
}

function now() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/** @param {ChartPerfRun} run */
function logRunSummary(run) {
  const games = run.meta.gameCount ?? '?';
  const f = run.frames;
  console.groupCollapsed(
    `[baklog-chart-perf] dashboard ${run.totalMs.toFixed(1)}ms · ${games} games · `
    + `jank=${f.janky} maxFrame=${f.maxGapMs.toFixed(1)}ms`,
  );
  for (const m of run.measures) {
    const extra = m.detail ? ` ${JSON.stringify(m.detail)}` : '';
    console.log(`${m.name}: ${m.ms.toFixed(1)}ms${extra}`);
  }
  if (run.marks['chart:first']) {
    const firstMs = run.marks['chart:first'] - run.t0;
    console.log(`firstChart: ${firstMs.toFixed(1)}ms`);
  }
  if (run.marks['chart:scatter']) {
    const scatterMs = run.marks['chart:scatter'] - run.t0;
    console.log(`scatter: ${scatterMs.toFixed(1)}ms`);
  }
  console.log(
    `frames: ${f.frames} total, ${f.overBudget} over ${FRAME_BUDGET_MS}ms, `
    + `${f.janky} janky (>${JANK_FRAME_MS}ms), max gap ${f.maxGapMs.toFixed(1)}ms`,
  );
  console.groupEnd();
}

/** Compact summary for the debug overlay. */
export function readChartPerfSummary() {
  try {
    const run = window.__baklogChartPerf?.last;
    if (!run || typeof run.totalMs !== 'number') return ' - ';
    const f = run.frames || {};
    return `${run.totalMs.toFixed(0)}ms j:${f.janky ?? 0} max:${(f.maxGapMs ?? 0).toFixed(0)}`;
  } catch (_) {
    return ' - ';
  }
}
