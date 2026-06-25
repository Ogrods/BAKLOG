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
 *   - buildBugBundle() — assembles a sanitized JSON payload (errors + app
 *     context) that the "Copy bug bundle" button writes to the clipboard.
 *   - registerBugBundleContext({ getFingerprint, getActiveFilterCount }) —
 *     app.js wires this once after table-ui/filters-ui are loaded; lets the
 *     bundle include the live table fingerprint and filter count without
 *     forcing error-boundary.js to import those modules at boot.
 *
 * Persistence:
 *   The session error list (_errors) is small (50 entries, drops on reload).
 *   We also mirror every recorded entry into a localStorage-backed ring
 *   (PERSIST_STORAGE_KEY, MAX_PERSISTED=200) so bug bundles can include
 *   history across reloads. Nothing is sent anywhere — the only way the log
 *   leaves your machine is the "Copy bug bundle" button you click yourself.
 */

const MAX_CAPTURED = 50;
const MAX_PERSISTED = 200; // localStorage ring — survives reloads for bug bundles
const MAX_PERSIST_STACK_LEN = 4096; // cap persisted stacks so the ring stays under quota
const DEDUPE_WINDOW_MS = 2000;
const MESSAGE_TRUNCATE = 240;
const UA_TRUNCATE = 256; // avoid leaking absurd UA-spoofing strings into bundles
const PERSIST_STORAGE_KEY = 'baklog-error-log';
const PERSIST_STACK_TRUNCATED = '\n(... truncated for storage)';

let _installed = false;
let _toastEl = null;
let _detailsOpen = false;
let _dismissed = false;
let _persistedRing = []; // larger than _errors so bundles can include history across reloads
let _bundleCtx = null; // { getFingerprint, getActiveFilterCount } — injected by app.js
const _errors = [];
const _signatures = new Map(); // sig -> last seen timestamp

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

/** Benign browser noise — never toast, persist, or include in bug bundles. */
function isIgnoredError(entry) {
  const msg = String(entry?.message || '');
  return /ResizeObserver loop completed with undelivered notifications/i.test(msg);
}

/**
 * Lazy-chunk fetch failure — the esbuild `dist/` bundle was rebuilt (new chunk
 * hashes) while this tab stayed open, so a hashed chunk URL the running build
 * references via `import('./x.js')` no longer exists on disk. It's not a code
 * bug; the fix is to reload onto the fresh build (see reloadForStaleChunkOnce).
 */
function isStaleChunkError(entry) {
  const msg = String(entry?.message || '');
  return /Failed to (?:fetch|load) dynamically imported module|error loading dynamically imported module|Importing a module script failed/i.test(msg);
}

const STALE_CHUNK_RELOAD_KEY = 'baklog-stale-chunk-reload';
const STALE_CHUNK_RELOAD_WINDOW_MS = 30_000;

/**
 * Reload the tab once onto the freshly-built bundle. Guarded by a sessionStorage
 * timestamp so a chunk that is genuinely missing (still 404s after the reload)
 * surfaces as a real error instead of trapping the tab in a reload loop.
 * @returns {boolean} true if a reload was scheduled (caller should swallow the error)
 */
function reloadForStaleChunkOnce() {
  if (typeof window === 'undefined') return false;
  let last = 0;
  try { last = Number(window.sessionStorage?.getItem(STALE_CHUNK_RELOAD_KEY)) || 0; } catch (_) { /* disabled storage */ }
  if (Date.now() - last < STALE_CHUNK_RELOAD_WINDOW_MS) return false;
  try { window.sessionStorage?.setItem(STALE_CHUNK_RELOAD_KEY, String(Date.now())); } catch (_) { /* best-effort */ }
  window.setTimeout(() => { try { window.location.reload(); } catch (_) { /* noop */ } }, 150);
  return true;
}

/**
 * Historical entries to drop when rehydrating localStorage (fixed bugs / ignored noise).
 * New captures for non-ignored messages are unaffected so regressions still surface.
 */
function isStalePersistedError(entry) {
  if (isIgnoredError(entry)) return true;
  // Transient stale-build artifacts — a reload clears them, so they shouldn't
  // linger in bug bundles as if they were live defects.
  if (isStaleChunkError(entry)) return true;
  const msg = String(entry?.message || '');
  return msg === 'authStatus is not defined'
    || msg === 'enableLocalProvider is not defined'
    || msg === 'lastBarSummary is not defined'
    || msg === 'eff is not defined'
    || msg === 'cancelGlobalFetcherTailThrottle is not defined'
    || msg === 'itadPendingAutoRun is not defined'
    || msg === 'queue wait timeout';
}

