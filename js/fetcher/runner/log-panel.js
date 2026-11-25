/** Fetcher log popover, inline row layout, and log panel chrome DOM. */
import { state } from '../../state.js';
import { savePrefs } from '../../prefs.js';
import { bindEscapeClose, trapFocus } from '../../focus-trap.js';
import {
  LOG_PANEL_CHROME_HTML,
  LOG_EMPTY_MESSAGE,
  logCollapseLabel,
} from '../../fetcher-health-log.js';
import { renderDashboardFetcherHealth } from '../render/dashboard.js';
import { updateGlobalFetcherIndicator } from '../global-indicator.js';
import { wireStallRetryOnce } from './stall-notice.js';

const LOG_DESKTOP_MQ = '(min-width: 1024px)';
const FETCHER_SHEET_MQ =
  '(max-width: 639.98px), (max-height: 480px) and (hover: none)';

/**
 * @param {object} deps
 * @param {() => boolean} deps.isFetcherInFlight
 * @param {Map<string, string>} deps.runStateByKey
 * @param {(key: string) => { label?: string; key?: string } | null} deps.source
 * @param {() => string} deps.getLastLineText
 * @param {() => string} deps.getLastLineKind
 * @param {() => string} deps.getLastBarSummary
 * @param {(text: string) => void} deps.setLastBarSummary
 * @param {() => boolean} deps.isApiAvailable
 * @param {() => number} deps.cancellableCount
 * @param {() => boolean} deps.getLastServerInFlight
 * @param {() => boolean} deps.getCancelInFlight
 * @param {(opts?: { force?: boolean }) => void} deps.cancelInFlightRuns
 * @param {() => void} deps.clearLog
 * @param {() => void} deps.scrollLogToBottom
 * @param {() => boolean} deps.getFollowTail
 * @param {(val: boolean) => void} deps.setFollowTail
 * @param {() => void} deps.clearFollowTailIdleTimer
 * @param {() => void} deps.scheduleFollowTailIdle
 * @param {Set<string>} deps.fetchSuccessLabels
 */
