import { baklogFetch, urlWithStreamTicket, withBaklogHeaders } from './api-client.js';
import { isAccountAuthMode } from './auth-gate.js';
import { isPageHidden, registerPausable } from './visibility.js';
import { state, ITCH_NON_GAME_CLASSIFICATIONS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { formatPlatformList } from './platform-labels.js';
import {
  noteFetcherAuthFailure,
  isProviderConnected,
  FETCHER_AUTH_PROVIDER,
  showReconnectBanner,
  authStatusLoaded,
  providerStatus,
  ingestAuthStatusProviders,
  groupRepFor,
} from './connections.js';
import {
  LS_FETCHER_AUTH_COOLDOWN,
  LS_FETCHER_LAST_SEQ,
  LS_FETCHER_SUPPRESSED_RUNS,
  LS_AUTO_STALE_LAST_RUN,
  LS_ITAD_LAST_AUTO_RUN,
  LS_CLAIMS_LAST_AUTO_RUN,
  LS_RECONNECT_DISMISSED,
  profileScopedStorageKey,
} from './profiles.js';
import { markClaimsPendingAutoRun } from './claimable.js';
import { savePrefs } from './prefs.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

// ---------------------------------------------------------------------------
// Chip-level auth-failure backoff
// ---------------------------------------------------------------------------
// When a fetcher run ends in an auth-ish failure (401/403, expired cookie,
// rejected sign-in) we cool that chip down so automatic refreshes and the user
// can't hammer a provider that needs reconnecting — the root cause of the
// earlier request flood. Consecutive failures escalate 5m -> 15m -> 60m. The
// cooldown clears on the next successful run, when the timer expires, or the
// moment the mapped provider shows "connected" in Connections (so reconnecting
// never leaves the chip stuck disabled).
const AUTH_COOLDOWN_STEPS_MS = [5 * 60_000, 15 * 60_000, 60 * 60_000];

function authCooldownLsKey() {
  return profileScopedStorageKey(LS_FETCHER_AUTH_COOLDOWN);
}

/** Escalating cooldown duration for the Nth consecutive auth failure (1-based). */
export function authCooldownDurationMs(strikes) {
  const i = Math.min(Math.max(strikes, 1), AUTH_COOLDOWN_STEPS_MS.length) - 1;
  return AUTH_COOLDOWN_STEPS_MS[i];
}

function loadAuthCooldowns() {
  const m = new Map();
  try {
    const raw = JSON.parse(localStorage.getItem(authCooldownLsKey()) || '{}');
    const now = Date.now();
    for (const [k, v] of Object.entries(raw)) {
      if (v && typeof v.until === 'number' && v.until > now) {
        m.set(k, { until: v.until, strikes: Number(v.strikes) || 1 });
      }
    }
  } catch (_) { /* corrupt or unavailable storage — start clean */ }
  return m;
}

let authCooldowns = new Map();
let _profileScopedFetcherStateReady = false;

/** Load profile-scoped LS after auth/profile id is known (call post-initAuthGate). */
export function ensureProfileScopedFetcherState() {
  if (_profileScopedFetcherStateReady) return;
  _profileScopedFetcherStateReady = true;
  authCooldowns = loadAuthCooldowns();
  reconnectDismissed = loadReconnectDismissedSet();
  if (authCooldowns.size) setTimeout(() => scheduleAuthCooldownTick(), 0);
}

function persistAuthCooldowns() {
  try {
    const obj = {};
    for (const [k, v] of authCooldowns) obj[k] = v;
    localStorage.setItem(authCooldownLsKey(), JSON.stringify(obj));
  } catch (_) { /* storage unavailable — in-memory map still enforces */ }
}

/** Record one auth failure for a fetcher key and (re)arm the escalating cooldown. */
export function noteAuthCooldownStrike(key) {
  ensureProfileScopedFetcherState();
  const strikes = Math.min((authCooldowns.get(key)?.strikes || 0) + 1, AUTH_COOLDOWN_STEPS_MS.length);
  authCooldowns.set(key, { until: Date.now() + authCooldownDurationMs(strikes), strikes });
  persistAuthCooldowns();
  scheduleAuthCooldownTick();
  if (strikes >= AUTH_COOLDOWN_STEPS_MS.length && !fetcherCredentialsSatisfied(key)) {
    const provider = connectProviderForFetcher(key) || FETCHER_AUTH_PROVIDER[key];
    if (provider) markReconnectRequired(provider);
  }
}

let authCooldownTimer = null;
/** Re-render the chip strip when the soonest cooldown expires so a chip
 *  re-enables on its own even with no run in flight. */
function scheduleAuthCooldownTick() {
  if (authCooldownTimer) { clearTimeout(authCooldownTimer); authCooldownTimer = null; }
  let soonest = Infinity;
  for (const c of authCooldowns.values()) soonest = Math.min(soonest, c.until);
  if (!Number.isFinite(soonest)) return;
  const delay = Math.max(0, soonest - Date.now()) + 250;
  authCooldownTimer = setTimeout(() => {
    authCooldownTimer = null;
    for (const [k, c] of authCooldowns) { if (c.until <= Date.now()) authCooldowns.delete(k); }
    persistAuthCooldowns();
    try { renderDashboardFetcherHealth(); } catch (_) { /* not mounted */ }
    scheduleAuthCooldownTick();
  }, delay);
}

export function clearAuthCooldown(key) {
  if (authCooldowns.delete(key)) persistAuthCooldowns();
}

/** Remaining cooldown for a fetcher key in ms, or 0. Self-heals on expiry or
 *  when the mapped provider is reconnected. */
export function authCooldownRemainingMs(key) {
  ensureProfileScopedFetcherState();
  const c = authCooldowns.get(key);
  if (!c) return 0;
  if (fetcherProviders(key).some(p => isProviderConnected(p))) {
    clearAuthCooldown(key);
    return 0;
  }
  const rem = c.until - Date.now();
  if (rem <= 0) { clearAuthCooldown(key); return 0; }
  return rem;
}

/** Short label for a cooldown badge, e.g. "auth 5m" / "auth 1h". */
function authCooldownLabel(ms) {
  const mins = Math.max(1, Math.ceil(ms / 60_000));
  return mins >= 60 ? `auth ${Math.round(mins / 60)}h` : `auth ${mins}m`;
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
function humanizeMissingRequirements(missing) {
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

/** Sync reconnect-required from GET /api/auth/status (survives reload).
 *  Uses the shared timeout so a hung endpoint can't stall the sync loop. */
export async function syncReconnectFromAuthStatus() {
  try {
    const res = await fetchWithTimeout('/api/auth/status');
    if (!res.ok) return;
    const data = await res.json();
    ingestAuthStatusProviders(data.providers || []);
    for (const p of data.providers || []) {
      if (p.status === 'expired') markReconnectRequired(p.key);
      else if (p.status === 'connected') {
        const wasReconnect = reconnectRequiredByProvider.has(p.key);
        clearReconnectRequired(p.key);
        if (wasReconnect) clearFailedStateForReconnectedProvider(p.key);
      }
    }
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
    processAuthStatusTransitions(providers);
    for (const p of providers) {
      if (p.status === 'expired') markReconnectRequired(p.key);
      else if (p.status === 'connected') {
        const wasReconnect = reconnectRequiredByProvider.has(p.key);
        clearReconnectRequired(p.key);
        if (wasReconnect) clearFailedStateForReconnectedProvider(p.key);
      }
    }
    try { renderDashboardFetcherHealth(); } catch (_) { /* not mounted */ }
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

async function handleFetcherAuthOutcome(key, data, logText) {
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
      renderDashboardFetcherHealth();
    } catch (_) {}
    return;
  }
  const authish = noteFetcherAuthFailure(key, logText);
  if (authish) noteAuthCooldownStrike(key);
}

const FRESH_THRESHOLDS = { fresh: 7 * 86400000, recent: 30 * 86400000 };
// ITAD is a deal feed — library-style 7d/30d thresholds are misleading.
const STALE_OVERRIDES = {
  itad: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
  claims: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
};
export function itadLastAutoRunKey() {
  return profileScopedStorageKey(LS_ITAD_LAST_AUTO_RUN);
}

export function claimsLastAutoRunKey() {
  return profileScopedStorageKey(LS_CLAIMS_LAST_AUTO_RUN);
}
export const ITAD_AUTO_REFRESH_INTERVAL_MS = 15 * 60_000;
export const ITAD_AUTO_QUIET_HOUR_END = 7;

/** User-configured ITAD auto-refresh interval (15–60 min) from prefs. */
export function itadAutoRefreshIntervalMs() {
  const min = Number(state.prefs?.itadAutoRefreshIntervalMin);
  if (!Number.isFinite(min)) return ITAD_AUTO_REFRESH_INTERVAL_MS;
  return Math.min(60, Math.max(15, min)) * 60_000;
}

export function claimsAutoRefreshIntervalMs() {
  return itadAutoRefreshIntervalMs();
}

export function thresholdsForMetaKey(metaKey) {
  return STALE_OVERRIDES[metaKey] || FRESH_THRESHOLDS;
}

/** Count new sales / historical lows after an ITAD refresh. */
export function diffItadDeals(prev, next) {
  let newSales = 0;
  let newHistoricalLows = 0;
  for (const [key, n] of Object.entries(next || {})) {
    const p = prev?.[key];
    const cut = n?.cut || 0;
    const prevCut = p?.cut || 0;
    if (cut > 0 && prevCut === 0) newSales += 1;
    if (n?.is_historical_low && !p?.is_historical_low) newHistoricalLows += 1;
  }
  return { newSales, newHistoricalLows };
}

let itadPendingAutoRun = false;

export function consumeItadAutoRunFlag() {
  const v = itadPendingAutoRun;
  itadPendingAutoRun = false;
  return v;
}

/** Map server run status to dashboard chip state. */
export function serverChipState(status) {
  if (status === 'running' || status === 'launching' || status === 'cancelling') return 'running';
  if (status === 'queued') return 'queued';
  return null;
}

export const FETCH_TIMEOUT_MS = 15_000;

/** Fetch with timeout; throws when the server does not respond in time. */
function _isApiUrl(url) {
  const s = String(url);
  return s.startsWith('/api/') || s.includes('/api/');
}

export async function fetchWithTimeout(url, options = {}, ms = FETCH_TIMEOUT_MS) {
  const method = (options.method || 'GET').toUpperCase();
  const merged = method === 'GET' || method === 'HEAD' ? options : withBaklogHeaders(options);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  const doFetch = _isApiUrl(url) ? baklogFetch : fetch;
  try {
    return await doFetch(url, { ...merged, signal: ctrl.signal });
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error('server not responding');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
const ENRICH_KEYS = new Set(['hltb', 'steamReviews', 'steamCovers', 'steamTags']);
/** Cache JSON loaded after library files in reloadGames — avoid "missing" flash during boot. */
const BOOT_DEFERRED_FETCHER_KEYS = new Set([...ENRICH_KEYS, 'itad', 'claims']);
const MAX_SSE_HINT = 'max 8 live streams';
const GROUP_ORDER = ['library', 'wishlist', 'prices', 'enrich'];
const GROUP_LABELS = {
  library: 'Library',
  wishlist: 'Wishlist',
  prices: 'Prices',
  enrich: 'Enrichment',
};
const GROUP_LABEL_TIPS = {
  library: 'Library/store sources',
  wishlist: 'Wishlist sources',
  prices: 'Price sources',
  enrich: 'Enrichment sources',
};
const COUNT_PILL_TITLES = {
  stale: 'Fetchers whose cached data is past its freshness window - re-run to refresh',
  missing: 'Data sources never fetched yet (no local cache) - click the chip to run them',
  fresh: "Every fetcher's cache is up to date",
};
// Fixed order within the Enrichment group: keep the three Steam-derived
// enrichers (orange edge) adjacent, then HLTB. Overrides the status/label
// sort so they always render next to each other.
const ENRICH_ORDER = ['steamTags', 'steamCovers', 'steamReviews', 'hltb'];

const COUNT_FNS = {
  itad: m => Object.keys(m?.by_key || {}).length,
  claims: m => (m?.items || []).length,
  hltb: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
  steamReviews: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
  steamCovers: m => (m?.last_updated != null ? m.last_updated : null),
  steamTags: m => (m?.rows_updated != null ? m.rows_updated : null),
};

// Plain-English description of what a normal click does for each fetcher.
// Falls back to a generic per-group hint if a key isn't listed here.
const CLICK_HINTS = {
  steam: 'Sync your Steam library - picks up new purchases & updated playtime',
  gog: 'Sync your GOG library - picks up new purchases & metadata',
  psn: 'Sync your PlayStation library',
  epic: 'Sync your Epic library',
  amazon: 'Sync your Amazon Prime Gaming library',
  xbox: 'Sync your Xbox library',
  battlenet: 'Sync your Battle.net library',
  ubisoft: 'Sync your Ubisoft Connect library',
  nintendo: 'Sync your Nintendo Switch library',
  humble: 'Sync your Humble Bundle library (games only)',
  ea: 'Sync your EA App library (PC titles)',
  itch: 'Sync your itch.io library',
  wishlistSteam: 'Sync your Steam wishlist',
  wishlistGog: 'Sync your GOG wishlist',
  wishlistEpic: 'Sync your Epic wishlist',
  wishlistPsn: 'Sync your PlayStation Store wishlist',
  wishlistUbisoft: 'Sync your Ubisoft Store wishlist',
  wishlistXbox: 'Sync your Xbox Store wishlist',
  wishlistNintendo: 'Sync your Nintendo Store wishlist',
  wishlistHumble: 'Sync your Humble Store wishlist',
  itad: 'Refresh wishlist price quotes from IsThereAnyDeal',
  claims: 'Download free claimable games (GOG giveaways, Epic, Prime, Steam keys)',
  hltb: "Look up HowLongToBeat hours for games we haven't checked yet",
  steamReviews: 'Pull missing Steam review scores for non-Steam games',
  steamCovers: 'Generate covers for non-Steam games missing artwork',
  steamTags: 'Backfill co-op tags + missing genres on non-Steam games using Steam category data',
};

// What Shift+click (--refresh) actually changes, per fetcher.
const REFRESH_HINTS = {
  steam: 'Re-fetch every game from Steam, ignoring local cache (slower, full rebuild)',
  gog: 'Re-fetch every game from GOG, ignoring local cache (slower, full rebuild)',
  psn: 'Re-fetch every PlayStation entry, ignoring local cache',
  epic: 'Re-fetch every Epic entry, ignoring local cache',
  wishlistGog: 'Re-fetch every wishlist entry from GOG, ignoring cached details',
  hltb: 'Also retry titles previously cached as "no HLTB match" - use after HLTB adds new entries',
  steamReviews:
    'Also retry titles previously cached as "no Steam app match" - use after Steam lists the game',
  steamCovers: 'Also retry rows previously cached as "no Steam match" - use after Steam adds new entries',
  steamTags: 'Re-fetch Steam appdetails ignoring the local cache - picks up newly-added Steam categories',
};

// Pending breakdown for the enrichment chips so the tooltip can say
// "nothing to look up" vs "X new lookups pending" — turns a misleading
// 76% data-coverage number into clear messaging about what a click will
// actually do.
//
// Three states per missing row:
//   unchecked → never tried by the fetcher; click will produce fresh work.
//   retry    → tried before, the upstream returned nothing useful, but the
//              fetcher will keep retrying. Click does work, but probably
//              won't change the numbers much.
//   noMatch  → cached as "no match" so the fetcher skips on a normal click.
//              Only Shift+click (HLTB) can revisit.
function pendingForEnrich(key) {
  if (key === 'hltb') {
    const cache = state.libraryMeta.hltb || {};
    const rows = allLibraryRows();
    let unchecked = 0;
    let retry = 0;
    let noMatch = 0;
    for (const g of rows) {
      if (g.hltb_main_hours != null) continue;
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      if (v === false) noMatch++;
      else unchecked++;
    }
    return { unchecked, retry, noMatch };
  }
  if (key === 'steamReviews') {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = reviewableRows();
    let unchecked = 0;
    let retry = 0;
    let noMatch = 0;
    for (const g of rows) {
      if (g.steam_review_percent != null) continue;
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      if (v === 0) noMatch++;
      else if (v == null) unchecked++;
      else retry++;
    }
    return { unchecked, retry, noMatch };
  }
  if (key === 'steamCovers') {
    const meta = state.libraryMeta.steamCovers || {};
    const skipped = new Set(meta.no_steam_match || []);
    const rows = coverableRows();
    let unchecked = 0;
    let noMatch = 0;
    for (const g of rows) {
      const lib = g.library_image || '';
      const hdr = g.header_image || '';
      const ok = (lib || hdr) && !String(lib).endsWith('.eprt') && !String(hdr).endsWith('.eprt');
      if (ok) continue;
      if (skipped.has(`${g.store || 'steam'}:${g.id}`)) noMatch++;
      else unchecked++;
    }
    return { unchecked, retry: 0, noMatch };
  }
  if (key === 'steamTags') {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = nonSteamRows();
    let unchecked = 0;
    let noMatch = 0;
    for (const g of rows) {
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      // No appid match → nothing this enricher can do.
      if (!v) {
        noMatch++;
        continue;
      }
      // coop_online/coop_local is the canonical "have we run this" signal.
      if (g.coop_online === undefined && g.coop_local === undefined) unchecked++;
    }
    return { unchecked, retry: 0, noMatch };
  }
  return null;
}

function clickHintFor(src) {
  const base = CLICK_HINTS[src.key] || `Run ${src.label} fetcher`;
  const pending = pendingForEnrich(src.key);
  if (!pending) return base;
  if (pending.unchecked > 0) {
    return `${base} (${formatNum(pending.unchecked)} pending)`;
  }
  if (pending.retry > 0) {
    return `Re-tries ${formatNum(pending.retry)} previously-attempted rows that didn't return data. Usually won't change the score - safe to skip.`;
  }
  if (pending.noMatch > 0) {
    const note = src.supportsRefresh
      ? ' Use Shift+click to retry them.'
      : '';
    return `Nothing new to look up - the remaining ${formatNum(pending.noMatch)} are cached as "no match".${note}`;
  }
  return 'Everything is enriched - nothing to do.';
}

function refreshHintFor(src) {
  if (!src.supportsRefresh) return null;
  const base = REFRESH_HINTS[src.key] || 'Re-fetch ignoring local cache (slower, full rebuild)';
  if (src.key === 'hltb' || src.key === 'steamReviews') {
    const pending = pendingForEnrich(src.key);
    if (pending?.noMatch > 0) {
      return `${base} (~${formatNum(pending.noMatch)} cached misses would be retried)`;
    }
  }
  return base;
}

function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === 'game') return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

function allLibraryRows() {
  const itchGames = (state.itchGames || []).filter(itchIsGame);
  return [...(state.allGames || []), ...itchGames];
}

function nonSteamRows() {
  return (state.allGames || []).filter(g => (g.store || 'steam') !== 'steam');
}

function reviewableRows() {
  return [...nonSteamRows(), ...(state.itchGames || []).filter(itchIsGame)];
}

export function coverableRows() {
  const itch = (state.itchGames || []).filter(itchIsGame);
  return [...nonSteamRows(), ...(state.wishlistGames || []), ...itch];
}

function coverageOf(rows, pred) {
  const total = rows.length;
  if (!total) return { covered: 0, total: 0, pct: null };
  const covered = rows.filter(pred).length;
  const pct = covered >= total ? 100 : Math.floor((covered / total) * 100);
  return { covered, total, pct };
}

const COVERAGE_FNS = {
  hltb: () => coverageOf(allLibraryRows(), g => g.hltb_main_hours != null),
  steamReviews: () => coverageOf(reviewableRows(), g => g.steam_review_percent != null),
  steamCovers: () => coverageOf(
    coverableRows(),
    g => {
      const lib = g.library_image || '';
      const hdr = g.header_image || '';
      if (!lib && !hdr) return false;
      return !String(lib).endsWith('.eprt') && !String(hdr).endsWith('.eprt');
    },
  ),
  // Universe = non-Steam rows where we have a Steam appid match. Covered =
  // rows the enricher has touched (coop fields are the canonical signal).
  steamTags: () => {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = nonSteamRows().filter(
      g => cache[`${g.store || 'steam'}:${g.id}`],
    );
    return coverageOf(
      rows,
      g => g.coop_online !== undefined || g.coop_local !== undefined,
    );
  },
};

function coverageLabel(key) {
  const fn = COVERAGE_FNS[key];
  if (!fn) return null;
  const { total, pct } = fn();
  if (!total) return ' - ';
  let label = `${pct != null ? pct : 0}%`;
  const pending = pendingForEnrich(key);
  if (pending && pending.unchecked > 0) label += ` · ${formatNum(pending.unchecked)} new`;
  return label;
}

function coverageTooltipLine(key) {
  const fn = COVERAGE_FNS[key];
  if (!fn) return null;
  const { covered, total } = fn();
  if (!total) return null;
  const pending = pendingForEnrich(key);
  const verb = key === 'hltb'
    ? 'have HowLongToBeat hours'
    : key === 'steamReviews'
      ? 'have Steam review scores'
      : key === 'steamTags'
        ? 'have Steam-derived co-op tags'
        : 'have artwork';
  let line = `${formatNum(covered)} of ${formatNum(total)} ${verb}.`;
  if (!pending) return line;
  if (pending.unchecked > 0) {
    line += ` ${formatNum(pending.unchecked)} still to try.`;
  } else if (pending.retry > 0 && key === 'steamReviews') {
    line += ` ${formatNum(pending.retry)} were tried before with no review score - clicking will re-check but rarely changes the number.`;
  } else if (pending.noMatch > 0) {
    const src = key === 'hltb' ? 'HowLongToBeat' : 'Steam';
    line += ` Remaining ${formatNum(pending.noMatch)} have no match on ${src} - clicking won't add more.`;
  } else {
    line += ' Nothing pending.';
  }
  return line;
}

let fetcherSources = [];
let reloadGamesFn = async () => {};
let reloadAfterFetcherFn = null;
let runStaleCooldownUntil = 0;

export function configureFetcherHealth({ reloadGames, reloadAfterFetcher }) {
  reloadGamesFn = reloadGames;
  reloadAfterFetcherFn = reloadAfterFetcher || null;
}

async function manifestRefreshKeys() {
  try {
    const res = await fetch('fetchers/manifest.json');
    if (!res.ok) return {};
    const data = await res.json();
    const keys = {};
    for (const entry of data.fetchers || []) {
      if ((entry.refreshArgs || []).length) keys[entry.key] = true;
    }
    return keys;
  } catch (_) {
    return {};
  }
}

export async function loadFetcherSources(force = false) {
  const refreshByKey = await manifestRefreshKeys();
  try {
    const res = await baklogFetch('/api/fetchers');
    if (res.ok) {
      const data = await res.json();
      fetcherSources = (data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: entry.cmd ? `python ${entry.cmd}` : '',
        countFn: COUNT_FNS[entry.key] || null,
        requires: entry.requires || [],
        missingRequirements: entry.missing_requirements || [],
        supportsRefresh: !!(entry.supports_refresh || refreshByKey[entry.key]),
        available: entry.available !== false,
        platforms: entry.platforms || [],
      }));
      return fetcherSources;
    }
  } catch (_) {}
  if (fetcherSources.length && !force) return fetcherSources;
  try {
    const res = await fetch('fetchers/manifest.json');
    if (res.ok) {
      const data = await res.json();
      fetcherSources = (data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: `python ${entry.script}${(entry.args || []).length ? ` ${(entry.args || []).join(' ')}` : ''}`,
        countFn: COUNT_FNS[entry.key] || null,
        requires: entry.requires || [],
        missingRequirements: [],
        supportsRefresh: !!refreshByKey[entry.key],
      }));
    }
  } catch (_) {}
  return fetcherSources;
}

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