function prunePersistedRing() {
  const before = _persistedRing.length;
  _persistedRing = _persistedRing.filter(e => !isStalePersistedError(e));
  if (_persistedRing.length === before || typeof window === 'undefined') return;
  try {
    window.localStorage?.setItem(PERSIST_STORAGE_KEY, JSON.stringify(_persistedRing));
  } catch (_) { /* best-effort */ }
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
    persisted: _persistedRing.slice(),
    help: 'Uncaught errors + unhandled rejections. Session items live in items[]; the persisted ring (last 200 across reloads) lives in persisted[].',
  };
}

/**
 * Restore the persisted ring from localStorage. Best-effort — corrupt JSON or
 * disabled storage is silently ignored so the live capture path is never blocked.
 */
function loadPersistedErrors() {
  if (typeof window === 'undefined') return;
  try {
    const raw = window.localStorage?.getItem(PERSIST_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      _persistedRing = parsed.slice(-MAX_PERSISTED);
      prunePersistedRing();
    }
  } catch (_) { /* corrupt or disabled storage — start fresh */ }
}

/**
 * Append the most recent entry to the persisted ring + write. Synchronous +
 * tiny because error rate is bounded by the dedupe window (max ~30/min in the
 * pathological case).
 */
function persistError(entry) {
  if (typeof window === 'undefined') return;
  _persistedRing.push(entryForStorage(entry));
  while (_persistedRing.length > MAX_PERSISTED) _persistedRing.shift();
  try {
    window.localStorage?.setItem(PERSIST_STORAGE_KEY, JSON.stringify(_persistedRing));
  } catch (_) { /* quota / disabled / private mode — bundle still works from in-memory _persistedRing */ }
}

/** Clone an entry for the persisted ring — truncate stacks, default repeats. */
function entryForStorage(entry) {
  const stored = { ...entry };
  if (typeof stored.message === 'string') stored.message = scrubErrorText(stored.message);
  if (typeof stored.stack === 'string') {
    stored.stack = scrubErrorText(stored.stack);
  }
  if (typeof stored.stack === 'string' && stored.stack.length > MAX_PERSIST_STACK_LEN) {
    stored.stack = stored.stack.slice(0, MAX_PERSIST_STACK_LEN) + PERSIST_STACK_TRUNCATED;
  }
  if (!stored.repeats) stored.repeats = 1;
  return stored;
}

function bumpRepeatsForSignature(sig) {
  for (let i = _errors.length - 1; i >= 0; i -= 1) {
    if (makeSignature(_errors[i]) !== sig) continue;
    _errors[i].repeats = (_errors[i].repeats || 1) + 1;
    for (let j = _persistedRing.length - 1; j >= 0; j -= 1) {
      if (makeSignature(_persistedRing[j]) !== sig) continue;
      _persistedRing[j].repeats = (_persistedRing[j].repeats || 1) + 1;
      try {
        window.localStorage?.setItem(PERSIST_STORAGE_KEY, JSON.stringify(_persistedRing));
      } catch (_) { /* best-effort */ }
      return;
    }
    return;
  }
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
      <button type="button" class="baklog-error-toast-btn" data-action="send-report" aria-label="Send a bug report" title="Open the report dialog to review and send this bug bundle. Nothing is sent until you confirm.">Send report</button>
      <button type="button" class="baklog-error-toast-btn" data-action="copy-bundle" aria-label="Copy a sanitized bug bundle to the clipboard" title="Copy a JSON bug bundle (errors + app context) to your clipboard so you can paste it into a GitHub issue. Nothing is sent anywhere - what you do with the clipboard is up to you.">Copy bug bundle</button>
      <button type="button" class="baklog-error-toast-btn" data-action="copy" title="Copy just the error list as JSON">Errors only</button>
      <button type="button" class="baklog-error-toast-btn" data-action="toggle-details" aria-label="Toggle error details">Details</button>
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
    } else if (action === 'copy-bundle') {
      copyBugBundle(btn);
    } else if (action === 'send-report') {
      window.dispatchEvent(new CustomEvent('baklog:open-bug-report'));
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
  setField('count', latest.repeats > 1
    ? `${_errors.length} (×${latest.repeats} repeats)`
    : String(_errors.length));
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
  copyTextToClipboard(JSON.stringify(_errors, null, 2), btn);
}

