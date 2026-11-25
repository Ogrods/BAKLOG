/**
 * Auto-refresh scheduling: ITAD, claims, stale-24h, connect, enrich.
 */
import {
  clearClaimsPendingAutoRun,
  markClaimsPendingAutoRun,
} from './claimable.js';
import { FETCHER_AUTH_PROVIDER, NO_AUTO_FETCH_KEYS } from './fetcher-registry.js';
import {
  clearItadPendingAutoRun,
  fetcherRunner,
  fetcherSources,
  markItadPendingAutoRun,
} from './fetcher-health-shared.js';
import {
  LS_AUTO_STALE_LAST_RUN,
  LS_CLAIMS_LAST_AUTO_RUN,
  LS_ITAD_LAST_AUTO_RUN,
  profileScopedStorageKey,
} from './profiles.js';
import { ENRICH_ORDER } from './fetcher/enrich-order.js';
import { state } from './state.js';

/** Defaults wired from fetcher-health.js after module init (avoids import cycles). */
let wired = {};

export function wireFetcherAutoRefresh(modules) {
  wired = { ...wired, ...modules };
}

const ITAD_SOURCE_DEFAULT = { key: 'itad', metaKey: 'itad' };
const CLAIMS_SOURCE_DEFAULT = { key: 'claims', metaKey: 'claims' };

export function itadLastAutoRunKey() {
  return profileScopedStorageKey(LS_ITAD_LAST_AUTO_RUN);
}

export function claimsLastAutoRunKey() {
  return profileScopedStorageKey(LS_CLAIMS_LAST_AUTO_RUN);
}

/** Drop claims auto-refresh cooldown entirely (tests / manual reset). */
export function clearClaimsLastAutoRun(deps = {}) {
  const clearFn = deps.clearLastRun
    ?? (() => {
      try { localStorage.removeItem(claimsLastAutoRunKey()); } catch (_) {}
    });
  clearFn();
}

/**
 * After a failed/cancelled auto-refresh run, delay the next attempt without
 * burning the full user interval (and without retrying every 30s poll).
 * Gate is (now - lastRun) < interval → lastRun = now - interval + backoff.
 */
export const CLAIMS_AUTO_FAIL_BACKOFF_MS = 15 * 60_000;
export const ITAD_AUTO_FAIL_BACKOFF_MS = 5 * 60_000;

function noteAutoRunFailed(deps, {
  intervalMs,
  backoffMs,
  defaultSetLastRun,
}) {
  const now = deps.now ?? Date.now();
  const interval = deps.intervalMs ?? intervalMs;
  const backoff = Math.min(deps.backoffMs ?? backoffMs, interval);
  const setLastRun = deps.setLastRun ?? defaultSetLastRun;
  setLastRun(now - interval + backoff);
}

export function noteClaimsAutoRunFailed(deps = {}) {
  noteAutoRunFailed(deps, {
    intervalMs: claimsAutoRefreshIntervalMs(),
    backoffMs: CLAIMS_AUTO_FAIL_BACKOFF_MS,
    defaultSetLastRun: (t) => {
      try { localStorage.setItem(claimsLastAutoRunKey(), String(t)); } catch (_) {}
    },
  });
}

export function noteItadAutoRunFailed(deps = {}) {
  noteAutoRunFailed(deps, {
    intervalMs: itadAutoRefreshIntervalMs(),
    backoffMs: ITAD_AUTO_FAIL_BACKOFF_MS,
    defaultSetLastRun: (t) => {
      try { localStorage.setItem(itadLastAutoRunKey(), String(t)); } catch (_) {}
    },
  });
}

/**
 * Auto-cycle latch (claims/ITAD). Set at POST accept; cleared on success or
 * after fail/cancel backoff. Kept separate from the banner pending flags so a
 * mid-run consumeClaims/ItadAutoRunFlag cannot skip fail backoff, and a manual
 * chip fail cannot rewrite lastRun.
 */
const autoRefreshCycleArmed = { claims: false, itad: false };

/** Soften claims/ITAD auto cooldown after fail/cancel when a cycle was armed. */
export function noteFetcherAutoRefreshFailed(key, deps = {}) {
  if (key === 'claims') {
    clearClaimsPendingAutoRun();
    if (!autoRefreshCycleArmed.claims) return;
    autoRefreshCycleArmed.claims = false;
    noteClaimsAutoRunFailed(deps);
  } else if (key === 'itad') {
    clearItadPendingAutoRun();
    if (!autoRefreshCycleArmed.itad) return;
    autoRefreshCycleArmed.itad = false;
    noteItadAutoRunFailed(deps);
  }
}

