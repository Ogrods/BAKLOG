/**
 * Global error boundary — surfaces uncaught errors instead of silencing them.
 *
 * Until this landed, a single bad row in renderTable() or a rejected fetch
 * promise would dump to the devtools console and leave the UI frozen with no
 * user-visible signal. This module wires window.error + unhandledrejection
 * listeners that:
 *   1. Capture the error (preserving the original console.error trail; we
 *      never swallow the runtime's own logging).
 *   2. Dedupe rapid-fire repeats so a render loop firing 1000 of the same
 *      error doesn't produce 1000 toasts.
 *   3. Show a sticky toast (no auto-dismiss — errors are not ephemeral) in
 *      the top-right with the latest message, an error count, and buttons to
 *      copy the full error list / expand the stack inline / dismiss for now.
 *   4. Stash the recent error log on window.__baklogErrors so the debug
 *      overlay and bug reports can introspect it.
 *
 * Public API:
 *   - installGlobalErrorHandler() — call once at module top-level in app.js.
 *   - reportError(err, opts?) — opt-in for modules with their own try/catch.
 *   - getErrorCount() — used by the debug overlay to surface a non-zero count.
 */

const MAX_CAPTURED = 50;
const DEDUPE_WINDOW_MS = 2000;
const MESSAGE_TRUNCATE = 240;

let _installed = false;
let _toastEl = null;
let _detailsOpen = false;
let _dismissed = false;
const _errors = [];
const _signatures = new Map(); // sig -> last seen timestamp

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function makeSignature(entry) {
  const firstStackLine = (entry.stack || '').split('\n').slice(0, 2).join('|');
  return `${entry.kind}::${entry.message}::${firstStackLine}`;
}

function captureFromErrorEvent(e) {
  // Browser fires this for uncaught throws + script-load errors. e.error is the
  // real Error when available; falling back to message/filename keeps us
  // useful even when CORS strips the object (e.g. third-party scripts).
  const err = e.error;
  return {
    kind: 'error',
    time: Date.now(),
    message: err?.message || e.message || String(err) || 'Unknown error',
    stack: err?.stack || '',
    source: e.filename || '',
    lineno: e.lineno || 0,
    colno: e.colno || 0,
    name: err?.name || 'Error',
  };
}

function captureFromRejectionEvent(e) {
  const reason = e.reason;
  const isErr = reason instanceof Error;
  return {
    kind: 'unhandledrejection',
    time: Date.now(),
    message: isErr ? reason.message : (typeof reason === 'string' ? reason : safeStringify(reason)),
    stack: isErr ? (reason.stack || '') : '',
    source: '',
    lineno: 0,
    colno: 0,
    name: isErr ? reason.name : 'UnhandledRejection',
  };
}

function safeStringify(v) {
  try { return JSON.stringify(v); } catch (_) { return String(v); }
}

function shouldDedupe(entry) {
  const sig = makeSignature(entry);
  const now = entry.time;
  const last = _signatures.get(sig);
  _signatures.set(sig, now);
  // Periodic prune so the map doesn't grow forever in a long session.
  if (_signatures.size > 200) {
    for (const [k, t] of _signatures) {
      if (now - t > 60_000) _signatures.delete(k);
    }
  }
  return last != null && now - last < DEDUPE_WINDOW_MS;
}

function publishToWindow() {
  if (typeof window === 'undefined') return;
  window.__baklogErrors = {
    count: _errors.length,
    items: _errors.slice(),
    help: 'Uncaught errors + unhandled rejections captured this session. Cleared on reload.',
  };
}

function buildToast() {
  const el = document.createElement('div');
  el.id = 'errorToast';
  el.className = 'baklog-error-toast';
  el.setAttribute('role', 'alert');
  el.setAttribute('aria-live', 'assertive');
  el.innerHTML = `
    <div class="baklog-error-toast-head">
      <span class="baklog-error-toast-icon" aria-hidden="true">!</span>
      <span class="baklog-error-toast-title">Error</span>
      <span class="baklog-error-toast-count" data-field="count">1</span>
      <button type="button" class="baklog-error-toast-dismiss" data-action="dismiss" aria-label="Dismiss">×</button>
    </div>
    <div class="baklog-error-toast-body">
      <div class="baklog-error-toast-message" data-field="message"></div>
      <div class="baklog-error-toast-source" data-field="source"></div>
    </div>
    <div class="baklog-error-toast-details" data-field="details" hidden>
      <pre class="baklog-error-toast-stack" data-field="stack"></pre>
    </div>
    <div class="baklog-error-toast-foot">
      <button type="button" class="baklog-error-toast-btn" data-action="copy" title="Copy error log as JSON">Copy</button>
      <button type="button" class="baklog-error-toast-btn" data-action="toggle-details">Details</button>
    </div>
  `;
  el.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === 'dismiss') {
      hideToast();
      _dismissed = true;
    } else if (action === 'copy') {
      copyErrorLog(btn);
    } else if (action === 'toggle-details') {
      _detailsOpen = !_detailsOpen;
      const details = el.querySelector('[data-field="details"]');
      if (details) details.hidden = !_detailsOpen;
      btn.textContent = _detailsOpen ? 'Hide details' : 'Details';
    }
  });
  return el;
}

