/** Per-provider reconnect state + Connections navigation for fetcher chips. */
import { state } from '../state.js';
import {
  FETCHER_AUTH_PROVIDER,
  noteFetcherAuthFailure,
  showReconnectBanner,
  clearReconnectBanner,
  authStatusLoaded,
  providerStatus,
  ingestAuthStatusProviders,
  groupRepFor,
  isProviderConnected,
} from '../connections.js';
import {
  LS_RECONNECT_DISMISSED,
  profileScopedStorageKey,
} from '../profiles.js';
import {
  authCooldownDurationMs,
  authCooldownRemainingMs as cooldownRemainingMs,
  clearAuthCooldown,
  initAuthCooldowns,
  noteAuthCooldownStrike,
} from '../fetcher-cooldown.js';
import { lastRunFailedByKey } from '../fetcher-health-shared.js';
import { fetchWithTimeout } from './http.js';
import { maybeAutoFetchOnConnect } from '../fetcher-auto-refresh.js';

export { authCooldownDurationMs, clearAuthCooldown, noteAuthCooldownStrike };

let _renderDashboard = () => {};
let _refreshGlobalIndicator = () => {};

/** Wire dashboard refresh callbacks (avoids import cycles at load time). */
export function wireFetcherReconnect({ renderDashboardFetcherHealth, refreshGlobalIndicator } = {}) {
  if (typeof renderDashboardFetcherHealth === 'function') {
    _renderDashboard = renderDashboardFetcherHealth;
  }
  if (typeof refreshGlobalIndicator === 'function') {
    _refreshGlobalIndicator = refreshGlobalIndicator;
  }
}

/** Map manifest env keys to user-facing Connections guidance. */
export function humanizeMissingRequirements(missing) {
  if (!missing?.length) return '';
  const keys = new Set(missing);
  if (keys.has('STEAM_API_KEY') && keys.has('STEAM_ID')) return 'Steam not connected';
  if (keys.has('STEAM_API_KEY') || keys.has('STEAM_ID')) return 'Steam not connected';
  if (keys.has('GOG_AL')) return 'GOG not connected';
  if (keys.has('PSN_NPSSO')) return 'PlayStation not connected';
  if (keys.has('ITCH_API_KEY')) return 'itch.io API key missing';
  if (keys.has('ITAD_API_KEY')) return 'ITAD API key missing';
  if (keys.has('XBL_API_KEY')) return 'Xbox API key missing';
  return missing.join(', ');
}

// ---------------------------------------------------------------------------
// Chip-level auth-failure backoff (see fetcher-cooldown.js)
// ---------------------------------------------------------------------------
let _profileScopedFetcherStateReady = false;

/** Load profile-scoped LS after auth/profile id is known (call post-initAuthGate). */
export function ensureProfileScopedFetcherState() {
  if (_profileScopedFetcherStateReady) return;
  _profileScopedFetcherStateReady = true;
  initAuthCooldowns();
  reconnectDismissed = loadReconnectDismissedSet();
}

/** Remaining cooldown for a fetcher key in ms, or 0. Self-heals on expiry or
 *  when the mapped provider is reconnected. */
export function authCooldownRemainingMs(key) {
  ensureProfileScopedFetcherState();
  return cooldownRemainingMs(key, (k) => fetcherProviders(k).some(p => isProviderConnected(p)));
}

/** Dual-source library fetchers: any connected sibling satisfies chip gates. */
export const FETCHER_PROVIDER_GROUP = {
  amazon: ['amazon_web', 'amazon'],
  gog: ['gog', 'gog_galaxy'],
  itch: ['itch', 'itch_local'],
};

/** Auth provider keys that can satisfy a fetcher chip (group or single). */
export function fetcherProviders(key) {
  const group = FETCHER_PROVIDER_GROUP[key];
  if (group) return group;
  const single = FETCHER_AUTH_PROVIDER[key];
  return single ? [single] : [];
}

/** True when at least one provider in the fetcher's group is connected. */
export function fetcherCredentialsSatisfied(key) {
  return fetcherProviders(key).some(p => providerStatus(p) === 'connected');
}

/** Map manifest env keys to user-facing Connections guidance. */
// ---------------------------------------------------------------------------
// Per-provider reconnect-required (definitive auth / max-strike / server expired)
// ---------------------------------------------------------------------------
function reconnectDismissedLsKey() {
  return profileScopedStorageKey(LS_RECONNECT_DISMISSED);
}
/** @type {Set<string>} */
let reconnectDismissed = new Set();
/** @type {Map<string, { at: number }>} */
const reconnectRequiredByProvider = new Map();

function loadReconnectDismissedSet() {
  try {
    const raw = JSON.parse(localStorage.getItem(reconnectDismissedLsKey()) || '[]');
    return new Set(Array.isArray(raw) ? raw.filter(x => typeof x === 'string') : []);
  } catch (_) {
    return new Set();
  }
}