/**
 * Stamp the full auto-refresh interval at POST accept (before snapshot/SSE)
 * and arm the auto-cycle latch. Fail/cancel overwrites via
 * noteFetcherAutoRefreshFailed so a later maybeAutoRefresh setLastRun cannot
 * replace a short fail backoff.
 */
export function noteFetcherAutoRefreshSubmitted(key, deps = {}) {
  const now = deps.now ?? Date.now();
  if (key === 'claims') {
    autoRefreshCycleArmed.claims = true;
    const setLastRun = deps.setLastRun
      ?? ((t) => {
        try { localStorage.setItem(claimsLastAutoRunKey(), String(t)); } catch (_) {}
      });
    setLastRun(now);
  } else if (key === 'itad') {
    autoRefreshCycleArmed.itad = true;
    const setLastRun = deps.setLastRun
      ?? ((t) => {
        try { localStorage.setItem(itadLastAutoRunKey(), String(t)); } catch (_) {}
      });
    setLastRun(now);
  }
}

/** Drop the auto-cycle latch on successful exit without applying fail backoff. */
export function clearFetcherAutoRefreshCycle(key) {
  if (key === 'claims') autoRefreshCycleArmed.claims = false;
  else if (key === 'itad') autoRefreshCycleArmed.itad = false;
}

/** Arm pending-auto banners only after a successful POST submit. */
export function armPendingAutoRunBanner(key) {
  if (key === 'itad') markItadPendingAutoRun();
  else if (key === 'claims') markClaimsPendingAutoRun();
}

export const ITAD_AUTO_REFRESH_INTERVAL_MS = 15 * 60_000;
export const ITAD_AUTO_QUIET_HOUR_END = 7;

/** User-configured ITAD auto-refresh interval (15–60 min) from prefs. */
export function itadAutoRefreshIntervalMs() {
  const min = Number(state.prefs?.itadAutoRefreshIntervalMin);
  if (!Number.isFinite(min)) return ITAD_AUTO_REFRESH_INTERVAL_MS;
  return Math.min(60, Math.max(15, min)) * 60_000;
}

export const CLAIMS_AUTO_REFRESH_INTERVAL_MS = 120 * 60_000;

/** User-configured free-claims auto-refresh interval (30–360 min) from prefs. */
export function claimsAutoRefreshIntervalMs() {
  const min = Number(state.prefs?.claimsAutoRefreshIntervalMin);
  if (!Number.isFinite(min)) return CLAIMS_AUTO_REFRESH_INTERVAL_MS;
  return Math.min(360, Math.max(30, min)) * 60_000;
}

export const AUTO_STALE_AGE_MS = 24 * 60 * 60 * 1000;
export const AUTO_STALE_STAGGER_MS = 30 * 60 * 1000;

export function autoStaleLastRunKey() {
  return profileScopedStorageKey(LS_AUTO_STALE_LAST_RUN);
}

let autoEnrichCooldownUntil = 0;
const AUTO_ENRICH_COOLDOWN_MS = 3000;

/**
 * Queue enrichers in ENRICH_ORDER (reviews → tags → covers → ProtonDB → HLTB).
 * @param {{ logLabel: string, deps?: Record<string, unknown> }} opts
 * @returns {Promise<boolean>}
 */
