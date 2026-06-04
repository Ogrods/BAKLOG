/**
 * Phase A instrumentation for library table paint.
 * Enable: ?debug=1 or ?perf=1 in the URL, or localStorage.setItem('baklog-perf', '1')
 * Read last run: window.__baklogPerf.last
 */

const PERF_STORAGE_KEY = 'baklog-perf';
const MAX_HISTORY = 8;

/** @type {PerfRun | null} */
let _activeRun = null;
/** @type {PerfRun[]} */
const _history = [];

/**
 * @typedef {object} PerfRun
 * @property {Record<string, unknown>} meta
 * @property {number} t0
 * @property {Record<string, number>} marks
 * @property {{ name: string, ms: number, detail?: Record<string, unknown> }[]} measures
 * @property {ChunkSample[]} chunks
 * @property {number} [totalMs]
 */

/**
 * @typedef {object} ChunkSample
 * @property {number} start
 * @property {number} end
 * @property {number} count
 * @property {string} mode
 * @property {number} htmlMs
 * @property {number} syncCoverMs
 * @property {number} totalMs
 */

export function isTablePerfEnabled() {
  if (typeof window === 'undefined') return false;
  if (window.__baklogPerfForce) return true;
  try {
    if (localStorage.getItem(PERF_STORAGE_KEY) === '1') return true;
  } catch (_) { /* private mode */ }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has('debug') || q.has('perf')) return true;
  } catch (_) { /* file:// etc. */ }
  return false;
}

let _bootLogged = false;
function logBootOnce() {
  if (_bootLogged) return;
  _bootLogged = true;
  console.log(
    '%c[baklog-perf] enabled%c · table render instrumentation will log each renderTable() with chunk timings. '
    + 'Inspect window.__baklogPerf.last anytime.',
    'background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:3px;font-weight:600',
    'color:#94a3b8',
  );
}

/** @returns {PerfRun | null} */
export function perfBeginRun(meta) {
  if (!isTablePerfEnabled()) return null;
  logBootOnce();
  const t = now();
  _activeRun = {
    meta: { ...meta },
    t0: t,
    marks: { 'run:start': t },
    measures: [],
    chunks: [],
  };
  return _activeRun;
}

/** @param {PerfRun | null} run */
export function perfMark(run, name) {
  if (!run) return;
  run.marks[name] = now();
  try { performance.mark(`baklog:${name}`); } catch (_) { /* noop */ }
}

/**
 * @param {PerfRun | null} run
 * @param {string} name
 * @param {string} startMark
 * @param {Record<string, unknown>} [detail]
 */
export function perfMeasure(run, name, startMark, detail) {
  if (!run || run.marks[startMark] == null) return;
  const ms = now() - run.marks[startMark];
  run.measures.push({ name, ms, detail });
  try { performance.measure(`baklog:${name}`, `baklog:${startMark}`); } catch (_) { /* noop */ }
}

/**
 * @param {PerfRun | null} run
 * @param {ChunkSample} sample
 */
export function perfChunk(run, sample) {
  if (!run) return;
  run.chunks.push(sample);
}

/** @param {PerfRun | null} run */
export function perfEndRun(run) {
  if (!run) return;
  run.totalMs = now() - run.t0;
  _history.unshift(run);
  while (_history.length > MAX_HISTORY) _history.pop();
  if (typeof window !== 'undefined') {
    window.__baklogPerf = {
      enabled: true,
      last: run,
      history: _history.slice(),
      help: 'Enable: ?perf=1 or localStorage baklog-perf=1. Disable: localStorage.removeItem("baklog-perf")',
    };
  }
  logRunSummary(run);
  if (_activeRun === run) _activeRun = null;
}

/** Active run for nested paint helpers (appendChunk, idle pump). */
export function perfActiveRun() {
  return _activeRun;
}

function now() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/** @param {PerfRun} run */
function logRunSummary(run) {
  const rows = run.meta.rowCount ?? '?';
  const view = run.meta.view ?? '?';
  const syncRows = run.meta.syncPaintRows ?? 0;
  const path = run.meta.paintPath ?? 'unknown';
  console.groupCollapsed(
    `[baklog-perf] renderTable ${run.totalMs.toFixed(1)}ms · ${view} · ${rows} rows · path=${path}${syncRows ? ` · syncRows=${syncRows}` : ''}`,
  );
  for (const m of run.measures) {
    const extra = m.detail ? ` ${JSON.stringify(m.detail)}` : '';
    console.log(`${m.name}: ${m.ms.toFixed(1)}ms${extra}`);
  }
  if (run.chunks.length) {
    const htmlTotal = run.chunks.reduce((s, c) => s + c.htmlMs, 0);
    const syncTotal = run.chunks.reduce((s, c) => s + c.syncCoverMs, 0);
    const rowTotal = run.chunks.reduce((s, c) => s + c.count, 0);
    console.log(
      `chunks: ${run.chunks.length}, rows painted in chunks: ${rowTotal}, `
      + `tableRowHtml build: ${htmlTotal.toFixed(1)}ms (${(htmlTotal / Math.max(rowTotal, 1)).toFixed(2)}ms/row), `
      + `syncCoverFits: ${syncTotal.toFixed(1)}ms`,
    );
    const slowChunks = [...run.chunks].sort((a, b) => b.totalMs - a.totalMs).slice(0, 5);
    console.log('slowest chunks:');
    console.table(slowChunks.map(c => ({
      mode: c.mode,
      rows: c.count,
      htmlMs: +c.htmlMs.toFixed(1),
      syncCoverMs: +c.syncCoverMs.toFixed(1),
      totalMs: +c.totalMs.toFixed(1),
      msPerRow: +(c.htmlMs / Math.max(c.count, 1)).toFixed(2),
    })));
  }
  if (syncRows >= 200) {
    console.warn(
      `[baklog-perf] Large synchronous paint (${syncRows} rows) - unexpected after Phase B; `
      + 'drill-in should use progressive+anchor with syncRows≈50 only.',
    );
  }
  const deferred = run.meta.deferredRows;
  if (deferred > 0 && run.meta.allRowsPaintedMs == null) {
    console.log(
      `[baklog-perf] Note: ${deferred} rows still painting in rAF chunks after renderTable returned `
      + `(watch for "all N rows in DOM" log).`,
    );
  }
  console.groupEnd();
}