/**
 * Build a sanitized bug-bundle payload. Whitelist-only — nothing makes it in
 * unless we explicitly add it here, so personal notes / library JSON /
 * credentials can never leak by accident.
 *
 * What's included:
 *   - app + ua context (version, generated_at, user-agent)
 *   - current view + data version + active filter count
 *   - opaque tableFingerprint (no row contents, just a stable hash-shaped string)
 *   - last renderTable timing
 *   - dashboard render stats counter
 *   - error list (in-memory session + persisted ring, with stack traces)
 *
 * What's deliberately NOT included:
 *   - state.personal / notes / statuses
 *   - state.manualGames / library contents / state.gamesBySource
 *   - localStorage contents (besides the error ring, which we own)
 *   - credentials / .env values / cookies
 */
export function buildBugBundle(extra = {}) {
  const win = (typeof window !== 'undefined') ? window : null;
  const doc = (typeof document !== 'undefined') ? document : null;
  const versionMeta = doc?.querySelector('meta[name="baklog-version"]');
  const appVersion = versionMeta?.getAttribute('content') || 'unknown';
  const ua = (win?.navigator?.userAgent || '').slice(0, UA_TRUNCATE);
  const dataVersion = (win && '_dataVersion' in win) ? win._dataVersion : null;
  const perf = win?.__baklogPerf?.last || null;
  const dashStats = win?.__baklogDash?.stats || null;
  return {
    bundle: 'baklog-bug-bundle',
    bundle_version: 2,
    app_version: appVersion,
    generated_at: new Date().toISOString(),
    ua,
    runtime: {
      view: safeActiveView(),
      data_version: dataVersion,
      active_filter_count: safeCount(),
      table_fingerprint: safeFingerprint(),
      last_render_ms: typeof perf?.totalMs === 'number' ? perf.totalMs : null,
      dash_stats: dashStats ? { ...dashStats } : null,
      propagation: win?.__baklogProp ? { ...win.__baklogProp } : null,
    },
    server: extra.server || null,
    errors: {
      session_count: _errors.length,
      persisted_count: _persistedRing.length,
      session: _errors.slice(),
      persisted: _persistedRing.slice(),
    },
    notice: 'This bundle was assembled locally. Nothing was sent anywhere. Paste it into a GitHub issue if you want to share it.',
  };
}

/** Fetch redacted server diagnostics for bug bundles (best-effort). */
export async function fetchBugBundleServerContext() {
  try {
    const res = await fetch('/api/diagnostics');
    if (!res.ok) return null;
    const data = await res.json();
    return {
      data_dir_path: data.data_dir_path ?? null,
      portable: data.portable ?? null,
      frozen: data.frozen ?? null,
      platform: data.platform ?? null,
      running_from_temp: data.running_from_temp ?? null,
      version: data.version ?? null,
    };
  } catch (_) {
    return null;
  }
}

/** buildBugBundle plus optional server diagnostics (async). */
export async function buildBugBundleAsync() {
  const server = await fetchBugBundleServerContext();
  return buildBugBundle({ server });
}

function readWindowField(win, dotted) {
  if (!win) return undefined;
  try {
    const parts = dotted.split('.');
    let cur = win;
    for (const p of parts) {
      if (cur == null) return undefined;
      cur = cur[p];
    }
    return cur;
  } catch (_) { return undefined; }
}

function safeFingerprint() {
  try {
    const fn = _bundleCtx?.getFingerprint;
    if (typeof fn !== 'function') return null;
    const fp = fn();
    return typeof fp === 'string' ? fp : null;
  } catch (_) { return null; }
}

function safeActiveView() {
  try {
    const fn = _bundleCtx?.getActiveView;
    if (typeof fn === 'function') {
      const v = fn();
      return typeof v === 'string' ? v : null;
    }
  } catch (_) { /* ignore */ }
  return readWindowField(typeof window !== 'undefined' ? window : null, 'state.activeView') ?? null;
}