function setGlobalFetcherTail(text, kind = 'stdout') {
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

function updateGlobalFetcherIndicator(runStateByKey, sourceFn) {
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
      el.title = 'A fetcher failed - click to view the log';
      el.setAttribute('aria-label', text);
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

export function humanizeAge(ms) {
  if (!Number.isFinite(ms)) return ' - ';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 14) return `${d}d`;
  const w = Math.floor(d / 7);
  if (w < 8) return `${w}w`;
  return `${Math.floor(d / 30)}mo`;
}

export function fetcherFreshness(source) {
  const thresholds = thresholdsForMetaKey(source.metaKey);
  const meta = state.libraryMeta[source.metaKey];
  const count = meta
    ? (source.countFn ? source.countFn(meta) : (meta.game_count ?? null))
    : null;
  const deferKey = source.key || source.metaKey;
  if (!meta || !meta.fetched_at) {
    if (!state.dashboardDataReady && BOOT_DEFERRED_FETCHER_KEYS.has(deferKey)) {
      return { status: 'pending', ageMs: Infinity, count, ageLabel: '…', iso: null };
    }
    return { status: 'missing', ageMs: Infinity, count, ageLabel: meta ? '?' : ' - ', iso: null };
  }
  const ts = Date.parse(meta.fetched_at);
  const ageMs = Number.isFinite(ts) ? Date.now() - ts : Infinity;
  let status = 'stale';
  if (ageMs < thresholds.fresh) status = 'fresh';
  else if (ageMs < thresholds.recent) status = 'recent';
  return { status, ageMs, count, ageLabel: humanizeAge(ageMs), iso: meta.fetched_at };
}

const ITAD_SOURCE = { key: 'itad', metaKey: 'itad', countFn: COUNT_FNS.itad };
const CLAIMS_SOURCE = { key: 'claims', metaKey: 'claims', countFn: COUNT_FNS.claims };

/** Auto-queue ITAD when prices are older than 60min (7am–midnight local). */
/** Chip stays in failed styling until the next successful run (not just ~10s runState). */
const lastRunFailedByKey = new Map();
/** Labels of fetchers that finished OK since the pill was last cleared. */
const fetchSuccessLabels = new Set();

// ---------------------------------------------------------------------------
// Cosmetic chip-age ticker (in-place text only — never re-renders dashboard)
// ---------------------------------------------------------------------------
const AGE_TICK_MS = 60_000;
const FAST_AGE_TICK_MS = 1_000;
const FAST_AGE_WINDOW_MS = 60_000;

let ageTickTimer = null;
let fastTickTimer = null;
let fastTickRemaining = 0;

/** Cosmetic age label from logged fetched_at (clamped, no local counter). */
function cosmeticAgeLabel(src) {
  const { ageMs, ageLabel } = fetcherFreshness(src);
  if (!Number.isFinite(ageMs)) return ageLabel;
  return humanizeAge(Math.max(0, ageMs));
}

/** True when the chip is showing a plain relative age (not run/reconnect/cooldown/etc.). */
function chipShowsPlainAge(src, deps = {}) {
  const stateFor = deps.stateFor ?? (k => fetcherRunner.stateFor(k));
  if (stateFor(src.key)) return false;
  if (isFetcherReconnectRequired(src.key)) return false;
  if (authCooldownRemainingMs(src.key) > 0) return false;
  if (lastRunFailedByKey.has(src.key)) return false;
  const { status } = fetcherFreshness(src);
  if (status === 'missing') return false;
  return true;
}

/**
 * Patch .fh-chip-age text from logged fetched_at. No innerHTML, no chart/dashboard render.
 * @returns {boolean} false when the panel is gone (caller should stop its timer).
 */
export function refreshChipAgesInPlace(deps = {}) {
  return tickRefreshChipAges(deps);
}

function tickRefreshChipAges(deps = {}) {
  if (typeof document !== 'undefined' && document.hidden) return true;
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return false;
  const sources = deps.sources ?? fetcherSources;
  for (const src of sources) {
    if (!chipShowsPlainAge(src, deps)) continue;
    const chip = slot.querySelector(`.fh-chip[data-fetcher-key="${src.key}"]`);
    const ageSpan = chip?.querySelector('.fh-chip-age');
    if (!ageSpan) continue;
    const label = cosmeticAgeLabel(src);
    if (ageSpan.textContent !== label) ageSpan.textContent = label;
  }
  return true;
}

export function stopAgeTicker() {
  if (ageTickTimer) clearInterval(ageTickTimer);
  ageTickTimer = null;
}

export function ensureAgeTicker() {
  if (ageTickTimer) return;
  ageTickTimer = setInterval(() => {
    if (!tickRefreshChipAges()) stopAgeTicker();
  }, AGE_TICK_MS);
}

export function stopFastAgeTick() {
  if (fastTickTimer) clearInterval(fastTickTimer);
  fastTickTimer = null;
  fastTickRemaining = 0;
}

/** Whether the post-fetch 1s age ticker is active (for tests / diagnostics). */
export function isFastAgeTickActive() {
  return fastTickTimer != null;
}

/** 1s cosmetic updates for the first minute after a fetch lands (seconds band). */
export function startFastAgeTick() {
  const ticks = Math.ceil(FAST_AGE_WINDOW_MS / FAST_AGE_TICK_MS);
  fastTickRemaining = Math.max(fastTickRemaining, ticks);
  if (fastTickTimer) return;
  fastTickTimer = setInterval(() => {
    const cont = tickRefreshChipAges();
    fastTickRemaining -= 1;
    if (!cont || fastTickRemaining <= 0) stopFastAgeTick();
  }, FAST_AGE_TICK_MS);
}

if (typeof document !== 'undefined' && !document.__baklogFetcherAgeVisListener) {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      try { tickRefreshChipAges(); } catch (_) { /* panel not mounted */ }
    }
  });
  document.__baklogFetcherAgeVisListener = true;
}