async function queueEnrichersInOrder({ logLabel, deps = {} }) {
  const now = deps.now ?? Date.now();
  if (now < autoEnrichCooldownUntil) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner?.isApiAvailable());
  if (!isApiAvailableFn()) return false;

  autoEnrichCooldownUntil = now + AUTO_ENRICH_COOLDOWN_MS;

  const loadSourcesFn = deps.loadFetcherSources ?? (async () => {
    const m = await import('./fetcher-health.js');
    return m.loadFetcherSources(true);
  });
  await loadSourcesFn();

  const sources = deps.sources ?? fetcherSources;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner?.stateFor(k));
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner?.run(k, opts));
  const cancelEpochFn = deps.getCancelEpoch ?? (() => fetcherRunner?.getCancelEpoch());
  const batchEpoch = cancelEpochFn();
  const waitSlotFn =
    deps.waitForQueueSlot ?? (() => fetcherRunner?.waitForQueueSlot({ batchEpoch }));
  const credsOkFn = deps.fetcherCredentialsSatisfied ?? wired.fetcherCredentialsSatisfied;
  const cooldownFn = deps.authCooldownRemainingMs ?? wired.authCooldownRemainingMs;
  const disconnectedFn = deps.isFetcherDisconnected ?? wired.isFetcherDisconnected;

  const keysToRun = ENRICH_ORDER.filter(key => {
    const src = sources.find(s => s.key === key);
    if (!src) return false;
    if (src.missingRequirements?.length && !credsOkFn(key)) return false;
    if (stateForFn(key)) return false;
    if (cooldownFn(key) > 0) return false;
    if (disconnectedFn(key)) return false;
    return true;
  });

  if (!keysToRun.length) return false;

  const appendLineFn = deps.appendLine;
  if (appendLineFn) {
    appendLineFn(logLabel.replace('{n}', String(keysToRun.length)), 'meta');
  }

  for (const key of keysToRun) {
    if (cancelEpochFn() !== batchEpoch) {
      if (appendLineFn) appendLineFn('[auto-enrich aborted: cancelled]', 'meta');
      break;
    }
    try {
      await waitSlotFn();
      if (cancelEpochFn() !== batchEpoch) {
        if (appendLineFn) appendLineFn('[auto-enrich aborted: cancelled]', 'meta');
        break;
      }
      await runFn(key, { auto: true });
    } catch (err) {
      if (err?.message === 'cancelled') {
        if (appendLineFn) appendLineFn('[auto-enrich aborted: cancelled]', 'meta');
      } else if (appendLineFn) {
        appendLineFn(`[auto-enrich aborted: ${err}]`, 'stderr');
      }
      break;
    }
  }
  return true;
}

export async function maybeAutoRefreshItad(deps = {}) {
  if (state.prefs.itadAutoRefreshDisabled) return false;
  const disconnectedFn = deps.isFetcherDisconnected ?? wired.isFetcherDisconnected;
  if (disconnectedFn?.('itad')) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner?.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const getHour = deps.getHour ?? (() => new Date().getHours());
  if (getHour() < ITAD_AUTO_QUIET_HOUR_END) return false;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner?.stateFor(k));
  if (stateForFn('itad')) return false;
  const freshnessFn = deps.fetcherFreshness ?? wired.fetcherFreshness;
  const itadSource = deps.itadSource ?? wired.itadSource ?? ITAD_SOURCE_DEFAULT;
  const fresh = freshnessFn ? freshnessFn(itadSource) : { ageMs: Infinity };
  if (fresh.ageMs < itadAutoRefreshIntervalMs()) return false;
  const now = deps.now ?? Date.now();
  const lastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(itadLastAutoRunKey()) || 0));
  if (now - lastRun() < itadAutoRefreshIntervalMs()) return false;
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner?.run(k, opts));
  // Cooldown is stamped inside run() at POST accept (noteFetcherAutoRefreshSubmitted)
  // so a fail during snapshot wait can overwrite with the short backoff.
  return !!(await runFn('itad', { auto: true }));
}

export async function maybeAutoRefreshClaims(deps = {}) {
  if (state.prefs.claimsAutoRefreshDisabled) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner?.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner?.stateFor(k));
  if (stateForFn('claims')) return false;
  const freshnessFn = deps.fetcherFreshness ?? wired.fetcherFreshness;
  const claimsSource = deps.claimsSource ?? wired.claimsSource ?? CLAIMS_SOURCE_DEFAULT;
  const fresh = freshnessFn ? freshnessFn(claimsSource) : { ageMs: Infinity };
  if (fresh.ageMs < claimsAutoRefreshIntervalMs()) return false;
  const now = deps.now ?? Date.now();
  const lastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(claimsLastAutoRunKey()) || 0));
  if (now - lastRun() < claimsAutoRefreshIntervalMs()) return false;
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner?.run(k, opts));
  // Cooldown stamped in run() at POST accept; fail/cancel overwrites via
  // noteFetcherAutoRefreshFailed without a post-return setLastRun race.
  return !!(await runFn('claims', { auto: true }));
}