function scrubErrorText(text) {
  if (typeof text !== 'string' || !text) return text;
  return text
    .replace(/Bearer\s+[A-Za-z0-9._\-]+/gi, 'Bearer [redacted]')
    .replace(/(Cookie:\s*)([^\s;]+)/gi, '$1[redacted]')
    .replace(/api[_-]?key["']?\s*[:=]\s*["']?[\w\-]+/gi, 'api_key=[redacted]');
}

function safeCount() {
  try {
    const fn = _bundleCtx?.getActiveFilterCount;
    if (typeof fn !== 'function') return null;
    const n = fn();
    return typeof n === 'number' ? n : null;
  } catch (_) { return null; }
}

/**
 * Wire deferred context the bundle wants without forcing error-boundary.js
 * to import table-ui / filters-ui (which would defeat the "install before
 * anything else" property — circular import + early-error blindness).
 *
 * Call once from app.js after the modules are loaded.
 *
 * @param {{ getFingerprint?: () => string, getActiveFilterCount?: () => number }} ctx
 */
export function registerBugBundleContext(ctx) {
  if (!ctx || typeof ctx !== 'object') return;
  _bundleCtx = {
    getFingerprint: typeof ctx.getFingerprint === 'function' ? ctx.getFingerprint : null,
    getActiveFilterCount: typeof ctx.getActiveFilterCount === 'function' ? ctx.getActiveFilterCount : null,
    getActiveView: typeof ctx.getActiveView === 'function' ? ctx.getActiveView : null,
  };
}

function copyBugBundle(btn) {
  copyTextToClipboard(JSON.stringify(buildBugBundle(), null, 2), btn);
}

export const BUG_REPORT_ENDPOINT = 'https://baklog.app/api/report';

/** Resolve report endpoint (meta tag / window override / default). */
export function getBugReportEndpoint() {
  return (typeof document !== 'undefined' && document.querySelector('meta[name="baklog-report-endpoint"]')?.content)
    || (typeof window !== 'undefined' && window.__BAKLOG_REPORT_ENDPOINT)
    || BUG_REPORT_ENDPOINT;
}

/**
 * Submit the sanitized bug bundle to the opt-in report endpoint.
 * Only called on explicit user action (Send report in the consent dialog).
 * @param {{ contact?: string, note?: string }} [opts]
 */
export async function submitBugReport({ contact = '', note = '' } = {}) {
  const bundle = await buildBugBundleAsync();
  bundle.errors.persisted = bundle.errors.persisted.slice(-25);
  const res = await fetch(getBugReportEndpoint(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bundle,
      contact: String(contact).slice(0, 320),
      note: String(note).slice(0, 2000),
    }),
  });
  if (!res.ok) throw new Error(`report failed: ${res.status}`);
  return res.json().catch(() => ({}));
}

/**
 * Copy the bug bundle to the clipboard (for kebab menu / programmatic callers).
 * @returns {Promise<boolean>}
 */
export async function copyBugBundleToClipboard() {
  const payload = JSON.stringify(await buildBugBundleAsync(), null, 2);
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(payload);
      return true;
    }
  } catch (_) { /* fall through */ }
  try {
    if (typeof document === 'undefined' || !document.body) return false;
    const ta = document.createElement('textarea');
    ta.value = payload;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    return ok;
  } catch (_) { return false; }
}

function copyTextToClipboard(text, btn) {
  const finish = (ok) => {
    if (!btn) return;
    const original = btn.dataset.originalLabel || btn.textContent;
    btn.dataset.originalLabel = original;
    btn.textContent = ok ? 'Copied' : 'Copy failed';
    setTimeout(() => {
      if (btn.textContent === 'Copied' || btn.textContent === 'Copy failed') {
        btn.textContent = original;
      }
    }, 1400);
  };
  try {
    if (navigator?.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(() => finish(true), () => finish(false));
      return;
    }
  } catch (_) { /* fall through */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
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
  if (isIgnoredError(entry)) return;
  // A lazily-imported chunk 404'd because dist/ was rebuilt under this open tab.
  // Recover by reloading onto the fresh build rather than alarming the user. If
  // we already reloaded recently and it's still failing, fall through so the
  // genuine failure surfaces.
  if (isStaleChunkError(entry) && reloadForStaleChunkOnce()) return;
  const sig = makeSignature(entry);
  if (shouldDedupe(entry)) {
    bumpRepeatsForSignature(sig);
    publishToWindow();
    showOrUpdateToast();
    return;
  }
  entry.repeats = 1;
  _errors.push(entry);
  while (_errors.length > MAX_CAPTURED) _errors.shift();
  persistError(entry);
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
  loadPersistedErrors();
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
  _installed = false;
  _errors.length = 0;
  _signatures.clear();
  _persistedRing = [];
  _bundleCtx = null;
  _dismissed = false;
  hideToast();
  try { window?.localStorage?.removeItem(PERSIST_STORAGE_KEY); } catch (_) { /* noop */ }
  publishToWindow();
}
