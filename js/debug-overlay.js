/**
 * Lightweight runtime introspection overlay.
 *
 * Enable with `?debug=1` in the URL or `localStorage.setItem('baklog-debug', '1')`.
 * Shows a tiny corner panel with: current view, data version, visible row count,
 * active filter count, table fingerprint (truncated), last renderTable() ms.
 *
 * Replaces ad-hoc console.log spelunking for the most common questions:
 * "is the data version bumping?" / "is the fingerprint changing?" /
 * "how slow was the last render?" / "is a filter still applied?".
 *
 * Implementation note: polls state every 1000ms instead of hooking into every
 * mutation site. Cheap (one DOM update, no layout thrash because the panel is
 * position:fixed), durable (no need to remember to call a refresh from new
 * code paths), and the overlay is opt-in so the cost only applies to debug
 * sessions.
 */

import { state } from './state.js';
import { tableFingerprint } from './table-ui.js';
import { collectActiveFilters } from './filters-ui.js';
import { getErrorCount } from './error-boundary.js';
import { getCurtainState } from './loading-curtain.js';
import { countOrphanPersonalKeys } from './personal-storage.js';

const STORAGE_KEY = 'baklog-debug';
const POLL_INTERVAL_MS = 1000;
const FINGERPRINT_DISPLAY_LEN = 28;

let _overlayEl = null;
let _pollTimer = null;

export function isDebugEnabled() {
  if (typeof window === 'undefined') return false;
  try {
    if (localStorage.getItem(STORAGE_KEY) === '1') return true;
  } catch (_) { /* private mode */ }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has('debug')) return true;
  } catch (_) { /* file:// */ }
  return false;
}

function buildOverlay() {
  const el = document.createElement('div');
  el.id = 'baklogDebugOverlay';
  el.className = 'baklog-debug-overlay';
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `
    <div class="baklog-debug-overlay-head">
      <span class="baklog-debug-overlay-title">baklog · debug</span>
      <button type="button" class="baklog-debug-overlay-close" title="Hide overlay (refresh to show again)">×</button>
    </div>
    <dl class="baklog-debug-overlay-rows">
      <dt>view</dt><dd data-field="view">—</dd>
      <dt>dataVer</dt><dd data-field="dataVer">—</dd>
      <dt>visible</dt><dd data-field="visible">—</dd>
      <dt>filters</dt><dd data-field="filters">—</dd>
      <dt>fp</dt><dd data-field="fp" title="">—</dd>
      <dt>render</dt><dd data-field="render">—</dd>
      <dt>dash</dt><dd data-field="dash" title="full / replay / skipped (reentrant+cooldown)">—</dd>
      <dt>curtain</dt><dd data-field="curtain" title="boot data-boot-loading + view overlay">—</dd>
      <dt>errors</dt><dd data-field="errors">—</dd>
      <dt>orphans</dt><dd data-field="orphans" title="state.personal keys with no matching game in any catalog. Surfaced read-only; clean up via kebab → Clean up unknown games.">—</dd>
    </dl>
    <div class="baklog-debug-overlay-foot">?debug=1 · <code>localStorage.removeItem('${STORAGE_KEY}')</code></div>
  `;
  el.querySelector('.baklog-debug-overlay-close')?.addEventListener('click', () => {
    el.classList.add('baklog-debug-overlay--hidden');
  });
  return el;
}

function setField(name, value, opts) {
  if (!_overlayEl) return;
  const node = _overlayEl.querySelector(`[data-field="${name}"]`);
  if (!node) return;
  const next = value == null ? '—' : String(value);
  if (node.textContent !== next) node.textContent = next;
  if (opts?.title != null && node.title !== opts.title) node.title = opts.title;
}

function readFingerprint() {
  try { return tableFingerprint(); } catch (_) { return ''; }
}

function readActiveFilterCount() {
  try { return collectActiveFilters().length; } catch (_) { return 0; }
}

function readLastRenderMs() {
  try {
    const t = window.__baklogPerf?.last?.totalMs;
    return typeof t === 'number' ? `${t.toFixed(1)}ms` : '—';
  } catch (_) { return '—'; }
}

function tick() {
  if (!_overlayEl) return;
  setField('view', state.activeView || '—');
  setField('dataVer', window._dataVersion ?? '—');
  setField('visible', state._visibleList?.length ?? '—');
  setField('filters', readActiveFilterCount());
  const fp = readFingerprint();
  const shortFp = fp.length > FINGERPRINT_DISPLAY_LEN
    ? `${fp.slice(0, FINGERPRINT_DISPLAY_LEN)}…`
    : (fp || '—');
  setField('fp', shortFp, { title: fp });
  setField('render', readLastRenderMs());
  setField('dash', readDashStats());
  setField('curtain', readCurtainState());
  const errCount = getErrorCount();
  setField('errors', errCount > 0 ? `${errCount} (see window.__baklogErrors)` : '0');
  if (!_overlayEl.classList.contains('baklog-debug-overlay--hidden')) {
    setField('orphans', readOrphanCount());
  } else {
    setField('orphans', '—');
  }
}

function readOrphanCount() {
  try {
    if (!state.dashboardDataReady) return 'waiting…';
    return String(countOrphanPersonalKeys());
  } catch (_) {
    return '—';
  }
}

/**
 * Compact dashboard-render counters. Format: "F:1 R:0 S:0" where F=full
 * renders, R=animation replays (explicit dashboard tab revisit only), S=
 * suppressed (re-entrant + auto-replay blocked — boot schedules should bump
 * skippedAutoReplay, not R).
 */
function readDashStats() {
  const s = (typeof window !== "undefined" && window.__baklogDash?.stats) || null;
  if (!s) return "—";
  const skipped = (s.skippedReentrant || 0) + (s.skippedAutoReplay || 0);
  return `F:${s.full} R:${s.replay} S:${skipped}`;
}

function readCurtainState() {
  try {
    const c = getCurtainState();
    const boot =
      c.bootReason != null
        ? `${c.bootReason}${c.bootElapsedMs != null ? ` ${c.bootElapsedMs}ms` : ""}`
        : "—";
    const view = c.viewOverlayShown
      ? (c.viewOverlayLabel || "on")
      : "—";
    return `boot:${boot} · view:${view}`;
  } catch (_) {
    return "—";
  }
}

/**
 * Mount the overlay and start polling.
 * No-op when debug is not enabled, when already mounted, or when document.body
 * isn't ready yet (caller should run this after DOMContentLoaded / bootstrap).
 */
export function startDebugOverlay() {
  if (!isDebugEnabled()) return;
  if (_overlayEl || typeof document === 'undefined' || !document.body) return;
  _overlayEl = buildOverlay();
  document.body.appendChild(_overlayEl);
  tick();
  _pollTimer = setInterval(tick, POLL_INTERVAL_MS);
  console.log(
    '%c[baklog-debug] overlay enabled%c · disable with localStorage.removeItem("' + STORAGE_KEY + '") or remove ?debug=1',
    'background:#0ea5e9;color:#fff;padding:2px 6px;border-radius:3px;font-weight:600',
    'color:#94a3b8',
  );
}

export function stopDebugOverlay() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = null;
  _overlayEl?.remove();
  _overlayEl = null;
}
