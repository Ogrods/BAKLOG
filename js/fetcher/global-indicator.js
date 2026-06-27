/** Global fetcher status pill + streaming tail helpers. */
import { fetchSuccessLabels, lastRunFailedByKey } from '../fetcher-health-shared.js';
import { primaryFailureNavigateTarget } from './reconnect.js';

const GLOBAL_FETCHER_TAIL_CAP = 80;
const GLOBAL_FETCHER_TAIL_THROTTLE_MS = 200;
let globalTailPending = null;
let globalTailTimer = null;
let globalTailLastApply = 0;

function cancelGlobalFetcherTailThrottle() {
  globalTailPending = null;
  globalTailLastApply = 0;
  if (globalTailTimer) {
    clearTimeout(globalTailTimer);
    globalTailTimer = null;
  }
}

/** Semantic pill states. Exactly one is applied at a time so the active state
 *  is never the faint "base" look (which read as grey). */
const PILL_STATE_CLASSES = [
  'fh-global-status-idle',
  'fh-global-status-queued',
  'fh-global-status-running',
  'fh-global-status-done',
  'fh-global-status-failed',
];

function setPillState(el, state) {
  el.classList.remove('hidden', ...PILL_STATE_CLASSES);
  el.classList.add(`fh-global-status-${state}`);
}