function persistReconnectDismissed() {
  try {
    localStorage.setItem(reconnectDismissedLsKey(), JSON.stringify([...reconnectDismissed]));
  } catch (_) { /* storage unavailable */ }
}

/** Mark a provider as needing reconnect (clears any prior dismiss). */
export function markReconnectRequired(provider) {
  if (!provider) return;
  reconnectRequiredByProvider.set(provider, { at: Date.now() });
  if (reconnectDismissed.delete(provider)) persistReconnectDismissed();
}

/** Clear reconnect-required for a provider (success or reconnected). */
export function clearReconnectRequired(provider) {
  if (!provider) return;
  reconnectRequiredByProvider.delete(provider);
  if (reconnectDismissed.delete(provider)) persistReconnectDismissed();
}

/** Fetcher chip keys whose mapped auth provider is `provider`. */
function fetcherKeysForProvider(provider) {
  return Object.keys(FETCHER_AUTH_PROVIDER).filter(
    k => FETCHER_AUTH_PROVIDER[k] === provider,
  );
}

/** A provider just reconnected (was reconnect-required -> connected): clear
 *  sticky failed/cooldown chip state so chips recover without a fresh run. */
function clearFailedStateForReconnectedProvider(provider) {
  for (const key of fetcherKeysForProvider(provider)) {
    lastRunFailedByKey.delete(key);
    clearAuthCooldown(key);
  }
}

/** User dismissed the inline reconnect chip affordance for this provider. */
export function dismissReconnectRequired(provider) {
  if (!provider) return;
  ensureProfileScopedFetcherState();
  reconnectDismissed.add(provider);
  persistReconnectDismissed();
}

export function isReconnectDismissed(provider) {
  ensureProfileScopedFetcherState();
  return reconnectDismissed.has(provider);
}

/** True when provider needs reconnect and user has not dismissed the chip hint. */
export function isProviderReconnectRequired(provider) {
  if (!provider) return false;
  ensureProfileScopedFetcherState();
  if (reconnectDismissed.has(provider)) return false;
  if (providerStatus(provider) === 'expired') return true;
  return reconnectRequiredByProvider.has(provider);
}

/** Fetcher chip key → reconnect-required via mapped auth provider(s). */
export function reconnectRequiredForFetcherKey(key) {
  return isFetcherReconnectRequired(key);
}

/** Apply reconnect / failed-chip recovery when auth status rows change.
 *  Must run before processAuthStatusTransitions so prevStatusByProvider still
 *  holds the prior status for transition detection. */
function applyAuthStatusProviderEffects(providers) {
  for (const p of providers || []) {
    if (p.status === 'expired') markReconnectRequired(p.key);
    else if (p.status === 'connected') {
      const prev = prevStatusByProvider.get(p.key);
      const transitionedToConnected = prev !== undefined && prev !== 'connected';
      const hadReconnectFlag = reconnectRequiredByProvider.has(p.key);
      clearReconnectRequired(p.key);
      clearReconnectBanner(p.key);
      if (transitionedToConnected || hadReconnectFlag) {
        clearFailedStateForReconnectedProvider(p.key);
      }
    }
  }
}

/** Sync reconnect-required from GET /api/auth/status (survives reload).
 *  Uses the shared timeout so a hung endpoint can't stall the sync loop. */
export async function syncReconnectFromAuthStatus() {
  try {
    const res = await fetchWithTimeout('/api/auth/status');
    if (!res.ok) return;
    const data = await res.json();
    ingestAuthStatusProviders(data.providers || []);
    applyAuthStatusProviderEffects(data.providers || []);
  } catch (_) { /* server offline or timed out */ }
}

const prevStatusByProvider = new Map();

/** Detect disconnected/expired → connected and optionally auto-fetch that provider's keys. */
export function processAuthStatusTransitions(providers, prevMap = prevStatusByProvider, deps = {}) {
  for (const p of providers || []) {
    const prev = prevMap.get(p.key);
    const transitioned = prev !== undefined && prev !== 'connected' && p.status === 'connected';
    if (transitioned) {
      const prefOn = deps.autoFetchOnConnect ?? (state.prefs.autoFetchOnConnect !== false);
      if (prefOn) {
        const runConnect = deps.maybeAutoFetchOnConnect ?? maybeAutoFetchOnConnect;
        void runConnect(p.fetcher_keys || [], deps);
      }
    }
    prevMap.set(p.key, p.status);
  }
  return prevMap;
}

export function resetAuthStatusTransitionsForTest() {
  prevStatusByProvider.clear();
}

