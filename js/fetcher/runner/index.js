/** Fetcher runner: queue, SSE streams, log panel, batch runs. */
import { baklogFetch, urlWithStreamTicket } from '../../api-client.js';
import { isPageHidden, registerPausable } from '../../visibility.js';
import { state } from '../../state.js';
import { escapeAttr, escapeHtml } from '../../dom-util.js';
import {
  LOG_PANEL_CHROME_HTML,
  LOG_EMPTY_MESSAGE,
  logCollapseLabel,
} from '../../fetcher-health-log.js';
import {
  FETCHER_AUTH_PROVIDER,
  showReconnectBanner,
  clearReconnectBanner,
} from '../../connections.js';
import {
  LS_FETCHER_SUPPRESSED_RUNS,
  LS_FETCHER_LAST_SEQ,
  profileScopedStorageKey,
} from '../../profiles.js';
import { markClaimsPendingAutoRun } from '../../claimable.js';
import { savePrefs } from '../../prefs.js';
import { bindEscapeClose, trapFocus } from '../../focus-trap.js';
import { authCooldownLabel, clearAuthCooldown } from '../../fetcher-cooldown.js';
import {
  maybeAutoRefreshItad,
  maybeAutoRefreshClaims,
  maybeAutoFetchStale24h,
} from '../../fetcher-auto-refresh.js';
import { autoRefreshDeps } from '../auto-refresh-wire.js';
import {
  fetcherSources,
  fetchSuccessLabels,
  lastRunFailedByKey,
  markItadPendingAutoRun,
} from '../../fetcher-health-shared.js';
import { startFastAgeTick, stopAgeTicker, stopFastAgeTick } from '../../fetcher-chips.js';
import { FETCH_TIMEOUT_MS, fetchWithTimeout } from '../http.js';
import { serverChipState } from '../misc.js';
import { renderDashboardFetcherHealth, cycleStatLayout } from '../render/dashboard.js';
import { updateGlobalFetcherIndicator, setGlobalFetcherTail } from '../global-indicator.js';
import {
  handleFetcherAuthOutcome,
  authCooldownRemainingMs,
  isFetcherDisconnected,
  connectProviderForFetcher,
  fetcherCredentialsSatisfied,
  clearReconnectRequired,
  syncReconnectFromAuthStatus,
  humanizeMissingRequirements,
} from '../reconnect.js';
import {
  loadFetcherSources,
  reloadGamesFn,
  reloadAfterFetcherFn,
  batchRunCooldowns,
  MAX_SSE_HINT,
} from '../source-meta.js';
import { fetcherFreshness, resolveStaleSweepKeys } from '../freshness.js';