function hideToast() {
  _toastEl?.remove();
  _toastEl = null;
  _detailsOpen = false;
}

function showOrUpdateToast() {
  if (_dismissed) return;
  if (typeof document === 'undefined' || !document.body) return;
  if (!_toastEl) {
    _toastEl = buildToast();
    document.body.appendChild(_toastEl);
  }
  const latest = _errors[_errors.length - 1];
  if (!latest) return;
  const setField = (name, text) => {
    const node = _toastEl.querySelector(`[data-field="${name}"]`);
    if (node) node.textContent = text;
  };
  const msg = latest.message.length > MESSAGE_TRUNCATE
    ? latest.message.slice(0, MESSAGE_TRUNCATE) + '…'
    : latest.message;
  setField('count', String(_errors.length));
  setField('message', `${latest.name}: ${msg}`);
  const sourceParts = [];
  if (latest.source) {
    const short = latest.source.replace(/^.*\//, '');
    sourceParts.push(latest.lineno ? `${short}:${latest.lineno}` : short);
  }
  if (latest.kind === 'unhandledrejection') sourceParts.unshift('unhandledrejection');
  setField('source', sourceParts.join(' · '));
  const stackNode = _toastEl.querySelector('[data-field="stack"]');
  if (stackNode) stackNode.textContent = latest.stack || '(no stack available)';
}

function copyErrorLog(btn) {
  const payload = JSON.stringify(_errors, null, 2);
  const finish = (ok) => {
    if (!btn) return;
    const original = btn.textContent;
    btn.textContent = ok ? 'Copied' : 'Copy failed';
    setTimeout(() => { if (btn.textContent !== original) btn.textContent = original; }, 1400);
  };
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(payload).then(() => finish(true), () => finish(false));
      return;
    }
  } catch (_) { /* fall through */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = payload;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    finish(ok);
  } catch (_) { finish(false); }
}

function record(entry) {
  if (shouldDedupe(entry)) return;
  _errors.push(entry);
  while (_errors.length > MAX_CAPTURED) _errors.shift();
  publishToWindow();
  showOrUpdateToast();
}

/**
 * Install the global error + unhandledrejection listeners.
 * Idempotent — safe to call more than once.
 */
export function installGlobalErrorHandler() {
  if (_installed || typeof window === 'undefined') return;
  _installed = true;
  window.addEventListener('error', (e) => {
    try {
      record(captureFromErrorEvent(e));
    } catch (_) { /* never let the handler itself throw */ }
  });
  window.addEventListener('unhandledrejection', (e) => {
    try {
      record(captureFromRejectionEvent(e));
    } catch (_) { /* never let the handler itself throw */ }
  });
  publishToWindow();
}

/**
 * Report an error explicitly (for try/catch sites that don't rethrow).
 * @param {unknown} err
 * @param {{ source?: string, kind?: string }} [opts]
 */
export function reportError(err, opts = {}) {
  const isErr = err instanceof Error;
  const entry = {
    kind: opts.kind || 'reported',
    time: Date.now(),
    message: isErr ? err.message : (typeof err === 'string' ? err : safeStringify(err)),
    stack: isErr ? (err.stack || '') : '',
    source: opts.source || '',
    lineno: 0,
    colno: 0,
    name: isErr ? err.name : 'ReportedError',
  };
  record(entry);
}

/** Latest error count — used by the debug overlay. */
export function getErrorCount() { return _errors.length; }

/** All captured errors (cloned, so callers can safely mutate). */
export function getCapturedErrors() { return _errors.slice(); }

// Test helper — not part of the public contract.
export function _resetForTests() {
  _errors.length = 0;
  _signatures.clear();
  _dismissed = false;
  hideToast();
  publishToWindow();
}