export function maybeAutoRefreshItad(deps = {}) {
  if (isPageHidden()) return false;
  if (state.prefs.itadAutoRefreshDisabled) return false;
  if (isFetcherDisconnected('itad')) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const getHour = deps.getHour ?? (() => new Date().getHours());
  if (getHour() < ITAD_AUTO_QUIET_HOUR_END) return false;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner.stateFor(k));
  if (stateForFn('itad')) return false;
  const fresh = fetcherFreshness(ITAD_SOURCE);
  const intervalMs = itadAutoRefreshIntervalMs();
  if (fresh.ageMs < intervalMs) return false;
  const now = deps.now ?? Date.now();
  const lastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(itadLastAutoRunKey()) || 0));
  if (now - lastRun() < intervalMs) return false;
  const setLastRun = deps.setLastRun
    ?? (t => localStorage.setItem(itadLastAutoRunKey(), String(t)));
  setLastRun(now);
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  runFn('itad', { auto: true });
  return true;
}

export function maybeAutoRefreshClaims(deps = {}) {
  if (isPageHidden()) return false;
  if (state.prefs.claimsAutoRefreshDisabled) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner.stateFor(k));
  if (stateForFn('claims')) return false;
  const fresh = fetcherFreshness(CLAIMS_SOURCE);
  const intervalMs = claimsAutoRefreshIntervalMs();
  if (fresh.ageMs < intervalMs) return false;
  const now = deps.now ?? Date.now();
  const lastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(claimsLastAutoRunKey()) || 0));
  if (now - lastRun() < intervalMs) return false;
  const setLastRun = deps.setLastRun
    ?? (t => localStorage.setItem(claimsLastAutoRunKey(), String(t)));
  setLastRun(now);
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  runFn('claims', { auto: true });
  return true;
}