function prefersReducedMotion() {
  return typeof matchMedia === 'function'
    && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** The tail holds its text in an inner span so it can be marquee-scrolled when
 *  the message overflows the reserved width without disturbing the clip box. */
function tailInner(tailEl, create = false) {
  let inner = tailEl.querySelector('.fh-global-status-tail-inner');
  if (!inner && create) {
    inner = document.createElement('span');
    inner.className = 'fh-global-status-tail-inner';
    tailEl.appendChild(inner);
  }
  return inner;
}

function clearGlobalFetcherTail(tailEl) {
  if (!tailEl) return;
  tailEl.textContent = '';
  tailEl.classList.remove('fh-global-status-tail--err', 'is-scrolling');
  tailEl.style.removeProperty('--tail-scroll-shift');
  tailEl.style.removeProperty('--tail-scroll-dur');
}

/** Add/refresh the scroll marquee when the message is wider than the clip box. */
function updateTailScroll(tailEl, inner) {
  if (prefersReducedMotion()) {
    tailEl.classList.remove('is-scrolling');
    tailEl.style.removeProperty('--tail-scroll-shift');
    tailEl.style.removeProperty('--tail-scroll-dur');
    return;
  }
  const shift = inner.scrollWidth - tailEl.clientWidth;
  if (shift > 4) {
    const travel = shift + 12;
    tailEl.style.setProperty('--tail-scroll-shift', `${travel}px`);
    // ~40px/sec each way; doubled for the alternate return trip; min 4s.
    tailEl.style.setProperty('--tail-scroll-dur', `${Math.max(4, (travel / 40) * 2).toFixed(1)}s`);
    tailEl.classList.add('is-scrolling');
  } else {
    tailEl.classList.remove('is-scrolling');
    tailEl.style.removeProperty('--tail-scroll-shift');
    tailEl.style.removeProperty('--tail-scroll-dur');
  }
}

function applyGlobalFetcherTail(text, kind = 'stdout') {
  const el = document.getElementById('fetcherGlobalStatus');
  const tailEl = document.getElementById('fetcherGlobalStatusTail');
  if (!el || !tailEl || !el.classList.contains('fh-global-status-running')) return;
  const line = String(text ?? '').trim();
  if (!line) return;
  const capped = line.length > GLOBAL_FETCHER_TAIL_CAP
    ? `${line.slice(0, GLOBAL_FETCHER_TAIL_CAP - 1)}…`
    : line;
  el.classList.add('is-streaming');
  const inner = tailInner(tailEl, true);
  const changed = inner.textContent !== capped;
  inner.textContent = capped;
  tailEl.classList.toggle('fh-global-status-tail--err', kind === 'stderr');
  const reducedMotion = prefersReducedMotion();
  if (changed && !reducedMotion && typeof inner.animate === 'function') {
    inner.animate(
      [{ opacity: 0.35 }, { opacity: 0.8 }],
      { duration: 180, easing: 'ease-out', fill: 'forwards' },
    );
  }
  if (changed) {
    const measure = () => updateTailScroll(tailEl, inner);
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(measure);
    else measure();
  }
}

export function setGlobalFetcherTail(text, kind = 'stdout') {
  const el = document.getElementById('fetcherGlobalStatus');
  const tailEl = document.getElementById('fetcherGlobalStatusTail');
  if (!el || !tailEl || !el.classList.contains('fh-global-status-running')) return;
  const line = String(text ?? '').trim();
  if (!line) return;

  el.classList.add('is-streaming');
  globalTailPending = { text: line, kind };
  const now = Date.now();
  const elapsed = now - globalTailLastApply;

  const flush = () => {
    if (!globalTailPending) return;
    const { text: pendingText, kind: pendingKind } = globalTailPending;
    globalTailPending = null;
    globalTailTimer = null;
    globalTailLastApply = Date.now();
    applyGlobalFetcherTail(pendingText, pendingKind);
  };

  if (elapsed >= GLOBAL_FETCHER_TAIL_THROTTLE_MS) {
    if (globalTailTimer) {
      clearTimeout(globalTailTimer);
      globalTailTimer = null;
    }
    flush();
  } else if (!globalTailTimer) {
    globalTailTimer = setTimeout(flush, GLOBAL_FETCHER_TAIL_THROTTLE_MS - elapsed);
  }
}

export function updateGlobalFetcherIndicator(runStateByKey, sourceFn) {
  const el = document.getElementById('fetcherGlobalStatus');
  if (!el) return;
  const textEl = document.getElementById('fetcherGlobalStatusText');
  const liveEl = document.getElementById('fetcherGlobalStatusLive');
  const tailEl = document.getElementById('fetcherGlobalStatusTail');
  const running = [];
  const queued = [];
  for (const [key, st] of runStateByKey) {
    const src = sourceFn(key);
    const label = src?.label || key;
    if (st === 'running') running.push(label);
    else if (st === 'queued') queued.push(label);
  }
  if (!running.length && !queued.length) {
    // Failed takes precedence over done: a broken run is the most important
    // thing to surface. lastRunFailedByKey is sticky until that source's next
    // success or the next run starts, mirroring the per-chip failed styling.
    const failedKeys = [...lastRunFailedByKey.keys()];
    if (failedKeys.length > 0) {
      const labels = failedKeys.map(k => sourceFn(k)?.label || k);
      const text = labels.length === 1
        ? `✕ ${labels[0]} failed`
        : `✕ ${labels.join(', ')} failed`;
      setPillState(el, 'failed');
      el.classList.remove('is-streaming');
      if (textEl) textEl.textContent = text;
      if (liveEl) liveEl.textContent = text;
      clearGlobalFetcherTail(tailEl);
      cancelGlobalFetcherTailThrottle();
      const navTarget = primaryFailureNavigateTarget();
      if (navTarget) {
        el.dataset.fetcherConnect = navTarget.provider;
        el.title = 'Click to fix in Connections (Shift+click for log)';
        el.setAttribute('aria-label', `${text} - click to fix in Connections`);
      } else {
        delete el.dataset.fetcherConnect;
        el.title = 'A fetcher failed - click to view the log';
        el.setAttribute('aria-label', text);
      }
      return;
    }
    if (fetchSuccessLabels.size > 0) {
      const labels = [...fetchSuccessLabels];
      const text = labels.length === 1
        ? `✓ ${labels[0]} updated`
        : `✓ ${labels.join(', ')} updated`;
      setPillState(el, 'done');
      el.classList.remove('is-streaming');
      if (textEl) textEl.textContent = text;
      if (liveEl) liveEl.textContent = text;
      clearGlobalFetcherTail(tailEl);
      cancelGlobalFetcherTailThrottle();
      el.title = 'Fetch complete - click to view log';
      el.setAttribute('aria-label', text);
      return;
    }
    // Stay visible as an idle affordance so the console is always reachable,
    // not only while a run is in flight.
    setPillState(el, 'idle');
    el.classList.remove('is-streaming');
    if (textEl) textEl.textContent = 'Fetcher log';
    if (liveEl) liveEl.textContent = '';
    clearGlobalFetcherTail(tailEl);
    cancelGlobalFetcherTailThrottle();
    el.title = 'Show fetcher log';
    el.setAttribute('aria-label', 'Fetcher log');
    return;
  }
  let text;
  if (running.length) {
    setPillState(el, 'running');
    const extra = queued.length ? ` (+${queued.length} queued)` : '';
    text = `Fetching: ${running.join(', ')}${extra}`;
  } else {
    setPillState(el, 'queued');
    text = `Queued: ${queued.join(', ')}`;
  }
  if (textEl) textEl.textContent = text;
  if (liveEl) liveEl.textContent = text;
  el.title = `${text} - click to show log`;
  el.setAttribute('aria-label', text);
}
