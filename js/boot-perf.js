/**
 * Boot-phase timing marks (?perf=1 / localStorage baklog-perf=1).
 * Read: window.__baklogBootPerf.last
 */

const PERF_STORAGE_KEY = 'baklog-perf';
const MAX_HISTORY = 8;

/** @type {BootPerfRun | null} */
let _active = null;
/** @type {BootPerfRun[]} */
const _history = [];

/**
 * @typedef {object} BootPerfRun
 * @property {number} t0
 * @property {Record<string, number>} marks
 * @property {{ name: string, ms: number }[]} measures
 * @property {number} [totalMs]
 */

export function isBootPerfEnabled() {
  if (typeof window === 'undefined') return false;
  if (window.__baklogBootPerfForce) return true;
  try {
    if (localStorage.getItem(PERF_STORAGE_KEY) === '1') return true;
  } catch (_) { /* private mode */ }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has('debug') || q.has('perf')) return true;
  } catch (_) { /* file:// */ }
  return false;
}

function now() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

export function bootPerfBegin() {
  if (!isBootPerfEnabled()) return null;
  _active = { t0: now(), marks: { start: now() }, measures: [] };
  if (typeof window !== 'undefined') {
    window.__baklogBootPerf = { enabled: true, last: _active, history: _history.slice() };
  }
  return _active;
}

/** @param {BootPerfRun | null} run @param {string} name */
export function bootPerfMark(run, name) {
  if (!run) return;
  run.marks[name] = now();
  try { performance.mark(`baklog-boot:${name}`); } catch (_) { /* noop */ }
}

/**
 * @param {BootPerfRun | null} run
 * @param {string} name
 * @param {string} startMark
 */
export function bootPerfMeasure(run, name, startMark) {
  if (!run || run.marks[startMark] == null) return;
  const ms = now() - run.marks[startMark];
  run.measures.push({ name, ms });
  try { performance.measure(`baklog-boot:${name}`, `baklog-boot:${startMark}`); } catch (_) { /* noop */ }
}

/** @param {BootPerfRun | null} run */
export function bootPerfEnd(run) {
  if (!run) return;
  run.totalMs = now() - run.t0;
  run.marks.end = now();
  _history.unshift(run);
  while (_history.length > MAX_HISTORY) _history.pop();
  if (typeof window !== 'undefined') {
    window.__baklogBootPerf = {
      enabled: true,
      last: run,
      history: _history.slice(),
      help: 'Enable: ?perf=1 or localStorage baklog-perf=1',
    };
  }
  if (_active === run) _active = null;
}