export function createLogPanelHelpers(deps) {
  let logEl = null;
  let logBodyEl = null;
  let fetcherPopoverRelease = null;
  let fetcherSheetMqWired = false;
  let forceExpanded = false;
  let suppressAutoExpand = false;
  let logHeightCardObs = null;
  let logHeightResizeWired = false;

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

  function isFetcherSheetViewport() {
    return typeof window !== 'undefined'
      && typeof window.matchMedia === 'function'
      && window.matchMedia(FETCHER_SHEET_MQ).matches;
  }

  /** Phone: fullscreen sheet class. Tablet/desktop keep anchored popover math-free CSS. */
  function syncFetcherPopoverSheetClass(pop = fetcherPopoverEl()) {
    if (!pop) return;
    pop.classList.toggle('fetcher-popover--sheet', isFetcherSheetViewport());
  }

  function ensureFetcherSheetMq() {
    if (fetcherSheetMqWired || typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return;
    }
    fetcherSheetMqWired = true;
    const mq = window.matchMedia(FETCHER_SHEET_MQ);
    const onChange = () => {
      const pop = fetcherPopoverEl();
      if (!pop || pop.hidden) return;
      syncFetcherPopoverSheetClass(pop);
    };
    if (mq.addEventListener) mq.addEventListener('change', onChange);
    else mq.addListener(onChange);
  }

  function hideFetcherPopover() {
    fetcherPopoverRelease?.();
    fetcherPopoverRelease = null;
    const pop = fetcherPopoverEl();
    const bd = document.getElementById('fetcherPopoverBackdrop');
    const pill = document.getElementById('fetcherGlobalStatus');
    if (bd) bd.hidden = true;
    if (pop) {
      pop.hidden = true;
      pop.classList.remove('fetcher-popover--sheet');
    }
    if (pill) pill.setAttribute('aria-expanded', 'false');
    // Collapse the log console drawer so reopening the fetcher starts tidy.
    const panel = logPanel();
    if (panel && !panel.classList.contains('fh-log--collapsed')) {
      panel.classList.add('fh-log--collapsed');
      syncLogCollapseButton();
    }
    if (deps.isFetcherInFlight()) suppressAutoExpand = true;
  }

  function showFetcherPopover({ focusPanel = true } = {}) {
    if (typeof document !== 'undefined' && document.documentElement.hasAttribute('data-boot-loading')) {
      return false;
    }
    const pop = fetcherPopoverEl();
    const bd = document.getElementById('fetcherPopoverBackdrop');
    if (!pop || !bd) return false;
    ensureFetcherSheetMq();
    syncFetcherPopoverSheetClass(pop);
    bd.hidden = false;
    pop.hidden = false;
    const pill = document.getElementById('fetcherGlobalStatus');
    if (pill) pill.setAttribute('aria-expanded', 'true');
    forceExpanded = true;
    suppressAutoExpand = false;
    deps.fetchSuccessLabels.clear();
    updateGlobalFetcherIndicator(deps.runStateByKey, deps.source);
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
        const log = logPanel();
        if (log) {
          const logRect = log.getBoundingClientRect();
          const scRect = scroller.getBoundingClientRect();
          scroller.scrollTop += logRect.top - scRect.top - 8;
        } else {
          scroller.scrollTop = scroller.scrollHeight;
        }
      } else {
        scroller.scrollTop = 0;
      }
    });
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
    for (const [key, st] of deps.runStateByKey) {
      const src = deps.source(key);
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
    return deps.getLastBarSummary();
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
      tailEl.textContent = deps.getLastLineText() || 'No fetcher activity yet.';
      tailEl.className = `fh-bar-tail${deps.getLastLineKind() === 'stderr' ? ' stderr' : ''}`;
    }
    if (dotEl) dotEl.classList.toggle('is-live', deps.isFetcherInFlight());
    if (toggleEl) {
      toggleEl.textContent = expanded ? '▾' : '▸';
      toggleEl.classList.toggle('is-open', expanded);
      toggleEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      toggleEl.setAttribute('aria-label', expanded ? 'Collapse fetcher' : 'Expand fetcher');
    }
  }

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
    if (deps.getFollowTail()) deps.scrollLogToBottom();
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
    if (deps.isFetcherInFlight()) return;
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
      if (deps.isFetcherInFlight()) suppressAutoExpand = true;
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
    wireStallRetryOnce(panel, () => deps.cancelInFlightRuns({ force: true }));
    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-role]');
      if (!btn) return;
      if (btn.dataset.role === 'close') toggleLogBody();
      else if (btn.dataset.role === 'clear') deps.clearLog();
      else if (btn.dataset.role === 'cancel') deps.cancelInFlightRuns({ force: e.shiftKey });
      else if (btn.dataset.role === 'jump') deps.scrollLogToBottom();
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
      deps.setFollowTail(true);
      deps.clearFollowTailIdleTimer();
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
    const show = deps.isApiAvailable() && (deps.cancellableCount() > 0 || deps.getLastServerInFlight());
    btn.classList.toggle('hidden', !show);
    if (deps.getCancelInFlight()) {
      btn.disabled = true;
      btn.textContent = 'Cancelling…';
      btn.title = 'Stopping queued and running fetchers and enrichers…';
    } else {
      btn.disabled = !show;
      btn.textContent = 'Cancel';
      btn.title = 'Stop all queued and running fetchers and enrichers (Shift+click: force-reset both lanes)';
    }
  }

  function onLogBodyScroll(body) {
    if (logNearBottom(body)) {
      deps.setFollowTail(true);
      deps.clearFollowTailIdleTimer();
    } else {
      deps.setFollowTail(false);
      deps.scheduleFollowTailIdle();
    }
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

  return {
    logPanel,
    logBody,
    showFetcherPopover,
    hideFetcherPopover,
    toggleFetcherPopover,
    openFetcherLog,
    isFetcherPopoverOpen,
    isFetcherSheetViewport,
    syncFetcherPopoverSheetClass,
    scrollPopoverModule,
    isFetcherRowExpanded,
    updateFetcherBar,
    applyFetcherRowLayout,
    revertFetcherLayoutIfIdle,
    expandPanel,
    collapsePanel,
    toggleFetcherPanel,
    syncLogHeightToCard,
    buildLogPanelChrome,
    ensurePanel,
    reopenLogPanel,
    updateCancelButton,
    setStatus,
    syncLogPanelChrome,
    updateJumpButton,
    logNearBottom,
  };
}