export const fetcherRunner = (() => {
  let apiAvailable = null;
  const runStateByKey = new Map();
  /** Keys with a POST /api/run in flight before run_id is assigned. */
  const submitInFlightKeys = new Set();
  const runIdByKey = new Map();
  // One EventSource per run (queued or running). Keeping all of them open
  // means a still-running fetcher keeps streaming lines even after the user
  // queues another one, and every run gets its own `done` event so its chip
  // can clear independently.
  const sourcesByRunId = new Map();
  const reconnectTimers = new Map();
  const reconnectAttempts = new Map();
  /** Run ids the user cancelled — do not reconnect or re-subscribe until gone from server. */
  const suppressedRunIds = new Set();
  const SUPPRESSED_RUNS_KEY = profileScopedStorageKey(LS_FETCHER_SUPPRESSED_RUNS);
  const LAST_SEQ_KEY = profileScopedStorageKey(LS_FETCHER_LAST_SEQ);
  const lastSeqByRunId = new Map();
  const IN_FLIGHT_POLL_MS = 10_000;
  // No-progress window: how long the slot may sit busy WITHOUT the active run
  // advancing before we give up. A run that keeps emitting lines resets it, so
  // legitimately long fetches/enrichers are waited out rather than aborted.
  const WAIT_QUEUE_SLOT_MS = 120_000;
  const RECONNECT_BASE_MS = 2000;
  const RECONNECT_MAX_MS = 30000;
  const RECONNECT_MAX_ATTEMPTS = 8;
  const RECONNECT_MAX_QUEUED = 3;
  const CANCEL_HTTP_MS = 5000;
  /** Background reconcile after instant UI clear — escalate to force reset if still busy. */
  const CANCEL_RECONCILE_WAIT_MS = 4_000;
  let runsSnapshotPromise = null;
  let runsSnapshotAt = 0;
  const RUNS_SNAPSHOT_MIN_MS = 1500;
  let inFlightPollTimer = null;
  /** True when the last /api/runs snapshot had active or queued rows (server truth). */
  let lastServerInFlight = false;
  let lastFetcherLaneInFlight = false;
  let lastEnrichLaneInFlight = false;
  /** Signature (active run id + line count + queue depth) of the last in-flight snapshot. */
  let lastInFlightSig = '';
  /**
   * Timestamp the in-flight signature last advanced. Drives a NO-PROGRESS queue
   * wait timeout (not a total-wait cap): a legitimately long run that keeps
   * emitting lines keeps resetting this, so we keep waiting; only a genuinely
   * wedged slot (no progress for the window) trips the timeout.
   */
  let inFlightProgressAt = 0;
  let cancelInFlight = false;
  /** Bumped on each user cancel — client batch loops capture epoch and stop if it changes. */
  let cancelEpoch = 0;

  function getCancelEpoch() {
    return cancelEpoch;
  }

  function bumpCancelEpoch() {
    cancelEpoch += 1;
  }

  function loadLastSeqByRunId() {
    try {
      const raw = sessionStorage.getItem(LAST_SEQ_KEY);
      if (!raw) return;
      const obj = JSON.parse(raw);
      if (obj && typeof obj === 'object') {
        for (const [id, seq] of Object.entries(obj)) {
          const n = Number(seq);
          if (id && Number.isFinite(n) && n > 0) lastSeqByRunId.set(id, n);
        }
      }
    } catch (_) {}
  }

  function persistLastSeqMap() {
    try {
      const obj = Object.fromEntries(lastSeqByRunId);
      sessionStorage.setItem(LAST_SEQ_KEY, JSON.stringify(obj));
    } catch (_) {}
  }

  function getLastSeq(runId) {
    return lastSeqByRunId.get(runId) || 0;
  }

  function recordLineSeq(runId, seq) {
    const n = Number(seq);
    if (!Number.isFinite(n) || n <= 0) return;
    if (n <= getLastSeq(runId)) return;
    lastSeqByRunId.set(runId, n);
    persistLastSeqMap();
  }

  function clearLastSeq(runId) {
    if (!lastSeqByRunId.delete(runId)) return;
    persistLastSeqMap();
  }

  function streamUrl(runId) {
    const base = `/api/stream/${encodeURIComponent(runId)}`;
    const since = getLastSeq(runId);
    return since > 0 ? `${base}?since=${since}` : base;
  }

  /**
   * Statuses that DON'T hold the fetcher slot: a run being torn down (cancelling)
   * or already terminal. A run with no explicit status is treated as blocking
   * (matches prior behaviour for minimal snapshots).
   */
  const NON_BLOCKING_RUN_STATUSES = new Set(['cancelling', 'done', 'failed', 'cancelled']);

  function runBlocksQueueSlot(run) {
    if (!run) return false;
    if (run.id && suppressedRunIds.has(run.id)) return false;
    if (run.status && NON_BLOCKING_RUN_STATUSES.has(run.status)) return false;
    return true;
  }

  function applyServerSnapshotInFlight(snap) {
    const blockingActive = runBlocksQueueSlot(snap?.active) ? snap.active : null;
    const blockingQueue = (snap?.queue || []).filter(runBlocksQueueSlot);
    const enrichActive = runBlocksQueueSlot(snap?.enrich_active) ? snap.enrich_active : null;
    const enrichQueue = (snap?.enrich_queue || []).filter(runBlocksQueueSlot);
    lastFetcherLaneInFlight = !!(blockingActive || blockingQueue.length);
    lastEnrichLaneInFlight = !!(enrichActive || enrichQueue.length);
    lastServerInFlight = lastFetcherLaneInFlight || lastEnrichLaneInFlight;
    const queueLen = blockingQueue.length + enrichQueue.length;
    const blockingRun = blockingActive || enrichActive;
    // line_count grows on every emitted line (heartbeats included), so the
    // signature changes while a run is alive; a frozen run keeps it stable.
    const sig = blockingRun
      ? `${blockingRun.id || blockingRun.key || 'run'}:${blockingRun.line_count ?? 0}:${queueLen}`
      : (lastServerInFlight ? `q:${queueLen}` : '');
    if (sig && sig !== lastInFlightSig) {
      inFlightProgressAt = Date.now();
    }
    lastInFlightSig = sig;
    updateCancelButton();
  }

  function loadSuppressedRunIds() {
    try {
      const raw = sessionStorage.getItem(SUPPRESSED_RUNS_KEY);
      if (!raw) return;
      const ids = JSON.parse(raw);
      if (Array.isArray(ids)) ids.forEach(id => suppressedRunIds.add(id));
    } catch (_) {}
  }

  function persistSuppressedRunIds() {
    try {
      sessionStorage.setItem(SUPPRESSED_RUNS_KEY, JSON.stringify([...suppressedRunIds]));
    } catch (_) {}
  }

  loadSuppressedRunIds();
  loadLastSeqByRunId();

  async function fetchWithTimeoutAndProbe(url, options = {}, ms = FETCH_TIMEOUT_MS) {
    try {
      return await fetchWithTimeout(url, options, ms);
    } catch (err) {
      if (String(err?.message || err).includes('server not responding')) {
        invalidateApiProbe();
      }
      throw err;
    }
  }

  function labelForKey(key) {
    return source(key)?.label || key;
  }

  /** Human-readable queue position for the run log panel. */
  function queueStatusExtra(snap, runId) {
    if (!snap) return '';
    const queue = snap.queue || [];
    const idx = queue.findIndex(r => r.id === runId);
    if (idx < 0) return '';
    const activeCount = snap.active ? 1 : 0;
    const slots = activeCount + queue.length;
    // Count the active run as the first in-flight slot so a single queued job
    // behind one active run reads "2 of 2" (it is the last of two), matching
    // the visible total rather than its queue-only index.
    const pos = activeCount + idx + 1;
    const waitFor = snap.active ? labelForKey(snap.active.key) : null;
    if (waitFor) return `${pos} of ${slots} - waiting for ${waitFor}`;
    // active=null with queued runs means the server worker wedged; snapshot polls
    // re-queue them, so this is usually brief — not "nothing will ever run".
    if (!snap.active) return `${pos} of ${slots} - starting soon`;
    return `${pos} of ${slots}`;
  }

  function ensureInFlightPolling() {
    if (inFlightPollTimer || !isApiAvailable()) return;
    if (runStateByKey.size === 0 && sourcesByRunId.size === 0) return;
    inFlightPollTimer = setInterval(() => {
      syncFromServer().catch(() => {});
      if (runStateByKey.size === 0 && sourcesByRunId.size === 0) {
        clearInterval(inFlightPollTimer);
        inFlightPollTimer = null;
      }
    }, IN_FLIGHT_POLL_MS);
  }

  function stopInFlightPolling() {
    if (inFlightPollTimer) clearInterval(inFlightPollTimer);
    inFlightPollTimer = null;
  }

  function closeAllStreams() {
    for (const timer of reconnectTimers.values()) clearTimeout(timer);
    reconnectTimers.clear();
    reconnectAttempts.clear();
    for (const { es } of sourcesByRunId.values()) {
      es.onerror = null;
      try { es.close(); } catch (_) {}
    }
    sourcesByRunId.clear();
    liveRunId = null;
    updateCancelButton();
  }

  async function fetchRunsSnapshot({ force = false } = {}) {
    const now = Date.now();
    if (!force && runsSnapshotPromise && now - runsSnapshotAt < RUNS_SNAPSHOT_MIN_MS) {
      return runsSnapshotPromise;
    }
    runsSnapshotAt = now;
    runsSnapshotPromise = fetchWithTimeoutAndProbe('/api/runs')
      .then(r => (r.ok ? r.json() : null))
      .catch(err => {
        if (String(err?.message || err).includes('not responding')) return null;
        return null;
      })
      .finally(() => {
        setTimeout(() => { runsSnapshotPromise = null; }, RUNS_SNAPSHOT_MIN_MS);
      });
    return runsSnapshotPromise;
  }

  function clearReconnect(runId) {
    const t = reconnectTimers.get(runId);
    if (t) clearTimeout(t);
    reconnectTimers.delete(runId);
  }

  function pruneSuppressedRuns(snap) {
    if (!snap) return;
    const terminal = new Set();
    for (const h of snap.history || []) {
      if (h?.id && ['done', 'failed', 'cancelled'].includes(h.status)) {
        terminal.add(h.id);
      }
    }
    for (const id of suppressedRunIds) {
      if (terminal.has(id)) suppressedRunIds.delete(id);
    }
    persistSuppressedRunIds();
  }

  function scheduleReconnect(runId, key, src, { queuedOnly = false } = {}) {
    if (suppressedRunIds.has(runId)) return;
    if (reconnectTimers.has(runId)) return;
    const attempt = (reconnectAttempts.get(runId) || 0) + 1;
    const maxAttempts = queuedOnly ? RECONNECT_MAX_QUEUED : RECONNECT_MAX_ATTEMPTS;
    if (attempt > maxAttempts) {
      reconnectAttempts.delete(runId);
      logEvent(
        'error',
        `[${src.label}: stream dropped too many times - refresh the page or use Cancel]`,
      );
      markChipState(key, null);
      if (liveRunId === runId) {
        setStatus('failed');
        liveRunId = null;
        updateCancelButton();
      }
      return;
    }
    reconnectAttempts.set(runId, attempt);
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** (attempt - 1) * (queuedOnly ? 1.5 : 1),
      RECONNECT_MAX_MS,
    );
    logEvent('info', `[${src.label}: stream dropped - reconnecting in ${Math.round(delay / 1000)}s]`);
    const timer = setTimeout(() => {
      reconnectTimers.delete(runId);
      if (suppressedRunIds.has(runId) || cancelInFlight) return;
      if (queuedOnly) return;
      if (!sourcesByRunId.has(runId)) subscribe(runId, key, src, { reconnect: true });
    }, delay);
    reconnectTimers.set(runId, timer);
  }

  // Whichever run is currently emitting stdout — used to set the panel title
  // and the top-right status pill. Only one server-side run is active at a
  // time because the worker queue is single-threaded, so this is safe.
  let liveRunId = null;
  let logEl = null;
  let logBodyEl = null;
  let forceExpanded = false;
  // Set when the user manually collapses the console mid-run so the polling
  // loop's auto-expand (ensurePanel) doesn't keep reopening it. Cleared when
  // the fetcher goes idle or the user manually reopens, so a fresh run can
  // still auto-open the console.
  let suppressAutoExpand = false;
  let lastLineText = '';
  let lastLineKind = 'stdout';
  let lastBarSummary = 'Fetcher health';
  let pollTimer = null;
  let _dashboardPollWanted = false;
  let syncedOnce = false;
  /** Avoid re-running refreshAfterFetch on every dashboard tab return when syncFromServer
   *  keeps seeing the same recent "done" run in the 5-minute window. */
  let _lastAppliedDoneRunId = null;

  function logPanel() {
    if (!logEl || !document.body.contains(logEl)) {
      logEl = document.getElementById('fetcherRunLog');
    }
    return logEl;
  }

  function logBody() {
    if (typeof document === 'undefined') return null;
    if (!logBodyEl || !document.body.contains(logBodyEl)) {
      logBodyEl = logPanel()?.querySelector('.fh-log-body') || logPanel()?.querySelector('[data-role="body"]') || null;
    }
    return logBodyEl;
  }

  function fetcherRow() {
    return document.getElementById('fetcherRow');
  }

  function fetcherPopoverEl() {
    return document.getElementById('fetcherPopover');
  }

  function isFetcherPopoverOpen() {
    const pop = fetcherPopoverEl();
    return !!(pop && !pop.hidden);
  }

  let fetcherPopoverRelease = null;

  function hideFetcherPopover() {
    fetcherPopoverRelease?.();
    fetcherPopoverRelease = null;
    const pop = fetcherPopoverEl();
    const bd = document.getElementById('fetcherPopoverBackdrop');
    const pill = document.getElementById('fetcherGlobalStatus');
    if (bd) bd.hidden = true;
    if (pop) pop.hidden = true;
    if (pill) pill.setAttribute('aria-expanded', 'false');
    // Collapse the log console drawer so reopening the fetcher starts tidy.
    const panel = logPanel();
    if (panel && !panel.classList.contains('fh-log--collapsed')) {
      panel.classList.add('fh-log--collapsed');
      syncLogCollapseButton();
    }
    if (isFetcherInFlight()) suppressAutoExpand = true;
  }

  function showFetcherPopover({ focusPanel = true } = {}) {
    if (typeof document !== 'undefined' && document.documentElement.hasAttribute('data-boot-loading')) {
      return false;
    }
    const pop = fetcherPopoverEl();
    const bd = document.getElementById('fetcherPopoverBackdrop');
    if (!pop || !bd) return false;
    bd.hidden = false;
    pop.hidden = false;
    const pill = document.getElementById('fetcherGlobalStatus');
    if (pill) pill.setAttribute('aria-expanded', 'true');
    forceExpanded = true;
    suppressAutoExpand = false;
    fetchSuccessLabels.clear();
    updateGlobalFetcherIndicator(runStateByKey, source);
    buildLogPanelChrome();
    expandLogBody();
    applyFetcherRowLayout();
    renderDashboardFetcherHealth();
    fetcherPopoverRelease?.();
    const releaseTrap = trapFocus(pop);
    const releaseEsc = bindEscapeClose(pop, hideFetcherPopover);
    fetcherPopoverRelease = () => {
      releaseTrap();
      releaseEsc();
      fetcherPopoverRelease = null;
    };
    if (focusPanel) {
      pop.querySelector('[data-fetcher-popover-close]')?.focus({ preventScroll: true });
    }
    pop.classList.add('fh-pop-opening');
    setTimeout(() => pop.classList.remove('fh-pop-opening'), 600);
    return true;
  }

  function toggleFetcherPopover() {
    if (isFetcherPopoverOpen()) hideFetcherPopover();
    else showFetcherPopover();
  }

  function openFetcherLog({ focusPanel = false } = {}) {
    if (fetcherPopoverEl()) {
      showFetcherPopover({ focusPanel });
      expandLogBody();
      return true;
    }
    reopenLogPanel();
    return true;
  }

  /**
   * Scroll the open fetcher popover module to the console (`'console'`) so the
   * user sees the log output that a chip click just produced, or back to the
   * top (`'top'`) when the click was a no-op. No-op outside the popover (legacy
   * inline row scrolls with the page).
   */
  function scrollPopoverModule(where) {
    const pop = fetcherPopoverEl();
    if (!pop || pop.hidden) return;
    const scroller = pop.querySelector('.fetcher-popover-scroll');
    if (!scroller) return;
    requestAnimationFrame(() => {
      if (where === 'console') {
        scrollLogToBottom();
        const log = logPanel();
        if (log) {
          const logRect = log.getBoundingClientRect();
          const scRect = scroller.getBoundingClientRect();
          if (logRect.bottom > scRect.bottom || logRect.top < scRect.top) {
            scroller.scrollTop += logRect.top - scRect.top - 8;
          }
        } else {
          scroller.scrollTop = scroller.scrollHeight;
        }
      } else {
        scroller.scrollTop = 0;
      }
    });
  }

  function isFetcherInFlight() {
    return runStateByKey.size > 0 || lastServerInFlight || cancelInFlight;
  }

  function shouldShowExpanded() {
    return forceExpanded || !state.prefs.fetcherCollapsed;
  }

  function isFetcherRowExpanded() {
    return fetcherRow()?.classList.contains('is-expanded') ?? false;
  }

  function barStatusFromRuns() {
    const running = [];
    const queued = [];
    for (const [key, st] of runStateByKey) {
      const src = source(key);
      const label = src?.label || key;
      if (st === 'running') running.push(label);
      else if (st === 'queued') queued.push(label);
    }
    if (running.length) {
      return running.length === 1 ? `Running: ${running[0]}` : `Running: ${running.join(', ')}`;
    }
    if (queued.length) {
      return queued.length === 1 ? `Queued: ${queued[0]}` : `Queued: ${queued.join(', ')}`;
    }
    return lastBarSummary;
  }

  function updateFetcherBar() {
    const bar = document.querySelector('[data-role="fetcher-bar"]');
    if (!bar) return;
    const expanded = isFetcherRowExpanded();
    const statusEl = bar.querySelector('[data-role="bar-status"]');
    const tailEl = bar.querySelector('[data-role="bar-tail"]');
    const dotEl = bar.querySelector('[data-role="bar-dot"]');
    const toggleEl = bar.querySelector('[data-role="bar-toggle"]');
    if (statusEl) statusEl.textContent = barStatusFromRuns();
    if (tailEl) {
      tailEl.textContent = lastLineText || 'No fetcher activity yet.';
      tailEl.className = `fh-bar-tail${lastLineKind === 'stderr' ? ' stderr' : ''}`;
    }
    if (dotEl) dotEl.classList.toggle('is-live', isFetcherInFlight());
    if (toggleEl) {
      toggleEl.textContent = expanded ? '▾' : '▸';
      toggleEl.classList.toggle('is-open', expanded);
      toggleEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      toggleEl.setAttribute('aria-label', expanded ? 'Collapse fetcher' : 'Expand fetcher');
    }
  }

  function applyFetcherRowLayout() {
    const row = fetcherRow();
    if (!row) return;
    const inPopover = !!fetcherPopoverEl();
    const expanded = inPopover
      ? isFetcherPopoverOpen()
      : shouldShowExpanded();
    row.classList.toggle('is-expanded', expanded);
    row.classList.toggle('is-collapsed', !expanded);
    const panel = logPanel();
    if (panel) {
      if (expanded) {
        buildLogPanelChrome();
        panel.classList.add('open');
        ensureLogHeightObserver();
        requestAnimationFrame(() => syncLogHeightToCard());
      } else {
        clearLogHeightCap(panel);
        panel.classList.remove('open');
      }
    }
    updateFetcherBar();
  }

  function revertFetcherLayoutIfIdle() {
    if (isFetcherInFlight()) return;
    forceExpanded = false;
    suppressAutoExpand = false;
    applyFetcherRowLayout();
  }

  function expandPanel({ manual = false, src, serverStatus, extra } = {}) {
    if (manual) {
      state.prefs.fetcherCollapsed = false;
      savePrefs();
      forceExpanded = false;
      suppressAutoExpand = false;
    } else if (!suppressAutoExpand) {
      forceExpanded = true;
    }
    const panel = buildLogPanelChrome();
    if (!panel) return false;
    if (src && serverStatus) {
      syncLogPanelChrome(src, serverStatus, extra);
    } else if (src) {
      panel.querySelector('[data-role="title"]').textContent = src.label;
    } else {
      const titleEl = panel.querySelector('[data-role="title"]');
      if (titleEl) titleEl.textContent = 'Fetcher log';
    }
    updateCancelButton();
    logBodyEl = panel.querySelector('[data-role="body"]');
    applyFetcherRowLayout();
    return true;
  }

  function collapsePanel({ manual = false } = {}) {
    if (isFetcherPopoverOpen()) {
      hideFetcherPopover();
      return;
    }
    if (manual) {
      state.prefs.fetcherCollapsed = true;
      savePrefs();
      // Stop the polling loop from auto-reopening this collapsed console
      // for the remainder of the in-flight run.
      if (isFetcherInFlight()) suppressAutoExpand = true;
    }
    forceExpanded = false;
    applyFetcherRowLayout();
  }

  function toggleFetcherPanel({ manual = true } = {}) {
    if (fetcherPopoverEl()) {
      toggleFetcherPopover();
      return;
    }
    if (isFetcherRowExpanded()) collapsePanel({ manual });
    else expandPanel({ manual });
  }

  const LOG_DESKTOP_MQ = '(min-width: 768px)';
  let logHeightCardObs = null;
  let logHeightResizeWired = false;

  function clearLogHeightCap(panel = logPanel()) {
    if (!panel) return;
    panel.style.maxHeight = '';
    panel.style.height = '';
  }

  /** Lock open log panel height to the fetcher-health card (desktop side-by-side). */
  function syncLogHeightToCard() {
    const panel = logPanel();
    const card = document.getElementById('dashboardFetcherHealth');
    if (!isFetcherRowExpanded() || !panel || !panel.classList.contains('open')) return;
    if (fetcherPopoverEl() || !window.matchMedia(LOG_DESKTOP_MQ).matches) {
      clearLogHeightCap(panel);
      return;
    }
    if (!card) return;
    panel.style.maxHeight = '0px';
    panel.style.height = '0px';
    void panel.offsetHeight;
    const cardHeight = card.offsetHeight;
    if (cardHeight > 0) {
      panel.style.maxHeight = `${cardHeight}px`;
      panel.style.height = `${cardHeight}px`;
    } else {
      clearLogHeightCap(panel);
    }
    updateJumpButton();
    if (followTail) scrollLogToBottom();
  }

  function ensureLogHeightObserver() {
    if (fetcherPopoverEl()) return;
    const card = document.getElementById('dashboardFetcherHealth');
    if (!card || typeof ResizeObserver === 'undefined') return;
    if (!logHeightCardObs) {
      logHeightCardObs = new ResizeObserver(() => {
        if (isFetcherRowExpanded() && logPanel()?.classList.contains('open')) syncLogHeightToCard();
      });
      logHeightCardObs.observe(card);
    }
    if (!logHeightResizeWired) {
      logHeightResizeWired = true;
      window.addEventListener('resize', () => {
        if (isFetcherRowExpanded() && logPanel()?.classList.contains('open')) syncLogHeightToCard();
      });
    }
  }

  function invalidateApiProbe() {
    apiAvailable = null;
  }

  async function probeApi(force = false) {
    if (force) apiAvailable = null;
    if (apiAvailable !== null) return apiAvailable;
    try {
      await loadFetcherSources(force);
      const res = await baklogFetch('/api/fetchers', { method: 'GET' });
      apiAvailable = res.ok;
    } catch {
      apiAvailable = false;
    }
    return apiAvailable;
  }

  function isApiAvailable() {
    return apiAvailable === true;
  }

  function apiProbeFinished() {
    return apiAvailable !== null;
  }

  function stateFor(key) {
    return runStateByKey.get(key) || null;
  }

  // Count of fetchers currently running client-side. The server enforces a hard
  // cap of 1 (no queuing); we mirror that here so the UI can disable other
  // chips before the user wastes a click on a 409.
  const MAX_IN_FLIGHT = 1;
  function inFlightCount() {
    return runStateByKey.size;
  }
  function isEnrichKey(key) {
    return source(key)?.group === 'enrich';
  }
  function isQueueFullForKey(key) {
    const enrich = isEnrichKey(key);
    const laneBusy = enrich ? lastEnrichLaneInFlight : lastFetcherLaneInFlight;
    if (laneBusy) return true;
    for (const [k] of runStateByKey) {
      if (isEnrichKey(k) === enrich) return true;
    }
    return false;
  }
  function isQueueFull() {
    return inFlightCount() >= MAX_IN_FLIGHT || lastServerInFlight;
  }
  const WAIT_QUEUE_SNAPSHOT_POLL_MS = 2000;
  function waitForQueueSlot({ batchEpoch, key } = {}) {
    if (batchEpoch !== undefined && getCancelEpoch() !== batchEpoch) {
      return Promise.reject(new Error('cancelled'));
    }
    if (cancelInFlight) return Promise.reject(new Error('cancelled'));
    if (key && !isQueueFullForKey(key)) return Promise.resolve();
    if (!key && !isQueueFull()) return Promise.resolve();
    // Deadline base is the later of wait-start and the last observed progress;
    // it slides forward as the active run advances (see inFlightProgressAt).
    let progressDeadlineBase = Date.now();
    let lastSnapPoll = 0;
    return new Promise((resolve, reject) => {
      const schedule = (delay) => setTimeout(tick, delay);
      const tick = () => {
        if (cancelInFlight) {
          reject(new Error('cancelled'));
          return;
        }
        if (batchEpoch !== undefined && getCancelEpoch() !== batchEpoch) {
          reject(new Error('cancelled'));
          return;
        }
        if (key ? !isQueueFullForKey(key) : !isQueueFull()) {
          resolve();
          return;
        }
        if (inFlightProgressAt > progressDeadlineBase) {
          progressDeadlineBase = inFlightProgressAt;
        }
        if (Date.now() - progressDeadlineBase > WAIT_QUEUE_SLOT_MS) {
          reject(new Error('queue wait timeout'));
          return;
        }
        const now = Date.now();
        if (isApiAvailable() && now - lastSnapPoll >= WAIT_QUEUE_SNAPSHOT_POLL_MS) {
          lastSnapPoll = now;
          void fetchRunsSnapshot({ force: true })
            .then((snap) => {
              if (snap) applyServerSnapshotInFlight(snap);
              if (key ? !isQueueFullForKey(key) : !isQueueFull()) resolve();
              else schedule(200);
            })
            .catch(() => schedule(200));
          return;
        }
        schedule(200);
      };
      tick();
    });
  }

  function source(key) {
    return fetcherSources.find(s => s.key === key) || null;
  }

  /**
   * Build the panel's DOM shell + click delegation if it hasn't been built
   * yet. Idempotent and safe to call from both run-starting paths
   * (ensurePanel) and reopen paths (reopenLogPanel). Doesn't open the panel
   * or change status — callers decide.
   */
  function isLogBodyCollapsed() {
    return logPanel()?.classList.contains('fh-log--collapsed') ?? false;
  }

  function syncLogCollapseButton() {
    const btn = logPanel()?.querySelector('[data-role="close"]');
    if (!btn) return;
    const collapsed = isLogBodyCollapsed();
    btn.classList.toggle('is-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    const label = logCollapseLabel(collapsed);
    btn.title = label;
    btn.setAttribute('aria-label', label);
  }

  function toggleLogBody() {
    const panel = logPanel();
    if (!panel) return;
    panel.classList.toggle('fh-log--collapsed');
    syncLogCollapseButton();
  }

  function expandLogBody() {
    const panel = logPanel();
    if (!panel || !panel.classList.contains('fh-log--collapsed')) return;
    panel.classList.remove('fh-log--collapsed');
    syncLogCollapseButton();
  }

  function buildLogPanelChrome() {
    const panel = logPanel();
    if (!panel) return null;
    if (panel.dataset.built) return panel;
    panel.innerHTML = LOG_PANEL_CHROME_HTML;
    panel.dataset.built = '1';
    syncLogCollapseButton();
    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-role]');
      if (!btn) return;
      if (btn.dataset.role === 'close') toggleLogBody();
      else if (btn.dataset.role === 'clear') clearLog();
      else if (btn.dataset.role === 'cancel') cancelInFlightRuns({ force: e.shiftKey });
      else if (btn.dataset.role === 'jump') scrollLogToBottom();
    });
    const body = panel.querySelector('[data-role="body"]');
    if (body) body.addEventListener('scroll', () => onLogBodyScroll(body));
    return panel;
  }

  /** Build/sync log chrome during runs without opening the popover or row. */
  function ensurePanel(src, serverStatus, extra) {
    const panel = buildLogPanelChrome();
    if (!panel) return;
    if (src && serverStatus) {
      syncLogPanelChrome(src, serverStatus, extra);
    } else if (src) {
      const titleEl = panel.querySelector('[data-role="title"]');
      if (titleEl) titleEl.textContent = src.label;
    }
    updateCancelButton();
    logBodyEl = panel.querySelector('[data-role="body"]');
  }

  /**
   * Expand fetcher health + console (e.g. kebab "Show fetcher log"). Builds
   * chrome if needed; preserves existing log lines.
   *
   * Expand fetcher health + console (header popover or legacy inline row).
   * @returns {boolean}
   */
  function reopenLogPanel() {
    const panel = buildLogPanelChrome();
    if (!panel) return false;
    const body = panel.querySelector('[data-role="body"]');
    if (body && !body.children.length) {
      const empty = document.createElement('div');
      empty.className = 'fh-log-empty';
      empty.textContent = LOG_EMPTY_MESSAGE;
      body.appendChild(empty);
      followTail = true;
      clearFollowTailIdleTimer();
    }
    logBodyEl = body || null;
    const ok = expandPanel({ manual: true });
    expandLogBody();
    return ok;
  }

  function updateCancelButton() {
    const panel = logPanel();
    if (!panel) return;
    const btn = panel.querySelector('[data-role="cancel"]');
    if (!btn) return;
    const show = isApiAvailable() && (inFlightCount() > 0 || lastServerInFlight);
    btn.classList.toggle('hidden', !show);
    if (cancelInFlight) {
      btn.disabled = true;
      btn.textContent = 'Cancelling…';
      btn.title = 'Stopping queued and running fetchers…';
    } else {
      btn.disabled = !show;
      btn.textContent = 'Cancel';
      btn.title = 'Stop all queued and running fetchers and enrichers (Shift+click: force reset queue)';
    }
  }

  async function cancelOneRun(runId) {
    try {
      const res = await fetchWithTimeoutAndProbe(
        `/api/run/${encodeURIComponent(runId)}/cancel`,
        { method: 'POST' },
        CANCEL_HTTP_MS,
      );
      return res.ok;
    } catch (_) {
      return false;
    }
  }

  async function waitForRunsToClear(runIds, timeoutMs = CANCEL_RECONCILE_WAIT_MS) {
    const pending = new Set(runIds);
    const deadline = Date.now() + timeoutMs;
    while (pending.size > 0 && Date.now() < deadline) {
      let snap = null;
      try {
        snap = await fetchRunsSnapshot({ force: true });
      } catch (_) {
        break;
      }
      if (!snap) break;
      for (const id of [...pending]) {
        const onActive = snap.active?.id === id;
        const onQueue = (snap.queue || []).some(r => r.id === id);
        const onEnrichActive = snap.enrich_active?.id === id;
        const onEnrichQueue = (snap.enrich_queue || []).some(r => r.id === id);
        if (!onActive && !onQueue && !onEnrichActive && !onEnrichQueue) {
          const hist = (snap.history || []).find(r => r.id === id);
          if (hist && ['done', 'failed', 'cancelled'].includes(hist.status)) {
            pending.delete(id);
          }
        }
      }
      await syncFromServer();
      if (pending.size > 0) {
        await new Promise(r => setTimeout(r, 400));
      }
    }
    return pending;
  }

  function applyInstantCancelUi({ force = false } = {}) {
    for (const key of [...runStateByKey.keys()]) markChipState(key, null);
    liveRunId = null;
    lastServerInFlight = false;
    lastFetcherLaneInFlight = false;
    lastEnrichLaneInFlight = false;
    logEvent(
      'info',
      force ? '[force reset - queue cleared locally]' : '[cancelled]',
    );
    flushLinesNow();
    setStatus('failed');
    renderDashboardFetcherHealth();
    revertFetcherLayoutIfIdle();
    updateCancelButton();
  }

  async function cancelServerLane(lane, { force = false } = {}) {
    const qs = force ? `?lane=${lane}&force=1` : `?lane=${lane}`;
    try {
      const res = await fetchWithTimeoutAndProbe(
        `/api/runs/cancel${qs}`,
        { method: 'POST' },
        CANCEL_HTTP_MS,
      );
      if (!res.ok) return 0;
      const data = await res.json();
      return data.cancelled?.length ?? 0;
    } catch (_) {
      return 0;
    }
  }

  function reconcileCancelInBackground(ids, { force = false } = {}) {
    void (async () => {
      // Dashboard Cancel clears fetcher + enrich lanes only — never kill admin
      // (internal) jobs like buildClaims/claimSources running in parallel.
      let bulkOk = false;
      let cancelledTotal = 0;
      for (const lane of ['fetcher', 'enrich']) {
        const n = await cancelServerLane(lane, { force });
        if (n > 0) {
          bulkOk = true;
          cancelledTotal += n;
        }
      }
      if (cancelledTotal) {
        logEvent(
          'info',
          force
            ? `[server force reset: ${cancelledTotal} run(s)]`
            : `[server cancelled ${cancelledTotal} run(s)]`,
        );
      }
      if (!bulkOk && ids.length) {
        for (const id of ids) {
          await cancelOneRun(id);
        }
      }
      const stillRunning = await waitForRunsToClear(ids, CANCEL_RECONCILE_WAIT_MS);
      if (stillRunning.size && !force) {
        logEvent('info', '[queue still busy - force reset…]');
        await cancelInFlightRuns({ force: true });
        return;
      }
      for (const id of ids) {
        if (!stillRunning.has(id)) suppressedRunIds.add(id);
      }
      persistSuppressedRunIds();
      try {
        const snap = await fetchRunsSnapshot({ force: true });
        applyServerSnapshotInFlight(snap);
        pruneSuppressedRuns(snap);
      } catch (_) {}
      await syncFromServer();
    })();
  }

  async function cancelInFlightRuns({ force = false } = {}) {
    if (!isApiAvailable()) return;
    if (cancelInFlight) return;
    cancelInFlight = true;
    bumpCancelEpoch();
    let ids = [];
    try {
      let snap = null;
      try {
        snap = await fetchRunsSnapshot({ force: true });
      } catch (_) {}
      applyServerSnapshotInFlight(snap);
      if (snap?.active) ids.push(snap.active.id);
      for (const q of snap?.queue || []) ids.push(q.id);
      if (snap?.enrich_active) ids.push(snap.enrich_active.id);
      for (const q of snap?.enrich_queue || []) ids.push(q.id);
      const clientStale = inFlightCount() > 0;
      if (!ids.length && !force && !clientStale && !lastServerInFlight) {
        return;
      }
      closeAllStreams();
      for (const id of ids) suppressedRunIds.add(id);
      persistSuppressedRunIds();
      applyInstantCancelUi({ force });
      reconcileCancelInBackground(ids, { force });
    } finally {
      cancelInFlight = false;
      updateCancelButton();
    }
  }

  function reconcileRunStateFromSnapshot(snap) {
    if (!snap) return;
    const inFlightKeys = new Set();
    if (snap.active?.key) inFlightKeys.add(snap.active.key);
    for (const q of snap.queue || []) {
      if (q.key) inFlightKeys.add(q.key);
    }
    if (snap.enrich_active?.key) inFlightKeys.add(snap.enrich_active.key);
    for (const q of snap.enrich_queue || []) {
      if (q.key) inFlightKeys.add(q.key);
    }
    const historyByKey = new Map();
    for (const h of snap.history || []) {
      if (!h.key) continue;
      if (!historyByKey.has(h.key) || (h.ended_at || 0) > (historyByKey.get(h.key).ended_at || 0)) {
        historyByKey.set(h.key, h);
      }
    }
    for (const key of [...runStateByKey.keys()]) {
      const state = runStateByKey.get(key);
      if (!state || state === 'failed') continue;
      if (inFlightKeys.has(key)) continue;
      const runId = runIdByKey.get(key);
      if (runId && sourcesByRunId.has(runId)) continue;
      const hist = historyByKey.get(key);
      if (hist) {
        if (hist.status === 'done' && hist.exit_code === 0) {
          markChipState(key, null);
        } else if (hist.status === 'cancelled') {
          markChipState(key, null);
        } else {
          markChipState(key, 'failed');
        }
        if (hist.id) clearLastSeq(hist.id);
      } else {
        markChipState(key, null);
        if (runId) clearLastSeq(runId);
      }
    }
  }

  function closePanel() {
    collapsePanel({ manual: true });
  }

  const LOG_DOM_CAP = 4000;
  const LOG_BUFFER_CAP = 4000;
  const FOLLOW_TAIL_IDLE_MS = 12_000;
  let pendingLines = [];
  let flushHandle = 0;
  let followTail = true;
  let followTailIdleTimer = 0;

  function clearFollowTailIdleTimer() {
    if (followTailIdleTimer) {
      clearTimeout(followTailIdleTimer);
      followTailIdleTimer = 0;
    }
  }

  function scheduleFollowTailIdle() {
    clearFollowTailIdleTimer();
    followTailIdleTimer = setTimeout(() => {
      followTailIdleTimer = 0;
      followTail = true;
      updateJumpButton();
    }, FOLLOW_TAIL_IDLE_MS);
  }

  function onLogBodyScroll(body) {
    if (logNearBottom(body)) {
      followTail = true;
      clearFollowTailIdleTimer();
    } else {
      followTail = false;
      scheduleFollowTailIdle();
    }
    updateJumpButton();
  }

  function clearLog() {
    pendingLines = [];
    if (flushHandle) {
      cancelAnimationFrame(flushHandle);
      flushHandle = 0;
    }
    const body = logBody();
    if (body) body.innerHTML = '';
    followTail = true;
    clearFollowTailIdleTimer();
    updateJumpButton();
  }

  /** Is the log scrolled within ~24px of the bottom (i.e. pinned to latest)? */
  function logNearBottom(body) {
    return body.scrollHeight - body.scrollTop - body.clientHeight < 24;
  }

  /** Show the jump-to-latest arrow only when scrolled away from the bottom. */
  function updateJumpButton() {
    const panel = logPanel();
    if (!panel) return;
    const body = panel.querySelector('[data-role="body"]');
    const btn = panel.querySelector('[data-role="jump"]');
    if (!body || !btn) return;
    btn.classList.toggle('hidden', logNearBottom(body));
  }

  function scrollLogToBottom() {
    const body = logBody();
    if (!body) return;
    followTail = true;
    clearFollowTailIdleTimer();
    const pin = () => {
      body.scrollTop = body.scrollHeight;
    };
    pin();
    requestAnimationFrame(pin);
    updateJumpButton();
  }

  function setStatus(status, extra) {
    const panel = logPanel();
    if (!panel) return;
    const el = panel.querySelector('[data-role="status"]');
    if (!el) return;
    el.className = `fh-log-status ${status}`;
    el.textContent = extra ? `${status} · ${extra}` : status;
    const body = panel.querySelector('[data-role="body"]');
    if (body) {
      if (status === 'running' || status === 'queued' || status === 'launching') {
        body.setAttribute('data-running', '1');
      } else {
        body.removeAttribute('data-running');
      }
    }
  }

  /** Keep log panel title and status badge aligned with server run state. */
  function syncLogPanelChrome(src, serverStatus, extra) {
    const panel = logPanel();
    if (!panel || !src) return;
    const titleEl = panel.querySelector('[data-role="title"]');
    const label = src.label || src.key;
    switch (serverStatus) {
      case 'launching':
        if (titleEl) titleEl.textContent = `Launching: ${label}`;
        setStatus('launching');
        break;
      case 'running':
        if (titleEl) titleEl.textContent = `Running: ${label}`;
        setStatus('running', extra);
        break;
      case 'cancelling':
        if (titleEl) titleEl.textContent = `Running: ${label}`;
        setStatus('running', extra || 'cancelling');
        break;
      case 'queued':
        if (titleEl) titleEl.textContent = `Queued: ${label}`;
        setStatus('queued', extra);
        break;
      default:
        setStatus(serverStatus, extra);
        break;
    }
  }

  function flushLines() {
    flushHandle = 0;
    if (!pendingLines.length) return;
    const body = logBody();
    if (!body) {
      pendingLines = [];
      return;
    }
    const batch = pendingLines;
    pendingLines = [];
    const placeholder = body.querySelector('.fh-log-empty');
    if (placeholder) placeholder.remove();
    const fragment = document.createDocumentFragment();
    for (const { text, kind } of batch) {
      const div = document.createElement('div');
      div.className = `fh-log-line ${kind}`;
      div.textContent = text;
      fragment.appendChild(div);
    }
    body.appendChild(fragment);
    while (body.children.length > LOG_DOM_CAP) body.removeChild(body.firstChild);
    if (followTail) {
      body.scrollTop = body.scrollHeight;
      requestAnimationFrame(() => {
        if (followTail) body.scrollTop = body.scrollHeight;
        updateJumpButton();
      });
    } else {
      updateJumpButton();
    }
  }

  function flushLinesNow() {
    if (flushHandle) {
      cancelAnimationFrame(flushHandle);
      flushHandle = 0;
    }
    flushLines();
  }

  const LOG_LEVEL_KIND = {
    cmd: 'cmd',
    output: 'stdout',
    info: 'meta',
    warn: 'warn',
    error: 'stderr',
  };

  function appendLine(text, kind = 'stdout') {
    if (!logBody()) buildLogPanelChrome();
    if (!logBody()) return;
    lastLineText = text;
    lastLineKind = kind;
    if (!isFetcherRowExpanded()) updateFetcherBar();
    setGlobalFetcherTail(text, kind);
    pendingLines.push({ text, kind });
    if (pendingLines.length > LOG_BUFFER_CAP) {
      pendingLines = pendingLines.slice(-LOG_BUFFER_CAP);
    }
    if (!flushHandle) {
      flushHandle = requestAnimationFrame(flushLines);
    }
  }

  function logEvent(level, text) {
    appendLine(text, LOG_LEVEL_KIND[level] ?? 'stdout');
  }

  function markChipState(key, runState, runId = null) {
    if (runState && runStateByKey.size === 0) fetchSuccessLabels.clear();
    if (runState) {
      runStateByKey.set(key, runState);
      if (runId) runIdByKey.set(key, runId);
    } else {
      runStateByKey.delete(key);
      runIdByKey.delete(key);
    }
    updateGlobalFetcherIndicator(runStateByKey, source);
    renderDashboardFetcherHealth();
    if (runState) ensureInFlightPolling();
    else if (runStateByKey.size === 0) {
      stopInFlightPolling();
      revertFetcherLayoutIfIdle();
      // Client chip cleared — re-check server truth so stale lastServerInFlight
      // does not keep isQueueFull() latched after a run ends locally.
      void fetchRunsSnapshot()
        .then((snap) => {
          if (snap) applyServerSnapshotInFlight(snap);
          updateCancelButton();
        })
        .catch(() => {});
    }
    updateFetcherBar();
  }

  // Returns true only when a run was actually submitted to the server; false on
  // any early bail (API down, cooldown, disconnected, queue full, submit error)
  // so callers can react when a requested run never actually started.
  async function run(key, { refresh = false, auto = false } = {}) {
    if (!isApiAvailable()) {
      if (!auto) scrollPopoverModule('top');
      return false;
    }
    if (cancelInFlight) {
      if (!auto) scrollPopoverModule('top');
      return false;
    }
    await loadFetcherSources(true);
    const src = source(key);
    if (!src || runStateByKey.has(key) || submitInFlightKeys.has(key)) {
      if (!auto) scrollPopoverModule('top');
      return false;
    }
    // Auth-failure backoff: block while cooling down. Auto/bulk runs stay
    // silent; a chip click is already prevented by the disabled attribute, so
    // this only fires for programmatic callers — explain it once.
    const cooldownMs = authCooldownRemainingMs(key);
    if (cooldownMs > 0) {
      if (!auto) {
        ensurePanel(src);
        logEvent(
          'info',
          `[${src.label}: auth cooldown - ${authCooldownLabel(cooldownMs)} left. Reconnect in Connections to clear.]`,
        );
        scrollPopoverModule('console');
      }
      return false;
    }
    if (isFetcherDisconnected(key)) {
      if (!auto) {
        ensurePanel(src);
        const provider = connectProviderForFetcher(key);
        logEvent(
          'info',
          `[${src.label}: not connected - connect in Connections before running. No request sent.]`,
        );
        if (provider) showReconnectBanner([provider]);
        scrollPopoverModule('console');
      }
      return false;
    }
    // Hard cap mirrors server-side enforcement (max 1 active run, no queuing).
    // Without this guard a fast double-click could land two POSTs before the
    // server's lock saw the first one as pending.
    if (isQueueFullForKey(key)) {
      if (!auto) {
        ensurePanel(src);
        logEvent(
          'info',
          `[${src.label}: queue full - a fetch is already running]`,
        );
        scrollPopoverModule('console');
      }
      return false;
    }
    if (refresh && !src.supportsRefresh) {
      logEvent(
        'info',
        `[${src.label}: this fetcher has no force-refresh mode - a normal click already pulls the latest data]`,
      );
      if (!auto) scrollPopoverModule('console');
      return false;
    }

    if (auto && key === 'itad') {
      markItadPendingAutoRun();
    } else if (auto && key === 'claims') {
      markClaimsPendingAutoRun();
    } else {
      ensurePanel(src);
      if (src.missingRequirements?.length && !fetcherCredentialsSatisfied(key)) {
        const hint = humanizeMissingRequirements(src.missingRequirements);
        logEvent(
          'warn',
          `[warning: ${hint} - open Connections before running]`,
        );
      }
      const cmdSuffix = refresh ? ' --refresh' : '';
      logEvent('cmd', `$ ${src.cmd}${cmdSuffix}`);
      if (!auto) scrollPopoverModule('console');
    }

    const url = `/api/run/${encodeURIComponent(key)}${refresh ? '?refresh=1' : ''}`;
    let res;
    submitInFlightKeys.add(key);
    try {
      for (let attempt = 0; attempt < 2; attempt++) {
      if (cancelInFlight) return false;
      try {
        res = await fetchWithTimeoutAndProbe(url, { method: 'POST' });
      } catch (err) {
        logEvent('error', `[client] cannot reach server: ${err}`);
        setStatus('failed');
        return false;
      }
      if (res.status !== 409) break;
      // Benign: key already in flight, or a just-cancelled run still holds the
      // server's active slot. Re-sync; retry once only if the server queue is free.
      const txt = await res.text().catch(() => '');
      logEvent('info', `[${src.label}: ${txt || 'already in flight'} - re-syncing queue]`);
      await syncFromServer();
      const canRetry =
        attempt === 0
        && !cancelInFlight
        && !runStateByKey.has(key)
        && !isQueueFullForKey(key);
      if (!canRetry) return false;
      await new Promise(r => setTimeout(r, 600));
      }
      if (res.status === 409) return false;
      if (!res.ok) {
        invalidateApiProbe();
        const txt = await res.text().catch(() => '');
        logEvent('error', `[server ${res.status}] ${txt || 'submit failed'}`);
        setStatus('failed');
        markChipState(key, null);
        return false;
      }
      const { run_id: runId } = await res.json();
      markChipState(key, 'queued', runId);
      ensureInFlightPolling();
      let snapAfterSubmit = null;
      try {
        snapAfterSubmit = await fetchRunsSnapshot();
      } catch (_) {}
      const queueExtra = queueStatusExtra(snapAfterSubmit, runId);
      if (queueExtra) {
        logEvent('info', `(queue ${queueExtra})`);
        syncLogPanelChrome(src, 'queued', queueExtra);
      } else if (snapAfterSubmit?.active?.id === runId) {
        syncLogPanelChrome(src, snapAfterSubmit.active.status);
      } else if (liveRunId && liveRunId !== runId) {
        const liveSrc = sourcesByRunId.get(liveRunId)?.src;
        logEvent('info', `(queued after ${liveSrc?.label || 'current run'})`);
      }
      // Only hold an SSE for the active run — queued runs attach when promoted.
      if (snapAfterSubmit?.active?.id === runId || !queueExtra) {
        subscribe(runId, key, src);
      }
    } finally {
      submitInFlightKeys.delete(key);
    }
    return true;
  }

  async function runBatchKeys(keys, { logPrefix = 'batch', runFn = run } = {}) {
    if (!keys.length) return;
    const batchEpoch = getCancelEpoch();
    for (const key of keys) {
      if (getCancelEpoch() !== batchEpoch) {
        logEvent('info', `[${logPrefix} aborted: cancelled]`);
        break;
      }
      try {
        await waitForQueueSlot({ batchEpoch, key });
        if (getCancelEpoch() !== batchEpoch) {
          logEvent('info', `[${logPrefix} aborted: cancelled]`);
          break;
        }
        await runFn(key);
      } catch (err) {
        if (err?.message === 'cancelled') {
          logEvent('info', `[${logPrefix} aborted: cancelled]`);
        } else {
          logEvent('error', `[${logPrefix} aborted: ${err}]`);
        }
        break;
      }
    }
  }

  async function runAllStale() {
    if (!isApiAvailable()) return;
    batchRunCooldowns.staleUntil = Date.now() + 2000;
    renderDashboardFetcherHealth();
    await loadFetcherSources(true);
    const staleKeys = resolveStaleSweepKeys(fetcherSources, {
      freshnessStatus: (src) => fetcherFreshness(src).status,
      credentialsSatisfied: fetcherCredentialsSatisfied,
      hasRunState: (key) => runStateByKey.has(key),
      cooldownMs: (key) => authCooldownRemainingMs(key),
      disconnected: (key) => isFetcherDisconnected(key),
    });
    if (!staleKeys.length) return;
    await runBatchKeys(staleKeys, { logPrefix: 'run stale' });
  }

  async function runAllFailed() {
    if (!isApiAvailable()) return;
    batchRunCooldowns.failedUntil = Date.now() + 2000;
    renderDashboardFetcherHealth();
    await loadFetcherSources(true);
    const failedKeys = fetcherSources
      .filter(src => {
        const key = src.key;
        if (!lastRunFailedByKey.has(key)) return false;
        if (runStateByKey.has(key)) return false;
        if (authCooldownRemainingMs(key) > 0) return false;
        if (isFetcherDisconnected(key)) return false;
        if (src.missingRequirements?.length && !fetcherCredentialsSatisfied(key)) return false;
        return true;
      })
      .map(src => src.key)
      .sort((a, b) => (source(a)?.label || a).localeCompare(source(b)?.label || b));
    if (!failedKeys.length) return;
    await runBatchKeys(failedKeys, { logPrefix: 'retry failed' });
  }

  async function subscribe(runId, key, src, { reconnect = false, quiet = false, queuedOnly = false } = {}) {
    if (suppressedRunIds.has(runId) || cancelInFlight || queuedOnly) return;
    // Keep live SSE log streams closed while the page is hidden: the auto-fetch
    // loop and /api/runs polling keep working (Phase 1), but there's no log view
    // to feed. On resume, syncFromServer re-subscribes to any active run.
    if (isPageHidden()) return;
    clearReconnect(runId);
    const prior = sourcesByRunId.get(runId);
    if (prior) {
      sourcesByRunId.delete(runId);
      prior.es.onerror = null;
      try { prior.es.close(); } catch (_) {}
    }
    let esUrl;
    try {
      esUrl = await urlWithStreamTicket(streamUrl(runId), { runId });
    } catch (_) {
      scheduleReconnect(runId, key, src, { queuedOnly });
      return;
    }
    const es = new EventSource(esUrl);
    sourcesByRunId.set(runId, { es, key, src });
    const recentLog = [];

    es.addEventListener('status', evt => {
      try {
        const data = JSON.parse(evt.data);
        if (data.status === 'running' || data.status === 'launching') {
          markChipState(key, 'running', runId);
          liveRunId = runId;
          if (liveRunId === runId) syncLogPanelChrome(src, data.status);
          if (reconnect) {
            if (!quiet) {
              const stateWord = data.status === 'launching' ? 'launching' : 'running';
              logEvent('info', `[reconnected · ${src.label} ${stateWord}]`);
            }
          } else {
            logEvent('info', `--- ${src.label} starting ---`);
          }
          updateCancelButton();
        } else if (data.status === 'queued') {
          markChipState(key, 'queued', runId);
        } else if (data.status === 'cancelling') {
          markChipState(key, 'running', runId);
          if (liveRunId === runId) syncLogPanelChrome(src, 'cancelling');
        }
      } catch (_) {}
    });

    es.addEventListener('line', evt => {
      try {
        const data = JSON.parse(evt.data);
        if (evt.lastEventId) recordLineSeq(runId, evt.lastEventId);
        else if (data.seq != null) recordLineSeq(runId, data.seq);
        const text = data.text || '';
        recentLog.push(text);
        if (recentLog.length > 40) recentLog.shift();
        appendLine(text, data.stream === 'stderr' ? 'stderr' : 'stdout');
      } catch (_) {}
    });

    es.addEventListener('done', async evt => {
      flushLinesNow();
      try {
        const data = JSON.parse(evt.data);
        const cancelled = data.status === 'cancelled';
        const ok = data.status === 'done' && data.exit_code === 0;
        const duration = data.started_at && data.ended_at
          ? `${(data.ended_at - data.started_at).toFixed(1)}s`
          : '';
        const outcome = cancelled ? 'cancelled' : ok ? 'done' : 'failed';
        logEvent(
          'info',
          `[${src.label}: exit ${data.exit_code}] ${outcome}${duration ? ` in ${duration}` : ''}`,
        );
        flushLinesNow();
        if (liveRunId === runId) {
          setStatus(cancelled ? 'failed' : ok ? 'done' : 'failed', duration);
          updateCancelButton();
        }
        if (ok) {
          lastRunFailedByKey.delete(key);
          fetchSuccessLabels.add(src.label || key);
          // Clear the chip before client-side reload so a slow hosted-feed merge
          // cannot leave the claims fetcher spinning after the subprocess exited.
          markChipState(key, null);
          if (runId !== _lastAppliedDoneRunId) {
            _lastAppliedDoneRunId = runId;
            await refreshAfterFetch(key);
          }
          clearAuthCooldown(key);
          const provider = FETCHER_AUTH_PROVIDER[key];
          if (provider) {
            clearReconnectRequired(provider);
            clearReconnectBanner(provider);
          }
        } else if (cancelled) {
          markChipState(key, null);
        } else {
          lastRunFailedByKey.set(key, Date.now());
          markChipState(key, 'failed');
          handleFetcherAuthOutcome(key, data, recentLog.join('\n'));
          setTimeout(() => {
            if (runStateByKey.get(key) === 'failed') {
              runStateByKey.delete(key);
              renderDashboardFetcherHealth();
            }
          }, 10000);
        }
      } catch (err) {
        logEvent('error', `[client] parse error on done: ${err}`);
      } finally {
        clearReconnect(runId);
        reconnectAttempts.delete(runId);
        clearLastSeq(runId);
        try { es.close(); } catch (_) {}
        sourcesByRunId.delete(runId);
        if (liveRunId === runId) {
          liveRunId = null;
          updateCancelButton();
        }
        revertFetcherLayoutIfIdle();
      }
    });

    es.onerror = async () => {
      if (suppressedRunIds.has(runId) || cancelInFlight) return;
      const attached = sourcesByRunId.get(runId);
      if (!attached || attached.es !== es) return;
      // Let the browser retry with the same ticket URL (multi-use tickets on the server).
      if (es.readyState === EventSource.CONNECTING) return;
      sourcesByRunId.delete(runId);
      es.onerror = null;
      try { es.close(); } catch (_) {}
      try {
        const snap = await fetchRunsSnapshot();
        if (!snap) throw new Error('no snapshot');
        const stillActive = snap.active?.id === runId;
        const inQueue = (snap.queue || []).some(r => r.id === runId);
        const finished = (snap.history || []).find(r => r.id === runId);
        if (stillActive || inQueue) {
          const queuedOnly = inQueue && !stillActive;
          scheduleReconnect(runId, key, src, { queuedOnly });
          return;
        }
        if (finished) {
          const ok = finished.status === 'done' && finished.exit_code === 0;
          logEvent('info', `[${src.label}: stream dropped after exit ${finished.exit_code}]`);
          if (liveRunId === runId) setStatus(ok ? 'done' : 'failed');
          if (ok) fetchSuccessLabels.add(src.label || key);
          if (ok) markChipState(key, null);
          if (ok && finished.id !== _lastAppliedDoneRunId) {
            _lastAppliedDoneRunId = finished.id;
            await refreshAfterFetch(key);
          }
          if (!ok && finished.status === 'done') {
            handleFetcherAuthOutcome(key, finished, '');
          }
          if (liveRunId === runId) liveRunId = null;
          return;
        }
      } catch (_) {}
      logEvent(
        'error',
        `[${src.label}: stream error - server stopped, too many tabs, or connection limit (${MAX_SSE_HINT})]`,
      );
      if (liveRunId === runId) {
        setStatus('failed');
        liveRunId = null;
      }
      markChipState(key, null);
    };
  }

  async function refreshAfterFetch(key) {
    try {
      if (reloadAfterFetcherFn) await reloadAfterFetcherFn(key);
      else await reloadGamesFn();
    } catch (err) {
      logEvent('error', `[client] reload failed: ${err}`);
    }
    renderDashboardFetcherHealth();
    startFastAgeTick();
  }

  /** Re-attach SSE streams after a page load (or tab return). */
  async function syncFromServer() {
    if (!isApiAvailable()) return;
    await syncReconnectFromAuthStatus();
    await loadFetcherSources(true);
    let snap;
    try {
      snap = await fetchRunsSnapshot();
      if (!snap) {
        invalidateApiProbe();
        return;
      }
    } catch {
      invalidateApiProbe();
      return;
    }
    applyServerSnapshotInFlight(snap);
    pruneSuppressedRuns(snap);
    reconcileRunStateFromSnapshot(snap);
    if (!isQueueFull()) {
      const { refreshPersistedErrorRing } = await import('../../error-boundary.js');
      refreshPersistedErrorRing();
    }

    const pending = [];
    if (snap.active) pending.push(snap.active);
    for (const q of snap.queue || []) pending.push(q);

    const visiblePending = pending.filter(r => !suppressedRunIds.has(r.id));
    if (visiblePending.length) {
      const panelSrc = source(snap.active?.key) || source(visiblePending[0].key);
      ensurePanel(panelSrc);
      const isFirstSync = !syncedOnce;
      syncedOnce = true;
      if (isFirstSync) {
        const parts = [];
        if (snap.active && !suppressedRunIds.has(snap.active.id)) {
          const aLabel = source(snap.active.key)?.label || snap.active.key;
          const aState = snap.active.status === 'launching'
            ? 'launching'
            : snap.active.status === 'cancelling'
              ? 'cancelling'
              : 'running';
          parts.push(`${aLabel} ${aState}`);
        }
        for (const q of snap.queue || []) {
          if (suppressedRunIds.has(q.id)) continue;
          const qLabel = source(q.key)?.label || q.key;
          parts.push(`${qLabel} queued`);
        }
        if (parts.length) {
          logEvent('info', `[reconnected · ${parts.join(', ')}]`);
        }
      }
      for (const run of visiblePending) {
        const src = source(run.key);
        if (!src) continue;
        const chipState = serverChipState(run.status) || 'queued';
        markChipState(run.key, chipState, run.id);
        if (run.status === 'running' || run.status === 'launching' || run.status === 'cancelling') {
          liveRunId = run.id;
        }
        if (run.status === 'cancelling') continue;
        if (sourcesByRunId.has(run.id)) continue;
        if (run.status === 'queued' && snap.active?.id !== run.id) continue;
        subscribe(run.id, run.key, src, { reconnect: true, quiet: true });
      }
      updateCancelButton();
      if (snap.active && panelSrc) {
        const st = snap.active.status;
        if (st === 'cancelling') syncLogPanelChrome(panelSrc, 'cancelling');
        else if (st === 'launching' || st === 'running') syncLogPanelChrome(panelSrc, st);
        else syncLogPanelChrome(panelSrc, 'running');
      } else if (snap.queue?.length) {
        const qRun = snap.queue[0];
        const qSrc = source(qRun.key) || panelSrc;
        if (qSrc) {
          const qExtra = queueStatusExtra(snap, qRun.id);
          syncLogPanelChrome(qSrc, 'queued', qExtra || undefined);
        }
      }
      ensureInFlightPolling();
      renderDashboardFetcherHealth();
      updateGlobalFetcherIndicator(runStateByKey, source);
      return;
    }

    reconcileRunStateFromSnapshot(snap);
    updateCancelButton();
    updateGlobalFetcherIndicator(runStateByKey, source);
    const recentDone = (snap.history || []).find(r => {
      if (r.status !== 'done' || r.exit_code !== 0 || !r.ended_at) return false;
      return Date.now() - r.ended_at * 1000 < 5 * 60_000;
    });
    if (recentDone && recentDone.id !== _lastAppliedDoneRunId) {
      _lastAppliedDoneRunId = recentDone.id;
      await refreshAfterFetch(recentDone.key);
    }
  }

  async function _runDashboardPollTick() {
    // Intentionally not gated on page visibility: the auto-fetch loop keeps
    // running while the window is minimized/unfocused (best-effort, subject to
    // browser background-timer throttling).
    await syncFromServer();
    maybeAutoRefreshItad(autoRefreshDeps());
    maybeAutoRefreshClaims(autoRefreshDeps());
    maybeAutoFetchStale24h(autoRefreshDeps());
  }

  function startDashboardPolling() {
    _dashboardPollWanted = true;
    if (pollTimer || !isApiAvailable()) return;
    void syncFromServer().then(() => {
      maybeAutoRefreshItad(autoRefreshDeps());
      maybeAutoRefreshClaims(autoRefreshDeps());
      maybeAutoFetchStale24h(autoRefreshDeps());
    });
    pollTimer = setInterval(() => { void _runDashboardPollTick(); }, 30_000);
  }

  function stopDashboardPolling() {
    _dashboardPollWanted = false;
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    stopInFlightPolling();
    stopAgeTicker();
    stopFastAgeTick();
  }

  if (typeof document !== 'undefined') {
    registerPausable({
      pause() {
        // Keep the dashboard + in-flight poll loops running while hidden so a
        // minimized/unfocused window still auto-refreshes (Phase 1). Only the
        // live SSE log streams are closed, since their output isn't visible.
        closeAllStreams();
      },
      resume() {
        // Catch up immediately when the window returns to the foreground.
        syncFromServer().catch(() => {});
        if (_dashboardPollWanted && !pollTimer && isApiAvailable()) {
          pollTimer = setInterval(_runDashboardPollTick, 30_000);
        }
        if (runStateByKey.size > 0 || sourcesByRunId.size > 0 || lastServerInFlight) {
          ensureInFlightPolling();
        }
      },
    });
  }

  return {
    probeApi,
    invalidateApiProbe,
    isApiAvailable,
    apiProbeFinished,
    stateFor,
    inFlightCount,
    isQueueFull,
    isQueueFullForKey,
    waitForQueueSlot,
    run,
    runAllStale,
    runAllFailed,
    runBatchKeysForTest: runBatchKeys,
    syncFromServer,
    startDashboardPolling,
    stopDashboardPolling,
    closeAllStreams,
    reopenLogPanel,
    expandPanel,
    collapsePanel,
    toggleFetcherPanel,
    isFetcherRowExpanded,
    applyFetcherRowLayout,
    updateFetcherBar,
    revertFetcherLayoutIfIdle,
    showFetcherPopover,
    hideFetcherPopover,
    toggleFetcherPopover,
    openFetcherLog,
    isFetcherPopoverOpen,
    setBarSummary(text) {
      lastBarSummary = text;
    },
    syncLogHeightToCard,
    refreshGlobalIndicator() {
      updateGlobalFetcherIndicator(runStateByKey, source);
    },
    flushLinesNow,
    appendLineForTest(text, kind = 'stdout') {
      appendLine(text, kind);
    },
    logEventForTest(level, text) {
      logEvent(level, text);
    },
    logLevelKindForTest() {
      return { ...LOG_LEVEL_KIND };
    },
    setFollowTailForTest(val) {
      followTail = !!val;
      clearFollowTailIdleTimer();
    },
    syncLogPanelChrome,
    ensurePanelForTest(src, serverStatus, extra) {
      ensurePanel(src, serverStatus, extra);
    },
    fetchWithTimeout: fetchWithTimeoutAndProbe,
    cancelInFlightRuns,
    applyServerSnapshotInFlight,
    getLastServerInFlight: () => lastServerInFlight,
    streamUrlForTest: streamUrl,
    recordLineSeqForTest: recordLineSeq,
    getLastSeqForTest: getLastSeq,
    reconcileRunStateFromSnapshot,
    isCancelInFlightForTest: () => cancelInFlight,
    getInFlightCountForTest: () => runStateByKey.size,
    getCancelEpoch,
    bumpCancelEpochForTest: bumpCancelEpoch,
    setCancelInFlightForTest(val) {
      cancelInFlight = !!val;
    },
    markChipStateForTest(key, state, runId = null) {
      markChipState(key, state, runId);
    },
    markRunFailedForTest(key) {
      lastRunFailedByKey.set(key, Date.now());
    },
    clearRunFailedForTest(key) {
      lastRunFailedByKey.delete(key);
    },
    resetPillAggregatesForTest() {
      lastRunFailedByKey.clear();
      fetchSuccessLabels.clear();
    },
    isRunFailedForTest(key) {
      return lastRunFailedByKey.has(key);
    },
    cycleStatLayout,
  };
})();
