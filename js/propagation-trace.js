/**
 * Opt-in counters for data-arrival propagation efficiency (?debug=1 / ?perf=1).
 * Inspect: window.__baklogProp
 */

export function tracingEnabled() {
  if (typeof window === 'undefined') return false;
  try {
    if (localStorage.getItem('baklog-debug') === '1') return true;
    if (localStorage.getItem('baklog-perf') === '1') return true;
  } catch (_) { /* private mode */ }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has('debug') || q.has('perf')) return true;
  } catch (_) { /* file:// */ }
  return false;
}

function freshStats() {
  return {
    merges: 0,
    tableRenders: 0,
    tableSkips: 0,
    fetcherReloads: 0,
    downstreamSyncs: 0,
    deferredDefers: 0,
    deferredFlushes: 0,
    lastMergeKey: null,
    lastFetcherKey: null,
    lastAt: 0,
  };
}

function bucket() {
  if (!tracingEnabled()) return null;
  if (!window.__baklogProp) window.__baklogProp = freshStats();
  return window.__baklogProp;
}

/** Library merge completed (fetcher done, reload, manual reload). */
export function noteLibraryMerge(key) {
  const p = bucket();
  if (!p) return;
  p.merges += 1;
  p.lastMergeKey = key ?? null;
  p.lastAt = Date.now();
}

/** reloadAfterFetcher entered (before JSON reload). */
export function noteFetcherReload(key) {
  const p = bucket();
  if (!p) return;
  p.fetcherReloads += 1;
  p.lastFetcherKey = key ?? null;
  p.lastAt = Date.now();
}

/** scheduleDownstreamSync timer fired (personal / cross-tab apply). */
export function noteDownstreamSync() {
  const p = bucket();
  if (!p) return;
  p.downstreamSyncs += 1;
  p.lastAt = Date.now();
}

/** render-gate defer* called while active view cannot paint. */
export function noteDeferredDefer() {
  const p = bucket();
  if (!p) return;
  p.deferredDefers += 1;
  p.lastAt = Date.now();
}

/** flushDeferredRenders consumed deferred flags on a table view. */
export function noteDeferredFlush(flags) {
  const p = bucket();
  if (!p) return;
  if (flags?.table || flags?.picks || flags?.summary) {
    p.deferredFlushes += 1;
    p.lastAt = Date.now();
  }
}

/** renderTable entered (full paint path, not fingerprint skip). */
export function noteTableRender() {
  const p = bucket();
  if (!p) return;
  p.tableRenders += 1;
  p.lastAt = Date.now();
}

/** renderTable returned early on fingerprint cache hit. */
export function noteTableRenderSkipped() {
  const p = bucket();
  if (!p) return;
  p.tableSkips += 1;
  p.lastAt = Date.now();
}

export function readPropagationStats() {
  return bucket();
}

/** Test helper — reset counters without disabling tracing. */
export function resetPropagationStatsForTests() {
  if (typeof window === 'undefined') return;
  window.__baklogProp = freshStats();
}