export async function maybeAutoFetchOnConnect(fetcherKeys, deps = {}) {
  if (state.prefs.autoFetchOnConnect === false) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner?.isApiAvailable());
  if (!isApiAvailableFn()) return false;

  const loadFn = deps.loadFetcherSources ?? (async () => {
    const m = await import('./fetcher-health.js');
    return m.loadFetcherSources(true);
  });
  await loadFn();

  const sources = deps.sources ?? fetcherSources;
  const keys = (fetcherKeys || []).filter((key) => {
    if (NO_AUTO_FETCH_KEYS.has(key)) return false;
    const src = sources.find((s) => s.key === key);
    if (!src) return false;
    if ((src.pausedReason || '').trim()) return false;
    return true;
  });
  if (!keys.length) return false;

  const openLogFn = deps.openFetcherLog ?? (() => fetcherRunner?.openFetcherLog({ focusPanel: false }));
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner?.run(k, opts));
  const waitFn = deps.waitForQueueSlot ?? ((o) => fetcherRunner?.waitForQueueSlot(o));
  const getCancelEpochFn = deps.getCancelEpoch ?? (() => fetcherRunner?.getCancelEpoch());

  openLogFn();
  const primaryKey = keys[0];
  if (typeof document !== 'undefined') {
    requestAnimationFrame(() => {
      document.querySelector(
        `#dashboardFetcherHealth .fh-chip[data-fetcher-key="${primaryKey}"]`,
      )?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  const batchEpoch = getCancelEpochFn();
  try {
    await waitFn({ batchEpoch });
    if (getCancelEpochFn() === batchEpoch) {
      await runFn(primaryKey, { auto: true });
    }
  } catch (err) {
    if (err?.message !== 'cancelled') {
      // Surface in fetcher log when wired; never leak as unhandledrejection.
      const logFn = deps.appendLine;
      if (logFn) logFn(`[auto-fetch on connect aborted: ${err}]`, 'stderr');
    }
  }
  return true;
}

export function maybeAutoFetchStale24h(deps = {}) {
  if (state.prefs.autoFetchStale24h !== true) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner?.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const inFlightFn = deps.inFlightCount ?? (() => fetcherRunner?.inFlightCount());
  if (inFlightFn() > 0) return false;

  const now = deps.now ?? Date.now();
  const getLastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(autoStaleLastRunKey()) || 0));
  if (now - getLastRun() < AUTO_STALE_STAGGER_MS) return false;

  const sources = deps.sources ?? fetcherSources;
  const freshnessFn = deps.fetcherFreshness ?? wired.fetcherFreshness;
  const credsFn = deps.fetcherCredentialsSatisfied ?? wired.fetcherCredentialsSatisfied;
  const stateForFn = deps.stateFor ?? ((k) => fetcherRunner?.stateFor(k));
  const cooldownFn = deps.authCooldownRemainingMs ?? wired.authCooldownRemainingMs;
  const disconnectedFn = deps.isFetcherDisconnected ?? wired.isFetcherDisconnected;
  const reconnectFn = deps.isFetcherReconnectRequired ?? wired.isFetcherReconnectRequired;

  const candidates = sources.filter((src) => {
    if (src.key === 'itad') return false;
    // Local launchers (GOG Galaxy, Amazon) can't refresh unattended — only
    // web/API stores auto-fetch. See fetchers/manifest.json autoFetch:false.
    if (NO_AUTO_FETCH_KEYS.has(src.key)) return false;
    if ((src.pausedReason || '').trim()) return false;
    if (!FETCHER_AUTH_PROVIDER[src.key]) return false;
    const { ageMs } = freshnessFn(src);
    if (ageMs < AUTO_STALE_AGE_MS) return false;
    if (src.missingRequirements?.length && !credsFn(src.key)) return false;
    if (stateForFn(src.key)) return false;
    if (cooldownFn(src.key) > 0) return false;
    if (disconnectedFn(src.key)) return false;
    if (reconnectFn(src.key)) return false;
    return true;
  });

  if (!candidates.length) return false;

  candidates.sort((a, b) => freshnessFn(b).ageMs - freshnessFn(a).ageMs);
  const pick = candidates[0];

  const setLastRun = deps.setLastRun
    ?? ((t) => localStorage.setItem(autoStaleLastRunKey(), String(t)));
  setLastRun(now);
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner?.run(k, opts));
  runFn(pick.key, { auto: true });
  return true;
}

export async function maybeAutoEnrichNewAdditions(newCount, deps = {}) {
  if (!state.prefs.autoEnrichOnAdd) return false;
  if (!newCount || newCount <= 0) return false;
  return queueEnrichersInOrder({
    logLabel: `[auto-enrich: ${newCount} new game(s) - queuing {n} enricher(s)]`,
    deps,
  });
}

/**
 * Bootstrap enrich after an explicit user offer (first Steam success).
 * Does not require newCount > 0 or autoEnrichOnAdd (caller already consented).
 * @param {Record<string, unknown>} [deps]
 */
export async function runEnrichBootstrap(deps = {}) {
  const reason = deps.reason || 'bootstrap';
  return queueEnrichersInOrder({
    logLabel: `[enrich-bootstrap: ${reason} - queuing {n} enricher(s)]`,
    deps,
  });
}