// Re-render the dashboard chips the instant auth status changes anywhere
// (e.g. a connection made in the Connections tab), not just on the 30s poll.
// connections.js fires this from its single auth-status cache write.
if (typeof document !== 'undefined') {
  document.addEventListener('baklog:auth-status', ev => {
    const providers = ev?.detail?.providers || [];
    applyAuthStatusProviderEffects(providers);
    processAuthStatusTransitions(providers);
    try { _renderDashboard(); } catch (_) { /* not mounted */ }
    try { _refreshGlobalIndicator(); } catch (_) { /* runner not ready */ }
  });
  document.addEventListener('baklog:reconnect-dismiss', ev => {
    for (const p of ev?.detail?.providers || []) dismissReconnectRequired(p);
  });
}

/** Provider to reconnect for a fetcher chip (skipped when a sibling is already connected). */
export function reconnectProviderForFetcher(key) {
  if (fetcherCredentialsSatisfied(key)) return null;
  for (const p of fetcherProviders(key)) {
    if (isProviderReconnectRequired(p)) return p;
  }
  return null;
}

export function isFetcherReconnectRequired(key) {
  if (!authStatusLoaded()) return false;
  const providers = fetcherProviders(key);
  if (!providers.some(p => isProviderReconnectRequired(p))) return false;
  // Dual-source fetchers: suppress when a non-reconnect sibling is connected.
  if (FETCHER_PROVIDER_GROUP[key]) {
    const hasHealthySibling = providers.some(
      p => !isProviderReconnectRequired(p) && providerStatus(p) === 'connected',
    );
    if (hasHealthySibling) return false;
  }
  return true;
}

/** Provider/rail key to open in Connections when the chip should not run a fetch. */
export function connectionsNavigateProvider(key) {
  const providers = fetcherProviders(key);
  for (const p of providers) {
    if (isProviderReconnectRequired(p)) return groupRepFor(p);
  }
  if (isFetcherDisconnected(key)) {
    const cp = connectProviderForFetcher(key);
    return cp ? groupRepFor(cp) : null;
  }
  if (authCooldownRemainingMs(key) > 0 || lastRunFailedByKey.has(key)) {
    const cp = connectProviderForFetcher(key) || FETCHER_AUTH_PROVIDER[key];
    return cp ? groupRepFor(cp) : null;
  }
  return null;
}

/** First sticky failed fetcher that should route to Connections (pill + chips). */
export function primaryFailureNavigateTarget() {
  for (const key of lastRunFailedByKey.keys()) {
    const provider = connectionsNavigateProvider(key);
    if (provider) return { fetcherKey: key, provider };
  }
  return null;
}

/** Provider key to use for the chip Connect button when disconnected. */
export function connectProviderForFetcher(key) {
  const providers = fetcherProviders(key);
  if (!providers.length) return null;
  if (key === 'amazon') {
    if (providerStatus('amazon_web') === 'disconnected') return 'amazon_web';
    if (providerStatus('amazon') === 'disconnected') return 'amazon';
    return 'amazon_web';
  }
  if (key === 'gog') {
    if (providerStatus('gog') === 'disconnected') return 'gog';
    if (providerStatus('gog_galaxy') === 'disconnected') return 'gog_galaxy';
    return 'gog';
  }
  if (key === 'itch') {
    if (providerStatus('itch') === 'disconnected') return 'itch';
    if (providerStatus('itch_local') === 'disconnected') return 'itch_local';
    return 'itch';
  }
  return FETCHER_AUTH_PROVIDER[key] || null;
}

/** True when the fetcher has no connected sibling and cannot run without connecting. */
export function isFetcherDisconnected(key) {
  if (!authStatusLoaded()) return false;
  if (fetcherCredentialsSatisfied(key)) return false;
  const providers = fetcherProviders(key);
  if (!providers.length) return false;
  if (FETCHER_PROVIDER_GROUP[key]) {
    return providers.every(p => {
      const st = providerStatus(p);
      return st === 'disconnected' || st === 'unavailable' || !st;
    });
  }
  const single = FETCHER_AUTH_PROVIDER[key];
  return single ? providerStatus(single) === 'disconnected' : false;
}

export async function handleFetcherAuthOutcome(key, data, logText) {
  const authExit = data?.exit_code === 4 || data?.failure_kind === 'auth';
  if (authExit) {
    const provider = reconnectProviderForFetcher(key)
      || connectProviderForFetcher(key)
      || FETCHER_AUTH_PROVIDER[key];
    if (provider) {
      markReconnectRequired(provider);
      showReconnectBanner([provider]);
    }
    clearAuthCooldown(key);
    // Pull mark_invalid from the fetcher subprocess into the shared auth cache
    // so Connections shows "Session expired" without waiting for the 30s poll.
    try {
      await syncReconnectFromAuthStatus();
      _renderDashboard();
    } catch (_) {}
    return;
  }
  const authish = noteFetcherAuthFailure(key, logText);
  if (authish) noteAuthCooldownStrike(key);
}