export const AUTO_STALE_AGE_MS = 24 * 60 * 60 * 1000;
export const AUTO_STALE_STAGGER_MS = 30 * 60 * 1000;

export function autoStaleLastRunKey() {
  return profileScopedStorageKey(LS_AUTO_STALE_LAST_RUN);
}

/** After a store connects, open the fetcher log and run that provider's fetcher_keys. */
export async function maybeAutoFetchOnConnect(fetcherKeys, deps = {}) {
  if (state.prefs.autoFetchOnConnect === false) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner.isApiAvailable());
  if (!isApiAvailableFn()) return false;

  const loadFn = deps.loadFetcherSources ?? (async () => loadFetcherSources(true));
  await loadFn();

  const sources = deps.sources ?? fetcherSources;
  const keys = (fetcherKeys || []).filter((key) => sources.some((s) => s.key === key));
  if (!keys.length) return false;

  const openLogFn = deps.openFetcherLog ?? (() => fetcherRunner.openFetcherLog({ focusPanel: false }));
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  const waitFn = deps.waitForQueueSlot ?? ((o) => fetcherRunner.waitForQueueSlot(o));
  const getCancelEpochFn = deps.getCancelEpoch ?? (() => fetcherRunner.getCancelEpoch());

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
  for (const key of keys) {
    if (getCancelEpochFn() !== batchEpoch) break;
    await waitFn({ batchEpoch });
    if (getCancelEpochFn() !== batchEpoch) break;
    await runFn(key, { auto: true });
  }
  return true;
}

/** Quietly refresh the stalest store fetcher older than 24h (one per stagger window). */
export function maybeAutoFetchStale24h(deps = {}) {
  if (state.prefs.autoFetchStale24h !== true) return false;
  if (isPageHidden()) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner.isApiAvailable());
  if (!isApiAvailableFn()) return false;
  const inFlightFn = deps.inFlightCount ?? (() => fetcherRunner.inFlightCount());
  if (inFlightFn() > 0) return false;

  const now = deps.now ?? Date.now();
  const getLastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(autoStaleLastRunKey()) || 0));
  if (now - getLastRun() < AUTO_STALE_STAGGER_MS) return false;

  const sources = deps.sources ?? fetcherSources;
  const freshnessFn = deps.fetcherFreshness ?? fetcherFreshness;
  const credsFn = deps.fetcherCredentialsSatisfied ?? fetcherCredentialsSatisfied;
  const stateForFn = deps.stateFor ?? ((k) => fetcherRunner.stateFor(k));
  const cooldownFn = deps.authCooldownRemainingMs ?? authCooldownRemainingMs;
  const disconnectedFn = deps.isFetcherDisconnected ?? isFetcherDisconnected;
  const reconnectFn = deps.isFetcherReconnectRequired ?? isFetcherReconnectRequired;

  const candidates = sources.filter((src) => {
    if (src.key === 'itad') return false;
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
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  runFn(pick.key, { auto: true });
  return true;
}

let autoEnrichCooldownUntil = 0;
const AUTO_ENRICH_COOLDOWN_MS = 3000;

/** Queue enrichers after a library fetch that added new titles (opt-out pref). */
export async function maybeAutoEnrichNewAdditions(newCount, deps = {}) {
  if (state.prefs.autoEnrichOnAdd === false) return false;
  if (!newCount || newCount <= 0) return false;
  const now = deps.now ?? Date.now();
  if (now < autoEnrichCooldownUntil) return false;
  const isApiAvailableFn = deps.isApiAvailable ?? (() => fetcherRunner.isApiAvailable());
  if (!isApiAvailableFn()) return false;

  autoEnrichCooldownUntil = now + AUTO_ENRICH_COOLDOWN_MS;

  const loadSourcesFn = deps.loadFetcherSources ?? (() => loadFetcherSources(true));
  await loadSourcesFn();

  const sources = deps.sources ?? fetcherSources;
  const stateForFn = deps.stateFor ?? (k => fetcherRunner.stateFor(k));
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  const waitSlotFn =
    deps.waitForQueueSlot ?? (() => fetcherRunner.waitForQueueSlot({ batchEpoch }));
  const credsOkFn = deps.fetcherCredentialsSatisfied ?? fetcherCredentialsSatisfied;
  const cooldownFn = deps.authCooldownRemainingMs ?? authCooldownRemainingMs;
  const disconnectedFn = deps.isFetcherDisconnected ?? isFetcherDisconnected;

  const keysToRun = ENRICH_ORDER.filter(key => {
    const src = sources.find(s => s.key === key);
    if (!src) return false;
    if (src.missingRequirements?.length && !credsOkFn(src.key)) return false;
    if (stateForFn(key)) return false;
    if (cooldownFn(key) > 0) return false;
    if (disconnectedFn(key)) return false;
    return true;
  });

  if (!keysToRun.length) return false;

  const appendLineFn = deps.appendLine;
  if (appendLineFn) {
    appendLineFn(`[auto-enrich: ${newCount} new game(s) - queuing ${keysToRun.length} enricher(s)]`, 'meta');
  }

  const cancelEpochFn = deps.getCancelEpoch ?? (() => fetcherRunner.getCancelEpoch());
  const batchEpoch = cancelEpochFn();

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

const STAT_LAYOUT_KEY = 'baklog-fetcher-stat-layout';
const STAT_LAYOUTS = ['compact', 'landscape'];

/** Survives innerHTML rebuilds — native <details> would re-collapse every render. */
let legendTipsOpen = false;

export function toggleLegendTips() {
  legendTipsOpen = !legendTipsOpen;
  renderDashboardFetcherHealth();
}

function statLayout() {
  try {
    const v = localStorage.getItem(STAT_LAYOUT_KEY);
    return STAT_LAYOUTS.includes(v) ? v : 'compact';
  } catch {
    return 'compact';
  }
}

function syncStatLayoutToggle() {
  const btn = document.getElementById('fetcherStatLayoutToggle');
  if (!btn) return;
  const layout = statLayout();
  const landscape = layout === 'landscape';
  btn.setAttribute('aria-pressed', landscape ? 'true' : 'false');
  btn.setAttribute(
    'aria-label',
    landscape ? 'Switch to compact layout' : 'Switch to landscape layout',
  );
}

export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try { localStorage.setItem(STAT_LAYOUT_KEY, next); } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}

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

  function applyServerSnapshotInFlight(snap) {
    lastServerInFlight = !!(snap?.active || (snap?.queue?.length));
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
    if (inFlightPollTimer || !isApiAvailable() || isPageHidden()) return;
    if (runStateByKey.size === 0 && sourcesByRunId.size === 0) return;
    inFlightPollTimer = setInterval(() => {
      if (isPageHidden()) return;
      syncFromServer().catch(() => {});
      if (runStateByKey.size === 0 && sourcesByRunId.size === 0 && !lastServerInFlight) {
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
    lastRunFailedByKey.clear();
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
  function isQueueFull() {
    return inFlightCount() >= MAX_IN_FLIGHT;
  }
  function waitForQueueSlot({ batchEpoch } = {}) {
    if (batchEpoch !== undefined && getCancelEpoch() !== batchEpoch) {
      return Promise.reject(new Error('cancelled'));
    }
    if (cancelInFlight) return Promise.reject(new Error('cancelled'));
    if (!isQueueFull()) return Promise.resolve();
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const tick = () => {
        if (cancelInFlight) {
          reject(new Error('cancelled'));
          return;
        }
        if (batchEpoch !== undefined && getCancelEpoch() !== batchEpoch) {
          reject(new Error('cancelled'));
          return;
        }
        if (!isQueueFull()) {
          resolve();
          return;
        }
        if (Date.now() - start > WAIT_QUEUE_SLOT_MS) {
          reject(new Error('queue wait timeout'));
          return;
        }
        setTimeout(tick, 200);
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
    const label = collapsed ? 'Expand log panel' : 'Collapse log panel';
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
    panel.innerHTML = `
      <div class="fh-log-head">
        <div class="fh-log-headings">
          <span class="fh-log-title" data-role="title">Fetcher log</span>
          <span class="fh-log-status" data-role="status" aria-live="polite">idle</span>
        </div>
        <button type="button" class="fh-log-btn fh-log-btn-cancel hidden" data-role="cancel" title="Stop all queued and running fetchers (Shift+click: force reset queue)">Cancel</button>
        <button type="button" class="fh-log-btn" data-role="clear" title="Clear log output (does not stop running fetchers)">Clear</button>
        <button type="button" class="fh-log-btn fh-log-toggle" data-role="close" aria-expanded="true" aria-label="Collapse log panel" title="Collapse log panel"><span class="fh-log-toggle-icon" aria-hidden="true">&#9662;</span></button>
      </div>
      <div class="fh-log-body" data-role="body"></div>
      <button type="button" class="fh-log-jump hidden" data-role="jump" aria-label="Jump to latest line" title="Jump to latest">&darr;</button>
    `;
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
      empty.textContent = 'No fetcher activity yet. Run a fetcher from the chips above to populate.';
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
      btn.title = 'Stop all queued and running fetchers (Shift+click: force reset queue)';
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
        if (!onActive && !onQueue) {
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

  function reconcileCancelInBackground(ids, { force = false } = {}) {
    void (async () => {
      const cancelUrl = force ? '/api/runs/cancel?force=1' : '/api/runs/cancel';
      let bulkOk = false;
      try {
        const res = await fetchWithTimeoutAndProbe(cancelUrl, { method: 'POST' }, CANCEL_HTTP_MS);
        if (res.ok) {
          bulkOk = true;
          const data = await res.json();
          const n = data.cancelled?.length ?? 0;
          if (n) {
            logEvent(
              'info',
              force ? `[server force reset: ${n} run(s)]` : `[server cancelled ${n} run(s)]`,
            );
          }
        }
      } catch (_) {}
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
    body.scrollTop = body.scrollHeight;
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
    if (followTail) body.scrollTop = body.scrollHeight;
    updateJumpButton();
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
    }
    updateFetcherBar();
  }

  async function run(key, { refresh = false, auto = false } = {}) {
    if (!isApiAvailable()) {
      if (!auto) scrollPopoverModule('top');
      return;
    }
    if (cancelInFlight) {
      if (!auto) scrollPopoverModule('top');
      return;
    }
    await loadFetcherSources(true);
    const src = source(key);
    if (!src || runStateByKey.has(key) || submitInFlightKeys.has(key)) {
      if (!auto) scrollPopoverModule('top');
      return;
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
      return;
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
      return;
    }
    // Hard cap mirrors server-side enforcement (max 1 active run, no queuing).
    // Without this guard a fast double-click could land two POSTs before the
    // server's lock saw the first one as pending.
    if (isQueueFull()) {
      ensurePanel(src);
      logEvent(
        'info',
        `[${src.label}: queue full - a fetch is already running]`,
      );
      if (!auto) scrollPopoverModule('console');
      return;
    }
    if (refresh && !src.supportsRefresh) {
      logEvent(
        'info',
        `[${src.label}: this fetcher has no force-refresh mode - a normal click already pulls the latest data]`,
      );
      if (!auto) scrollPopoverModule('console');
      return;
    }

    if (auto && key === 'itad') {
      itadPendingAutoRun = true;
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
      if (cancelInFlight) return;
      try {
        res = await fetchWithTimeoutAndProbe(url, { method: 'POST' });
      } catch (err) {
        logEvent('error', `[client] cannot reach server: ${err}`);
        setStatus('failed');
        return;
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
        && !isQueueFull();
      if (!canRetry) return;
      await new Promise(r => setTimeout(r, 600));
      }
      if (res.status === 409) return;
      if (!res.ok) {
        invalidateApiProbe();
        const txt = await res.text().catch(() => '');
        logEvent('error', `[server ${res.status}] ${txt || 'submit failed'}`);
        setStatus('failed');
        markChipState(key, null);
        return;
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
  }

  async function runAllStale() {
    if (!isApiAvailable()) return;
    runStaleCooldownUntil = Date.now() + 2000;
    renderDashboardFetcherHealth();
    await loadFetcherSources(true);
    const staleKeys = fetcherSources
      .filter(src => {
        const { status } = fetcherFreshness(src);
        if (status !== 'stale' && status !== 'missing') return false;
        if (src.missingRequirements?.length && !fetcherCredentialsSatisfied(src.key)) return false;
        if (runStateByKey.has(src.key)) return false;
        if (authCooldownRemainingMs(src.key) > 0) return false;
        if (isFetcherDisconnected(src.key)) return false;
        return true;
      })
      .map(src => src.key);
    if (!staleKeys.length) return;
    const batchEpoch = getCancelEpoch();
    // Respect the global cap. Wait for an open slot between submits so we
    // never stack the queue beyond 1 active + 1 queued, matching the rule
    // the server enforces and the chip-disable logic in chipHtml.
    for (const key of staleKeys) {
      if (getCancelEpoch() !== batchEpoch) {
        logEvent('info', '[run stale aborted: cancelled]');
        break;
      }
      try {
        await waitForQueueSlot({ batchEpoch });
        if (getCancelEpoch() !== batchEpoch) {
          logEvent('info', '[run stale aborted: cancelled]');
          break;
        }
        await run(key);
      } catch (err) {
        if (err?.message === 'cancelled') {
          logEvent('info', '[run stale aborted: cancelled]');
        } else {
          logEvent('error', `[run stale aborted: ${err}]`);
        }
        break;
      }
    }
  }

  async function subscribe(runId, key, src, { reconnect = false, quiet = false, queuedOnly = false } = {}) {
    if (suppressedRunIds.has(runId) || cancelInFlight || queuedOnly) return;
    clearReconnect(runId);
    const prior = sourcesByRunId.get(runId);
    if (prior) {
      try { prior.es.close(); } catch (_) {}
      sourcesByRunId.delete(runId);
    }
    const es = new EventSource(await urlWithStreamTicket(streamUrl(runId)));
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
          if (runId !== _lastAppliedDoneRunId) {
            _lastAppliedDoneRunId = runId;
            await refreshAfterFetch(key);
          }
          clearAuthCooldown(key);
          const provider = FETCHER_AUTH_PROVIDER[key];
          if (provider) clearReconnectRequired(provider);
          fetchSuccessLabels.add(src.label || key);
          markChipState(key, null);
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
      if (es.readyState === EventSource.CONNECTING) return;
      if (!sourcesByRunId.has(runId)) return;
      try { es.close(); } catch (_) {}
      sourcesByRunId.delete(runId);
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
          if (ok && finished.id !== _lastAppliedDoneRunId) {
            _lastAppliedDoneRunId = finished.id;
            await refreshAfterFetch(key);
          }
          if (!ok && finished.status === 'done') {
            handleFetcherAuthOutcome(key, finished, '');
          }
          if (ok) fetchSuccessLabels.add(src.label || key);
          markChipState(key, null);
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
    if (isPageHidden()) return;
    await syncFromServer();
    maybeAutoRefreshItad();
    maybeAutoRefreshClaims();
    maybeAutoFetchStale24h();
  }

  function startDashboardPolling() {
    _dashboardPollWanted = true;
    if (pollTimer || !isApiAvailable() || isPageHidden()) return;
    void syncFromServer().then(() => {
      maybeAutoRefreshItad();
      maybeAutoRefreshClaims();
      maybeAutoFetchStale24h();
    });
    pollTimer = setInterval(() => { void _runDashboardPollTick(); }, 30_000);
  }

  function pauseDashboardPollForVisibility() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
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
        pauseDashboardPollForVisibility();
        stopInFlightPolling();
        closeAllStreams();
      },
      resume() {
        syncFromServer().catch(() => {});
        if (_dashboardPollWanted && !pollTimer && isApiAvailable() && !isPageHidden()) {
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
    waitForQueueSlot,
    run,
    runAllStale,
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

function isSourceConnected(row) {
  return row.status !== 'missing'
    && row.status !== 'pending'
    && !isFetcherDisconnected(row.src.key)
    && !isFetcherReconnectRequired(row.src.key);
}

function groupConnectedCount(rows, group) {
  const inGroup = rows.filter(r => r.src.group === group);
  const total = inGroup.length;
  const connected = inGroup.filter(isSourceConnected).length;
  return { connected, total };
}

export function buildFetcherHealthRows() {
  return fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
}

/** Auth-healthy for chip filter: not disconnected and not reconnect-required. */
export function isFetcherAuthHealthy(key) {
  return !isFetcherDisconnected(key) && !isFetcherReconnectRequired(key);
}

export function filterFetcherHealthRows(rows, { showConnected, showStaleMissing }) {
  if (!showConnected && !showStaleMissing) return rows;
  return rows.filter(r => {
    const matchConnected = showConnected && isFetcherAuthHealthy(r.src.key);
    const matchStaleMissing = showStaleMissing && (r.status === 'stale' || r.status === 'missing');
    return matchConnected || matchStaleMissing;
  });
}

function fetcherHealthEmptyMessage({ showConnected, showStaleMissing }) {
  if (!showConnected && !showStaleMissing) return 'No fetchers.';
  if (showConnected && showStaleMissing) {
    return 'No connected or stale/missing fetchers match these filters.';
  }
  if (showConnected) return 'No connected fetchers match this filter.';
  return 'No stale or missing fetchers match this filter.';
}

function fetcherStatTotals(rows) {
  const total = rows.length;
  const connected = rows.filter(isSourceConnected).length;
  const pct = total ? Math.round((connected / total) * 100) : 0;
  const lib = groupConnectedCount(rows, 'library');
  const wish = groupConnectedCount(rows, 'wishlist');
  const enrich = groupConnectedCount(rows, 'enrich');

  let lastSyncValue = 'never';
  let minAge = Infinity;
  for (const r of rows) {
    if (Number.isFinite(r.ageMs) && r.ageMs < minAge) minAge = r.ageMs;
  }
  if (Number.isFinite(minAge) && minAge !== Infinity) {
    lastSyncValue = `${humanizeAge(minAge)} ago`;
  }
  return { total, connected, pct, lib, wish, enrich, lastSyncValue };
}

function statTileHtml(value, label, title, extraClass = '') {
  return `
    <div class="fh-stat${extraClass ? ` ${extraClass}` : ''}" title="${escapeAttr(title)}">
      <span class="fh-stat-value">${escapeHtml(String(value))}</span>
      <span class="fh-stat-label">${escapeHtml(label)}</span>
    </div>`;
}

export function buildStatTilesHtml(rows) {
  const { lib, wish, enrich, lastSyncValue } = fetcherStatTotals(rows);
  return `
      ${statTileHtml(lastSyncValue, 'Last sync', 'Most recent fetch across all sources', 'fh-stat--lastsync')}
      ${statTileHtml(lib.connected, 'Libraries', `${lib.connected} of ${lib.total} library sources connected`)}
      ${statTileHtml(wish.connected, 'Wishlists', `${wish.connected} of ${wish.total} wishlist sources connected`)}
      ${statTileHtml(enrich.connected, 'Enrichment', `${enrich.connected} of ${enrich.total} enrichment sources connected`)}`;
}

export function buildStatStripHtml(rows, mode = statLayout(), extrasHtml = '') {
  const { total, connected, pct } = fetcherStatTotals(rows);
  const heroTitle = `${connected} of ${total} sources have data and are not disconnected`;
  const heroLabel = mode === 'compact' ? 'Sources' : 'Sources connected';
  const barHtml = `<span class="fh-stat-bar" aria-hidden="true"><span class="fh-stat-bar-fill" style="--pct:${pct}%"></span></span>`;
  const meterHtml = `<span class="fh-stat-meter" aria-hidden="true"><span class="fh-stat-meter-fill" style="--pct:${pct}%"></span></span>`;

  if (mode === 'compact') {
    return `
    <div class="fh-stats fh-stats--compact" role="group" aria-label="Fetcher overview">
      <div class="fh-stat fh-stat--hero" title="${escapeAttr(heroTitle)}">
        <span class="fh-stat-value">${connected}/${total}</span>
        <span class="fh-stat-label">${escapeHtml(heroLabel)}</span>
      </div>
      ${extrasHtml}
      ${buildStatTilesHtml(rows)}
      ${barHtml}
    </div>`;
  }

  // Rail: the meter hero is the only thing in this block. The breakdown tiles
  // and the head controls are placed in the middle rail column by the renderer.
  return `
    <div class="fh-stats fh-stats--rail" role="group" aria-label="Fetcher overview">
      <div class="fh-stat fh-stat--hero fh-stat--meter" title="${escapeAttr(heroTitle)}">
        <span class="fh-stat-value">${connected}/${total}</span>
        <span class="fh-stat-label">${escapeHtml(heroLabel)}</span>
        ${meterHtml}
      </div>
    </div>`;
}

export function renderDashboardFetcherHealth() {
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return;
  const restoreBarToggleFocus = document.activeElement?.matches?.('[data-role="bar-toggle"]');
  const showConnected = state.prefs.fetcherHealthShowConnected !== false;
  const showStaleMissing = state.prefs.fetcherHealthShowStaleMissing !== false;
  const rows = fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
  const staleRows = rows.filter(r => r.status === 'stale');
  const missingRows = rows.filter(r => r.status === 'missing');
  const runnableStale = rows.filter(r => {
    if (r.status !== 'stale' && r.status !== 'missing') return false;
    if (r.src.missingRequirements?.length && !fetcherCredentialsSatisfied(r.src.key)) return false;
    if (fetcherRunner.stateFor(r.src.key)) return false;
    if (isFetcherDisconnected(r.src.key)) return false;
    return true;
  });
  const visible = filterFetcherHealthRows(rows, { showConnected, showStaleMissing });
  // Sort best -> worst by the chip's *effective* status (mirrors the precedence
  // chipHtml uses for displayStatus), so healthy fetchers float to the top and
  // anything needing attention sinks to the bottom. Active runs lead since the
  // user is watching them; alphabetical label is the final tiebreaker.
  const healthRank = (r) => {
    const key = r.src.key;
    const runState = fetcherRunner.stateFor(key);
    if (runState && runState !== 'failed') return 0; // running / queued / launching
    if (!runState && lastRunFailedByKey.has(key)) return 8; // failed (worst)
    if (isFetcherReconnectRequired(key)) return 7; // session expired
    if (isFetcherDisconnected(key)) return 6; // not connected
    if (authCooldownRemainingMs(key) > 0) return 5; // auth cooldown
    const freshRank = { fresh: 1, recent: 2, stale: 3, pending: 3, missing: 4 };
    return freshRank[r.status] ?? 4;
  };
  visible.sort((a, b) => healthRank(a) - healthRank(b) || a.src.label.localeCompare(b.src.label));

  const summaryParts = [];
  if (staleRows.length) summaryParts.push(`${staleRows.length} stale`);
  if (missingRows.length) summaryParts.push(`${missingRows.length} missing`);
  const healthSummary = summaryParts.length ? summaryParts.join(' · ') : 'All fresh';
  fetcherRunner.setBarSummary(healthSummary);
  // The "missing" pill is always shown so it doesn't pop in/out: at 0 it stays
  // put and turns green (fresh). The stale pill remains count-conditional.
  const missingNone = missingRows.length === 0;
  const stalePillHtml = staleRows.length
    ? `<span class="fh-count fh-count--stale" title="${escapeAttr(COUNT_PILL_TITLES.stale)}">${staleRows.length} stale</span>`
    : '';
  const missingPillHtml = `<span class="fh-count ${missingNone ? 'fh-count--fresh' : 'fh-count--missing'}" title="${escapeAttr(missingNone ? COUNT_PILL_TITLES.fresh : COUNT_PILL_TITLES.missing)}">${missingRows.length} missing</span>`;
  const countsHtml = `${stalePillHtml}${missingPillHtml}`;
  const apiReady = fetcherRunner.isApiAvailable();
  const probeDone = fetcherRunner.apiProbeFinished();
  const showReadonly = probeDone && !apiReady;
  const summaryTooltip = [
    'Click a chip → run an incremental sync (fast - fills gaps, uses cache where safe).',
    'Shift+click → force a full refresh that ignores local cache (slower; only on chips that support it).',
    'Hover any chip to see exactly what click vs. Shift+click will do for that source.',
  ].join('\n');
  const clickHint = apiReady
    ? `<span class="fh-legend-item" title="${escapeAttr(summaryTooltip)}"><span class="fh-chip-warn" aria-hidden="true">!</span> click a chip = sync &middot; Shift+click = full refresh</span>`
    : '';
  const readonlyBanner = showReadonly
    ? (isAccountAuthMode()
      ? `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only - the server API did not respond (sign in, restart
          <code>python server.py</code>, or check the terminal for errors).
        </div>`
      : `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only. Run <code>python server.py</code> and open
          <a href="http://127.0.0.1:8765" class="fh-readonly-link">http://127.0.0.1:8765</a>
          to click chips and stream logs.
        </div>`)
    : '';
  const layout = statLayout();
  slot.dataset.statLayout = layout;
  const countsBlockHtml = `<span class="fh-counts">${countsHtml}</span>`;
  const infoStripHtml = buildStatStripHtml(rows, 'compact', '');
  const statStripHtml = buildStatStripHtml(rows, layout, '');

  function chipHtml({ src, status, count, ageLabel, iso }) {
    const covLabel = ENRICH_KEYS.has(src.key) ? coverageLabel(src.key) : null;
    const countStr = covLabel != null
      ? covLabel
      : (count != null && count > 0 ? formatNum(count) : ' - ');
    // Co-op tags has the longest enrichment label; when it also shows "· N new"
    // the chip gets tight, so drop the " tags" suffix to reclaim space.
    const chipLabel = (src.key === 'steamTags' && covLabel && covLabel.includes('new'))
      ? src.label.replace(/ tags$/i, '')
      : src.label;
    const fetchedLine = iso ? new Date(iso).toLocaleString() : 'not loaded';
    const runState = fetcherRunner.stateFor(src.key);
    // A terminal 'failed' runState (the ~10s post-failure flash) is not an
    // active run: clicks should route to Connections (reconnect / fix creds)
    // exactly like the persisted failed/reconnect state that follows it, so
    // every chip behaves the same the instant it fails — never silently
    // re-running an auth-broken fetcher. Only launching/queued/running/
    // cancelling count as "active" and suppress the Connections route.
    const runActive = !!runState && runState !== 'failed';
    const needsReconnect = !runActive && isFetcherReconnectRequired(src.key);
    const disconnected = !runActive && !needsReconnect && isFetcherDisconnected(src.key);
    const navProvider = !runActive ? connectionsNavigateProvider(src.key) : null;
    const authCooldownMs = (runState || needsReconnect || disconnected) ? 0 : authCooldownRemainingMs(src.key);
    const inAuthCooldown = authCooldownMs > 0;
    const persistFailed = !runState && lastRunFailedByKey.has(src.key);
    const displayStatus = runState
      || (persistFailed ? 'failed' : (needsReconnect ? 'reconnect' : status));
    const runLabel = runState ? ` · ${runState.toUpperCase()}` : '';
    const needsConfig = (src.missingRequirements || []).length > 0
      && !fetcherCredentialsSatisfied(src.key);
    const configHint = needsConfig
      ? ` · missing for this profile: ${src.missingRequirements.join(', ')} (Connections)`
      : '';
    const clickHint = clickHintFor(src);
    const refreshHint = refreshHintFor(src);
    const enrichLine = ENRICH_KEYS.has(src.key) ? coverageTooltipLine(src.key) : null;
    const titleLines = apiReady
      ? [
          `${src.label} · ${countStr} · fetched ${fetchedLine}${runLabel}`,
          enrichLine,
          `Click: ${clickHint}`,
          refreshHint ? `Shift+click: ${refreshHint}` : 'Shift+click: not supported for this fetcher',
          `Command: ${src.cmd}${refreshHint ? ' [+ --refresh on Shift+click]' : ''}`,
          needsConfig ? 'Not configured for this profile - open Connections to add keys.' : '',
          configHint ? `Note:${configHint}` : '',
        ].filter(Boolean)
      : [
          `${src.label} · ${countStr} · fetched ${fetchedLine}`,
          enrichLine,
          `Click: ${clickHint}`,
          `Command: ${src.cmd}`,
          needsConfig ? 'Not configured for this profile - open Connections to add keys.' : '',
          configHint ? `Note:${configHint}` : '',
          'Server is offline - start `python server.py` to run fetchers from the UI.',
        ].filter(Boolean);
    const queueFullElsewhere = fetcherRunner.inFlightCount() >= 1 && !runState;
    if (queueFullElsewhere) {
      titleLines.push('Queue full - a fetch is already running. Wait for it to finish.');
    }
    if (needsReconnect) {
      titleLines.push('Session expired - reconnect to refresh credentials, or dismiss to hide this hint.');
    }
    if (disconnected) {
      titleLines.push('Not connected - click to connect in Connections.');
    }
    if (inAuthCooldown) {
      titleLines.push(`Auth failed - cooling down ${authCooldownLabel(authCooldownMs)}. Reconnect in Connections to clear, or wait it out.`);
    }
    const platformUnavailable = src.available === false;
    if (platformUnavailable) {
      const plats = formatPlatformList(src.platforms);
      titleLines.push(`Unavailable on this OS - ${src.label} runs on ${plats} only.`);
    }
    const title = titleLines.join('\n');
    // When navProvider is set, the chip routes to Connections (bind-events) instead of running.
    const disabled = platformUnavailable || !apiReady || runState === 'running' || runState === 'queued' || queueFullElsewhere
      || ((inAuthCooldown || needsReconnect) && !navProvider);
    const needsClass = needsConfig ? ' fh-chip-needs-config' : '';
    const readonlyClass = !apiReady ? ' fh-chip-readonly' : '';
    const cooldownClass = inAuthCooldown ? ' fh-chip-auth-cooldown' : '';
    const reconnectClass = needsReconnect ? ' fh-chip-reconnect-required' : '';
    const disconnectedClass = disconnected ? ' fh-chip-disconnected' : '';
    const unavailableClass = platformUnavailable ? ' fh-chip-unavailable' : '';
    const warnBadge = needsConfig
      ? '<span class="fh-chip-warn" title="Missing credentials for this profile - Connections">!</span>'
      : '';
    let ageText = runState
      ? runState
      : (disconnected ? '' : (inAuthCooldown ? authCooldownLabel(authCooldownMs) : ageLabel));
    if (persistFailed && !runState) ageText = 'failed';
    else if (status === 'pending') ageText = '…';
    else if (status === 'missing' && ageLabel === '?' && (count === 0 || count == null)) ageText = 'empty';
    const connectAttr = navProvider
      ? ` data-fetcher-connect="${escapeAttr(navProvider)}"`
      : '';
    const chipAriaLabel = `${chipLabel}, ${countStr}, ${ageText || status}`;
    const chipBtn = `<button type="button" class="fh-chip fh-chip-${escapeAttr(displayStatus)}${needsClass}${readonlyClass}${cooldownClass}${reconnectClass}${disconnectedClass}${unavailableClass}" data-fetcher-key="${escapeAttr(src.key)}" data-status="${escapeAttr(status)}"${connectAttr} style="border-left: 3px solid ${escapeAttr(src.color)}" title="${escapeAttr(title)}" aria-label="${escapeAttr(chipAriaLabel)}"${disabled ? ' disabled' : ''} aria-disabled="${disabled ? 'true' : 'false'}">
      <span class="fh-chip-dot"></span>
      ${warnBadge}
      <span class="fh-chip-label">${escapeHtml(chipLabel)}</span>
      <span class="fh-chip-count">${escapeHtml(countStr)}</span>
      <span class="fh-chip-age">${escapeHtml(ageText)}</span>
    </button>`;
    return chipBtn;
  }

  const chipsHtml = visible.length
    ? GROUP_ORDER.map(group => {
        let groupRows = visible.filter(r => r.src.group === group);
        if (!groupRows.length) return '';
        if (group === 'enrich') {
          const ord = k => {
            const i = ENRICH_ORDER.indexOf(k);
            return i < 0 ? ENRICH_ORDER.length : i;
          };
          groupRows = [...groupRows].sort((a, b) => healthRank(a) - healthRank(b) || ord(a.src.key) - ord(b.src.key));
        }
        let groupToggle = '';
        if (group === 'prices') {
          const itadMin = Number(state.prefs.itadAutoRefreshIntervalMin) || 15;
          const itadOff = !!state.prefs.itadAutoRefreshDisabled;
          groupToggle = `<label class="fh-toggle fh-itad-auto" title="Runs ITAD between 7am and midnight when the dashboard is open.">
              <input id="itadAutoRefreshToggle" type="checkbox" class="rounded" ${itadOff ? '' : 'checked'} />
              Auto-refresh
            </label>
            <label class="fh-toggle fh-itad-interval" title="How often auto-refresh runs ITAD (15-60 min)">
              <input id="itadAutoRefreshInterval" type="range" min="15" max="60" step="5" value="${itadMin}" ${itadOff ? 'disabled' : ''} aria-label="Auto-refresh interval (minutes)" />
              <span id="itadAutoRefreshIntervalVal">${itadMin}m</span>
            </label>`;
        } else if (group === 'enrich') {
          groupToggle = `<label class="fh-toggle" title="After a library fetch adds new games, queue HLTB, Reviews, Covers, and Co-op tags">
              <input id="autoEnrichOnAddToggle" type="checkbox" class="rounded" ${state.prefs.autoEnrichOnAdd !== false ? 'checked' : ''} />
              Auto-enrich new games
            </label>`;
        }
        return `<div class="fh-group">
            <div class="fh-group-head">
              <div class="fh-group-label" title="${escapeAttr(GROUP_LABEL_TIPS[group] || '')}">${escapeHtml(GROUP_LABELS[group] || group)}</div>
              ${groupToggle}
            </div>
            <div class="fh-group-chips">${groupRows.map(chipHtml).join('')}</div>
          </div>`;
      }).join('')
    : `<span class="fh-empty">${escapeHtml(fetcherHealthEmptyMessage({ showConnected, showStaleMissing }))}</span>`;

  const staleBtnDisabled = !apiReady || !runnableStale.length || Date.now() < runStaleCooldownUntil;
  const staleBtnLabel = `Run stale (${runnableStale.length})`;

  const staleButtonHtml = `<button type="button" class="fh-run-stale" ${staleBtnDisabled ? 'disabled' : ''} title="Queue every stale or missing fetcher that has credentials">${escapeHtml(staleBtnLabel)}</button>`;
  const filterHint = (!showConnected && !showStaleMissing)
    ? 'Showing all'
    : `Uncheck both to show all ${rows.length}`;
  const filterToggleHtml = `<div class="fh-filter-toggles" title="Each checked box adds fetchers (OR). Disconnected sources with fresh data may stay hidden - uncheck both to reveal all.">
            <label class="fh-toggle" title="Show fetchers whose store/session is connected (not disconnected or expired)">
              <input id="fetcherHealthShowConnected" type="checkbox" class="rounded" ${showConnected ? 'checked' : ''} />
              Connected
            </label>
            <label class="fh-toggle" title="Show fetchers with stale or missing cached data (regardless of connection)">
              <input id="fetcherHealthShowStaleMissing" type="checkbox" class="rounded" ${showStaleMissing ? 'checked' : ''} />
              Stale / missing
            </label>
            <span class="fh-filter-hint">${escapeHtml(filterHint)}</span>
          </div>`;
  const legendTipsItemsHtml = `
          ${clickHint}
          <span class="fh-legend-item" title="Yellow ! on a chip - credentials missing for this profile; open Connections"><span class="fh-chip-warn" aria-hidden="true">!</span> missing keys for this profile</span>
          <span class="fh-legend-item" title="Dim dashed chip border - this source has never been fetched">dim dashed = never fetched</span>
          <span class="fh-legend-item" title="Dot color on each chip - how old the cached data is">dot color = cache age</span>
          <span class="fh-legend-item" title="Reconnect label - session expired; fix in Connections, not by clicking the chip">reconnect = session expired (Connections, not these chips)</span>`;
  const legendToggleHtml = `<button type="button" class="fh-legend-toggle${legendTipsOpen ? ' is-open' : ''}" data-role="fh-legend-toggle" aria-expanded="${legendTipsOpen ? 'true' : 'false'}" aria-controls="fhLegendTips" title="Show fetcher chip legend and tips">ⓘ Legend &amp; tips</button>`;
  const legendTipsHtml = `<div id="fhLegendTips" class="fh-legend-tips${legendTipsOpen ? ' is-open' : ''}" role="region" aria-label="Fetcher legend and tips"${legendTipsOpen ? '' : ' aria-hidden="true"'}>${legendTipsItemsHtml}</div>`;
  const chipsBlockHtml = `<div class="fh-chips">${chipsHtml}</div>`;
  const controlBarHtml = `
      <div class="fh-legend-row fh-legend-row--bar">
        <div class="fh-control-bar">
          ${countsBlockHtml}
          ${staleButtonHtml}
          ${legendToggleHtml}
          ${filterToggleHtml}
        </div>
      </div>`;

  // Landscape: 3-col rail (meter | tiles+controls | legend+chips).
  // Compact: finalized top-info stack above chips.
  const overviewHtml = layout === 'landscape'
    ? `<div class="fh-rail-grid">
      ${statStripHtml}
      <div class="fh-rail-mid">
        ${buildStatTilesHtml(rows)}
        <div class="fh-head fh-head--stack">
          ${staleButtonHtml}
          ${filterToggleHtml}
          ${countsBlockHtml}
          ${legendToggleHtml}
        </div>
      </div>
      <div class="fh-rail-main">
        ${chipsBlockHtml}
      </div>
    </div>
    ${legendTipsHtml}`
    : `${infoStripHtml}
    <div class="fh-rail-main">
      ${controlBarHtml}
      ${chipsBlockHtml}
    </div>
    ${legendTipsHtml}`;

  slot.innerHTML = `
    <div class="fh-bar" data-role="fetcher-bar" title="Click to expand the fetcher console">
      <span class="fh-bar-dot" data-role="bar-dot" aria-hidden="true"></span>
      <span class="fh-bar-status" data-role="bar-status">Fetcher health</span>
      <span class="fh-bar-tail" data-role="bar-tail">No fetcher activity yet.</span>
      <button type="button" class="fh-bar-toggle" data-role="bar-toggle" aria-expanded="false" aria-label="Expand fetcher" title="Expand or collapse the fetcher console">▸</button>
    </div>
    ${readonlyBanner}
    ${overviewHtml}
  `;
  ensureAgeTicker();
  fetcherRunner.applyFetcherRowLayout();
  syncStatLayoutToggle();
  if (restoreBarToggleFocus) {
    document.querySelector('[data-role="bar-toggle"]')?.focus();
  }
}
