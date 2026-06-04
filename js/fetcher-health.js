import { baklogFetch, urlWithStreamTicket, withBaklogHeaders } from './api-client.js';
import { isAccountAuthMode } from './auth-gate.js';
import { isPageHidden, registerPausable } from './visibility.js';
import { state, ITCH_NON_GAME_CLASSIFICATIONS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import {
  noteFetcherAuthFailure,
  isProviderConnected,
  FETCHER_AUTH_PROVIDER,
  showReconnectBanner,
  authStatusLoaded,
  providerStatus,
  ingestAuthStatusProviders,
} from './connections.js';
import { activeProfileId, profileScopedStorageKey } from './profiles.js';
import { savePrefs } from './prefs.js';

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
const AUTH_COOLDOWN_LS_KEY = profileScopedStorageKey('baklog-fetcher-auth-cooldown');

/** Escalating cooldown duration for the Nth consecutive auth failure (1-based). */
export function authCooldownDurationMs(strikes) {
  const i = Math.min(Math.max(strikes, 1), AUTH_COOLDOWN_STEPS_MS.length) - 1;
  return AUTH_COOLDOWN_STEPS_MS[i];
}

function loadAuthCooldowns() {
  const m = new Map();
  try {
    const raw = JSON.parse(localStorage.getItem(AUTH_COOLDOWN_LS_KEY) || '{}');
    const now = Date.now();
    for (const [k, v] of Object.entries(raw)) {
      if (v && typeof v.until === 'number' && v.until > now) {
        m.set(k, { until: v.until, strikes: Number(v.strikes) || 1 });
      }
    }
  } catch (_) { /* corrupt or unavailable storage — start clean */ }
  return m;
}

const authCooldowns = loadAuthCooldowns();
// Resume any cooldown persisted from a previous session.
if (authCooldowns.size) setTimeout(() => scheduleAuthCooldownTick(), 0);

function persistAuthCooldowns() {
  try {
    const obj = {};
    for (const [k, v] of authCooldowns) obj[k] = v;
    localStorage.setItem(AUTH_COOLDOWN_LS_KEY, JSON.stringify(obj));
  } catch (_) { /* storage unavailable — in-memory map still enforces */ }
}

/** Record one auth failure for a fetcher key and (re)arm the escalating cooldown. */
export function noteAuthCooldownStrike(key) {
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
  if (keys.has('PSN_NPSSO')) return 'PSN not connected';
  if (keys.has('ITCH_API_KEY')) return 'itch.io API key missing';
  if (keys.has('ITAD_API_KEY')) return 'ITAD API key missing';
  if (keys.has('XBL_API_KEY')) return 'Xbox API key missing';
  return missing.join(', ');
}

// ---------------------------------------------------------------------------
// Per-provider reconnect-required (definitive auth / max-strike / server expired)
// ---------------------------------------------------------------------------
const RECONNECT_DISMISSED_LS_KEY = profileScopedStorageKey('baklog-reconnect-dismissed');
/** @type {Set<string>} */
let reconnectDismissed = loadReconnectDismissedSet();
/** @type {Map<string, { at: number }>} */
const reconnectRequiredByProvider = new Map();

function loadReconnectDismissedSet() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECONNECT_DISMISSED_LS_KEY) || '[]');
    return new Set(Array.isArray(raw) ? raw.filter(x => typeof x === 'string') : []);
  } catch (_) {
    return new Set();
  }
}

function persistReconnectDismissed() {
  try {
    localStorage.setItem(RECONNECT_DISMISSED_LS_KEY, JSON.stringify([...reconnectDismissed]));
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

/** User dismissed the inline reconnect chip affordance for this provider. */
export function dismissReconnectRequired(provider) {
  if (!provider) return;
  reconnectDismissed.add(provider);
  persistReconnectDismissed();
}

export function isReconnectDismissed(provider) {
  return reconnectDismissed.has(provider);
}

/** True when provider needs reconnect and user has not dismissed the chip hint. */
export function isProviderReconnectRequired(provider) {
  if (!provider || reconnectDismissed.has(provider)) return false;
  if (isProviderConnected(provider)) {
    clearReconnectRequired(provider);
    return false;
  }
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
      else if (p.status === 'connected') clearReconnectRequired(p.key);
    }
  } catch (_) { /* server offline or timed out */ }
}

// Re-render the dashboard chips the instant auth status changes anywhere
// (e.g. a connection made in the Connections tab), not just on the 30s poll.
// connections.js fires this from its single auth-status cache write.
if (typeof document !== 'undefined') {
  document.addEventListener('baklog:auth-status', ev => {
    const providers = ev?.detail?.providers || [];
    for (const p of providers) {
      if (p.status === 'expired') markReconnectRequired(p.key);
      else if (p.status === 'connected') clearReconnectRequired(p.key);
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
  if (fetcherCredentialsSatisfied(key)) return false;
  return fetcherProviders(key).some(p => isProviderReconnectRequired(p));
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

function handleFetcherAuthOutcome(key, data, logText) {
  const authExit = data?.exit_code === 4 || data?.failure_kind === 'auth';
  if (authExit) {
    if (!fetcherCredentialsSatisfied(key)) {
      const provider = reconnectProviderForFetcher(key) || FETCHER_AUTH_PROVIDER[key];
      if (provider) markReconnectRequired(provider);
      if (provider) showReconnectBanner([provider]);
    }
    clearAuthCooldown(key);
    return;
  }
  const authish = noteFetcherAuthFailure(key, logText);
  if (authish) noteAuthCooldownStrike(key);
}

const FRESH_THRESHOLDS = { fresh: 7 * 86400000, recent: 30 * 86400000 };
// ITAD is a deal feed — library-style 7d/30d thresholds are misleading.
const STALE_OVERRIDES = {
  itad: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
};
export const ITAD_LAST_AUTO_RUN_KEY = profileScopedStorageKey('baklog-itad-last-auto-run');
export const ITAD_AUTO_REFRESH_INTERVAL_MS = 60 * 60_000;
export const ITAD_AUTO_QUIET_HOUR_END = 7;

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
const MAX_SSE_HINT = 'max 8 live streams';
const GROUP_ORDER = ['library', 'wishlist', 'prices', 'enrich'];
const GROUP_LABELS = {
  library: 'Library',
  wishlist: 'Wishlist',
  prices: 'Prices',
  enrich: 'Enrichment',
};
// Fixed order within the Enrichment group: keep the three Steam-derived
// enrichers (orange edge) adjacent, then HLTB. Overrides the status/label
// sort so they always render next to each other.
const ENRICH_ORDER = ['steamTags', 'steamCovers', 'steamReviews', 'hltb'];

const COUNT_FNS = {
  itad: m => Object.keys(m?.by_key || {}).length,
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
  psn: 'Sync your PSN library',
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
  hltb: "Look up HowLongToBeat hours for games we haven't checked yet",
  steamReviews: 'Pull missing Steam review scores for non-Steam games',
  steamCovers: 'Generate covers for non-Steam games missing artwork',
  steamTags: 'Backfill co-op tags + missing genres on non-Steam games using Steam category data',
};

// What Shift+click (--refresh) actually changes, per fetcher.
const REFRESH_HINTS = {
  steam: 'Re-fetch every game from Steam, ignoring local cache (slower, full rebuild)',
  gog: 'Re-fetch every game from GOG, ignoring local cache (slower, full rebuild)',
  psn: 'Re-fetch every PSN entry, ignoring local cache',
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

function coverableRows() {
  return nonSteamRows();
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
  const { covered, total, pct } = fn();
  if (!total) return ' - ';
  const base = `${pct != null ? pct : 0}% · ${formatNum(covered)}/${formatNum(total)}`;
  const pending = pendingForEnrich(key);
  if (!pending) return base;
  if (pending.unchecked > 0) return `${base} · ${formatNum(pending.unchecked)} new`;
  // "retry" and "noMatch" are not actionable enough to deserve a banner —
  // keep the chip quiet and let the tooltip explain. "max" means there's
  // simply nothing left a click would do.
  return `${base} · max`;
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

function updateGlobalFetcherIndicator(runStateByKey, sourceFn) {
  const el = document.getElementById('fetcherGlobalStatus');
  if (!el) return;
  const textEl = document.getElementById('fetcherGlobalStatusText');
  const liveEl = document.getElementById('fetcherGlobalStatusLive');
  const running = [];
  const queued = [];
  for (const [key, st] of runStateByKey) {
    const src = sourceFn(key);
    const label = src?.label || key;
    if (st === 'running') running.push(label);
    else if (st === 'queued') queued.push(label);
  }
  if (!running.length && !queued.length) {
    // Stay visible as an idle affordance so the console is always reachable,
    // not only while a run is in flight.
    el.classList.remove('hidden');
    el.classList.add('fh-global-status-idle');
    if (textEl) textEl.textContent = 'Fetcher log';
    if (liveEl) liveEl.textContent = '';
    el.title = 'Show fetcher log';
    return;
  }
  el.classList.remove('hidden');
  el.classList.remove('fh-global-status-idle');
  let text;
  if (running.length) {
    const extra = queued.length ? ` (+${queued.length} queued)` : '';
    text = `Fetching: ${running.join(', ')}${extra}`;
  } else {
    text = `Queued: ${queued.join(', ')}`;
  }
  if (textEl) textEl.textContent = text;
  if (liveEl) liveEl.textContent = text;
  el.title = `${text} - click to show log`;
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
  if (!meta || !meta.fetched_at) {
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

/** Auto-queue ITAD when prices are older than 60min (7am–midnight local). */
/** Chip stays in failed styling until the next successful run (not just ~10s runState). */
const lastRunFailedByKey = new Map();

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
  if (fresh.ageMs < ITAD_AUTO_REFRESH_INTERVAL_MS) return false;
  const now = deps.now ?? Date.now();
  const lastRun = deps.getLastRun
    ?? (() => Number(localStorage.getItem(ITAD_LAST_AUTO_RUN_KEY) || 0));
  if (now - lastRun() < ITAD_AUTO_REFRESH_INTERVAL_MS) return false;
  const setLastRun = deps.setLastRun
    ?? (t => localStorage.setItem(ITAD_LAST_AUTO_RUN_KEY, String(t)));
  setLastRun(now);
  const runFn = deps.runFn ?? ((k, opts) => fetcherRunner.run(k, opts));
  runFn('itad', { auto: true });
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
  const waitSlotFn = deps.waitForQueueSlot ?? (() => fetcherRunner.waitForQueueSlot());
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

  for (const key of keysToRun) {
    try {
      await waitSlotFn();
      await runFn(key, { auto: true });
    } catch (err) {
      if (appendLineFn) appendLineFn(`[auto-enrich aborted: ${err}]`, 'stderr');
      break;
    }
  }
  return true;
}

export const fetcherRunner = (() => {
  let apiAvailable = null;
  const runStateByKey = new Map();
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
  const SUPPRESSED_RUNS_KEY = profileScopedStorageKey('fetcher-suppressed-run-ids');
  const LAST_SEQ_KEY = profileScopedStorageKey('fetcher-last-seq-by-run');
  const lastSeqByRunId = new Map();
  const IN_FLIGHT_POLL_MS = 10_000;
  const WAIT_QUEUE_SLOT_MS = 120_000;
  const RECONNECT_BASE_MS = 2000;
  const RECONNECT_MAX_MS = 30000;
  const RECONNECT_MAX_ATTEMPTS = 8;
  const RECONNECT_MAX_QUEUED = 3;
  const CANCEL_HTTP_MS = 5000;
  let runsSnapshotPromise = null;
  let runsSnapshotAt = 0;
  const RUNS_SNAPSHOT_MIN_MS = 1500;
  let inFlightPollTimer = null;
  /** True when the last /api/runs snapshot had active or queued rows (server truth). */
  let lastServerInFlight = false;
  let cancelInFlight = false;

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
      appendLine(
        `[${src.label}: stream dropped too many times - refresh the page or use Cancel]`,
        'stderr',
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
    appendLine(`[${src.label}: stream dropped - reconnecting in ${Math.round(delay / 1000)}s]`, 'meta');
    const timer = setTimeout(() => {
      reconnectTimers.delete(runId);
      if (suppressedRunIds.has(runId)) return;
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
      toggleEl.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      toggleEl.setAttribute('aria-label', expanded ? 'Collapse fetcher' : 'Expand fetcher');
    }
  }

  function applyFetcherRowLayout() {
    const row = fetcherRow();
    if (!row) return;
    const expanded = shouldShowExpanded();
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
    applyFetcherRowLayout();
  }

  function expandPanel({ manual = false, src, serverStatus, extra } = {}) {
    if (manual) {
      state.prefs.fetcherCollapsed = false;
      savePrefs();
      forceExpanded = false;
    } else {
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
    if (manual) {
      state.prefs.fetcherCollapsed = true;
      savePrefs();
    }
    forceExpanded = false;
    applyFetcherRowLayout();
  }

  function toggleFetcherPanel({ manual = true } = {}) {
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
    if (!window.matchMedia(LOG_DESKTOP_MQ).matches) {
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

  // Count of fetchers currently running + queued client-side. The server
  // enforces a hard cap of 2 (1 active + 1 queued); we mirror that here so
  // the UI can disable other chips before the user wastes a click on a 409.
  const MAX_IN_FLIGHT = 2;
  function inFlightCount() {
    return runStateByKey.size;
  }
  function isQueueFull() {
    return inFlightCount() >= MAX_IN_FLIGHT;
  }
  function waitForQueueSlot() {
    if (!isQueueFull()) return Promise.resolve();
    const start = Date.now();
    return new Promise((resolve, reject) => {
      const tick = () => {
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
  function buildLogPanelChrome() {
    const panel = logPanel();
    if (!panel) return null;
    if (panel.dataset.built) return panel;
    panel.innerHTML = `
      <div class="fh-log-head">
        <span class="fh-log-title" data-role="title">Fetcher log</span>
        <span class="fh-log-status" data-role="status">idle</span>
        <span class="fh-log-spacer"></span>
        <button type="button" class="fh-log-btn fh-log-btn-cancel hidden" data-role="cancel" title="Stop all queued and running fetchers (Shift+click: force reset queue)">Cancel</button>
        <button type="button" class="fh-log-btn" data-role="clear">Clear</button>
        <button type="button" class="fh-log-btn" data-role="close">Collapse</button>
      </div>
      <div class="fh-log-body" data-role="body"></div>
      <button type="button" class="fh-log-jump hidden" data-role="jump" aria-label="Jump to latest line" title="Jump to latest">&darr;</button>
    `;
    panel.dataset.built = '1';
    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-role]');
      if (!btn) return;
      if (btn.dataset.role === 'close') collapsePanel({ manual: true });
      else if (btn.dataset.role === 'clear') clearLog();
      else if (btn.dataset.role === 'cancel') cancelInFlightRuns({ force: e.shiftKey });
      else if (btn.dataset.role === 'jump') scrollLogToBottom();
    });
    const body = panel.querySelector('[data-role="body"]');
    if (body) body.addEventListener('scroll', () => onLogBodyScroll(body));
    return panel;
  }

  function ensurePanel(src, serverStatus, extra) {
    expandPanel({ manual: false, src, serverStatus, extra });
  }

  /**
   * Expand fetcher health + console (e.g. kebab "Show fetcher log"). Builds
   * chrome if needed; preserves existing log lines.
   *
   * Note: lives inside #dashboardContainer — switchView('dashboard') first
   * when calling from other views.
   * @returns {boolean}
   */
  function reopenLogPanel() {
    const panel = buildLogPanelChrome();
    if (!panel) return false;
    const body = panel.querySelector('[data-role="body"]');
    if (body && !body.children.length) {
      const empty = document.createElement('div');
      empty.className = 'fh-log-empty';
      empty.textContent = 'No fetcher activity yet. Run a fetcher from the dashboard chips to populate.';
      body.appendChild(empty);
      followTail = true;
      clearFollowTailIdleTimer();
    }
    logBodyEl = body || null;
    return expandPanel({ manual: true });
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

  async function waitForRunsToClear(runIds, timeoutMs = 15_000) {
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

  async function cancelInFlightRuns({ force = false } = {}) {
    if (!isApiAvailable()) return;
    if (cancelInFlight) return;
    cancelInFlight = true;
    updateCancelButton();
    let snap = null;
    try {
      snap = await fetchRunsSnapshot({ force: true });
    } catch (_) {}
    applyServerSnapshotInFlight(snap);
    const ids = [];
    if (snap?.active) ids.push(snap.active.id);
    for (const q of snap?.queue || []) ids.push(q.id);
    if (!ids.length && !force && inFlightCount() === 0 && !lastServerInFlight) {
      cancelInFlight = false;
      updateCancelButton();
      return;
    }
    closeAllStreams();
    for (const id of ids) suppressedRunIds.add(id);
    persistSuppressedRunIds();
    for (const key of [...runStateByKey.keys()]) {
      markChipState(key, 'running');
    }
    if (snap?.active) {
      const src = source(snap.active.key);
      if (src) {
        ensurePanel(src, 'cancelling', force ? 'cancelling (force)' : undefined);
        markChipState(
          snap.active.key,
          serverChipState(snap.active.status) || 'running',
          snap.active.id,
        );
      }
    } else {
      setStatus('running', force ? 'cancelling (force)' : 'cancelling');
    }
    updateCancelButton();
    renderDashboardFetcherHealth();
    const cancelUrl = force ? '/api/runs/cancel?force=1' : '/api/runs/cancel';
    let bulkOk = false;
    try {
      const res = await fetchWithTimeoutAndProbe(cancelUrl, { method: 'POST' }, CANCEL_HTTP_MS);
      if (res.ok) {
        bulkOk = true;
        const data = await res.json();
        const n = data.cancelled?.length ?? 0;
        appendLine(
          force ? `[force reset: ${n} run(s)]` : (n ? `[cancelled ${n} run(s)]` : '[cancelled]'),
          'meta',
        );
      } else {
        const txt = await res.text().catch(() => '');
        appendLine(`[cancel failed ${res.status}] ${txt}`, 'stderr');
      }
    } catch (err) {
      appendLine(`[cancel failed] ${err}`, 'stderr');
    }
    if (!bulkOk && ids.length) {
      appendLine('[per-run cancel fallback…]', 'meta');
      for (const id of ids) {
        await cancelOneRun(id);
      }
    }
    let stillRunning = await waitForRunsToClear(ids);
    if (stillRunning.size && !force) {
      appendLine('[queue still busy - force reset…]', 'stderr');
      cancelInFlight = false;
      return cancelInFlightRuns({ force: true });
    }
    for (const id of ids) {
      if (!stillRunning.has(id)) suppressedRunIds.add(id);
    }
    persistSuppressedRunIds();
    try {
      snap = await fetchRunsSnapshot({ force: true });
      applyServerSnapshotInFlight(snap);
      pruneSuppressedRuns(snap);
    } catch (_) {}
    await syncFromServer();
    const idle = !snap?.active && !(snap?.queue || []).length;
    if (idle) {
      for (const key of [...runStateByKey.keys()]) markChipState(key, null);
      setStatus('failed');
      liveRunId = null;
      lastServerInFlight = false;
    }
    updateCancelButton();
    renderDashboardFetcherHealth();
    cancelInFlight = false;
    updateCancelButton();
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

  function appendLine(text, kind = 'stdout') {
    if (!logBody()) buildLogPanelChrome();
    if (!logBody()) return;
    lastLineText = text;
    lastLineKind = kind;
    if (!isFetcherRowExpanded()) updateFetcherBar();
    pendingLines.push({ text, kind });
    if (pendingLines.length > LOG_BUFFER_CAP) {
      pendingLines = pendingLines.slice(-LOG_BUFFER_CAP);
    }
    if (!flushHandle) {
      flushHandle = requestAnimationFrame(flushLines);
    }
  }

  function markChipState(key, runState, runId = null) {
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
    if (!isApiAvailable()) return;
    await loadFetcherSources(true);
    const src = source(key);
    if (!src || runStateByKey.has(key)) return;
    // Auth-failure backoff: block while cooling down. Auto/bulk runs stay
    // silent; a chip click is already prevented by the disabled attribute, so
    // this only fires for programmatic callers — explain it once.
    const cooldownMs = authCooldownRemainingMs(key);
    if (cooldownMs > 0) {
      if (!auto) {
        ensurePanel(src);
        appendLine(
          `[${src.label}: auth cooldown - ${authCooldownLabel(cooldownMs)} left. Reconnect in Connections to clear.]`,
          'meta',
        );
      }
      return;
    }
    if (isFetcherDisconnected(key)) {
      if (!auto) {
        ensurePanel(src);
        const provider = connectProviderForFetcher(key);
        appendLine(
          `[${src.label}: not connected - connect in Connections before running. No request sent.]`,
          'meta',
        );
        if (provider) showReconnectBanner([provider]);
      }
      return;
    }
    // Hard cap mirrors server-side enforcement (max 1 active + 1 queued).
    // Without this guard a fast double-click could land two POSTs before the
    // server's lock saw the first one as pending.
    if (isQueueFull()) {
      ensurePanel(src);
      appendLine(
        `[${src.label}: queue full - one run is in progress and one is queued]`,
        'meta',
      );
      return;
    }
    if (refresh && !src.supportsRefresh) {
      appendLine(
        `[${src.label}: this fetcher has no force-refresh mode - a normal click already pulls the latest data]`,
        'stderr',
      );
      return;
    }

    if (auto && key === 'itad') {
      itadPendingAutoRun = true;
    } else {
      ensurePanel(src);
      if (src.missingRequirements?.length && !fetcherCredentialsSatisfied(key)) {
        const hint = humanizeMissingRequirements(src.missingRequirements);
        appendLine(
          `[warning: ${hint} - open Connections before running]`,
          'meta',
        );
      }
      const cmdSuffix = refresh ? ' --refresh' : '';
      appendLine(`$ ${src.cmd}${cmdSuffix}`, 'cmd');
    }

    const url = `/api/run/${encodeURIComponent(key)}${refresh ? '?refresh=1' : ''}`;
    let res;
    try {
      res = await fetchWithTimeoutAndProbe(url, { method: 'POST' });
    } catch (err) {
      appendLine(`[client] cannot reach server: ${err}`, 'stderr');
      setStatus('failed');
      return;
    }
    if (res.status === 409) {
      const txt = await res.text().catch(() => '');
      appendLine(`[server 409] ${txt || 'already queued or running'}`, 'stderr');
      appendLine('[syncing queue state…]', 'meta');
      await syncFromServer();
      return;
    }
    if (!res.ok) {
      invalidateApiProbe();
      const txt = await res.text().catch(() => '');
      appendLine(`[server ${res.status}] ${txt || 'submit failed'}`, 'stderr');
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
      appendLine(`(queue ${queueExtra})`, 'meta');
      syncLogPanelChrome(src, 'queued', queueExtra);
    } else if (snapAfterSubmit?.active?.id === runId) {
      syncLogPanelChrome(src, snapAfterSubmit.active.status);
    } else if (liveRunId && liveRunId !== runId) {
      const liveSrc = sourcesByRunId.get(liveRunId)?.src;
      appendLine(`(queued after ${liveSrc?.label || 'current run'})`, 'meta');
    }
    subscribe(runId, key, src);
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
    // Respect the global cap. Wait for an open slot between submits so we
    // never stack the queue beyond 1 active + 1 queued, matching the rule
    // the server enforces and the chip-disable logic in chipHtml.
    for (const key of staleKeys) {
      try {
        await waitForQueueSlot();
        await run(key);
      } catch (err) {
        appendLine(`[run stale aborted: ${err}]`, 'stderr');
        break;
      }
    }
  }

  async function subscribe(runId, key, src, { reconnect = false, quiet = false, queuedOnly = false } = {}) {
    if (suppressedRunIds.has(runId)) return;
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
              appendLine(`[reconnected · ${src.label} ${stateWord}]`, 'meta');
            }
          } else {
            appendLine(`--- ${src.label} starting ---`, 'meta');
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
        appendLine(
          `[${src.label}: exit ${data.exit_code}] ${outcome}${duration ? ` in ${duration}` : ''}`,
          'meta',
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
        appendLine(`[client] parse error on done: ${err}`, 'stderr');
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
      if (suppressedRunIds.has(runId)) return;
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
          appendLine(`[${src.label}: stream dropped after exit ${finished.exit_code}]`, 'meta');
          if (liveRunId === runId) setStatus(ok ? 'done' : 'failed');
          if (ok && finished.id !== _lastAppliedDoneRunId) {
            _lastAppliedDoneRunId = finished.id;
            await refreshAfterFetch(key);
          }
          if (!ok && finished.status === 'done') {
            handleFetcherAuthOutcome(key, finished, '');
          }
          markChipState(key, null);
          if (liveRunId === runId) liveRunId = null;
          return;
        }
      } catch (_) {}
      appendLine(
        `[${src.label}: stream error - server stopped, too many tabs, or connection limit (${MAX_SSE_HINT})]`,
        'stderr',
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
      appendLine(`[client] reload failed: ${err}`, 'stderr');
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
          appendLine(`[reconnected · ${parts.join(', ')}]`, 'meta');
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
        const queuedOnly = run.status === 'queued' && snap.active?.id !== run.id;
        subscribe(run.id, run.key, src, { reconnect: true, quiet: true, queuedOnly });
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

  function _runDashboardPollTick() {
    if (isPageHidden()) return;
    syncFromServer();
    maybeAutoRefreshItad();
  }

  function startDashboardPolling() {
    _dashboardPollWanted = true;
    if (pollTimer || !isApiAvailable() || isPageHidden()) return;
    maybeAutoRefreshItad();
    pollTimer = setInterval(_runDashboardPollTick, 30_000);
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
    setBarSummary(text) {
      lastBarSummary = text;
    },
    syncLogHeightToCard,
    flushLinesNow,
    appendLineForTest(text, kind = 'stdout') {
      appendLine(text, kind);
    },
    setFollowTailForTest(val) {
      followTail = !!val;
      clearFollowTailIdleTimer();
    },
    syncLogPanelChrome,
    fetchWithTimeout: fetchWithTimeoutAndProbe,
    cancelInFlightRuns,
    applyServerSnapshotInFlight,
    getLastServerInFlight: () => lastServerInFlight,
    streamUrlForTest: streamUrl,
    recordLineSeqForTest: recordLineSeq,
    getLastSeqForTest: getLastSeq,
    reconcileRunStateFromSnapshot,
    isCancelInFlightForTest: () => cancelInFlight,
    markChipStateForTest(key, state, runId = null) {
      markChipState(key, state, runId);
    },
  };
})();

export function renderDashboardFetcherHealth() {
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return;
  const restoreBarToggleFocus = document.activeElement?.matches?.('[data-role="bar-toggle"]');
  const showOnlyStale = !!state.prefs.fetcherHealthStaleOnly;
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
  const visible = showOnlyStale
    ? rows.filter(r => r.status === 'stale' || r.status === 'missing')
    : rows;
  const rank = { missing: 0, stale: 1, recent: 2, fresh: 3 };
  visible.sort((a, b) => rank[a.status] - rank[b.status] || a.src.label.localeCompare(b.src.label));

  const profileLabel = document.getElementById('profileMenuLabel')?.textContent?.trim()
    || activeProfileId();
  const summaryParts = [];
  if (staleRows.length) summaryParts.push(`${staleRows.length} stale`);
  if (missingRows.length) summaryParts.push(`${missingRows.length} missing`);
  const healthSummary = summaryParts.length ? summaryParts.join(' · ') : 'All fresh';
  const summaryText = `Profile: ${profileLabel} · ${healthSummary}`;
  fetcherRunner.setBarSummary(summaryText);
  const apiReady = fetcherRunner.isApiAvailable();
  const probeDone = fetcherRunner.apiProbeFinished();
  const showReadonly = probeDone && !apiReady;
  const summaryTooltip = [
    'Click a chip → run an incremental sync (fast - fills gaps, uses cache where safe).',
    'Shift+click → force a full refresh that ignores local cache (slower; only on chips that support it).',
    'Hover any chip to see exactly what click vs. Shift+click will do for that source.',
  ].join('\n');
  const apiNotice = apiReady
    ? `<span class="fh-summary" title="${escapeAttr(summaryTooltip)}">· click = sync · Shift+click = full refresh</span>`
    : '';
  const readonlyBanner = showReadonly
    ? (isAccountAuthMode()
      ? `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only — the server API did not respond (sign in, restart
          <code>python server.py</code>, or check the terminal for errors).
        </div>`
      : `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only. Run <code>python server.py</code> and open
          <a href="http://127.0.0.1:8765" class="fh-readonly-link">http://127.0.0.1:8765</a>
          to click chips and stream logs.
        </div>`)
    : '';

  function chipHtml({ src, status, count, ageLabel, iso }) {
    const covLabel = ENRICH_KEYS.has(src.key) ? coverageLabel(src.key) : null;
    const countStr = covLabel != null
      ? covLabel
      : (count != null && count > 0 ? formatNum(count) : ' - ');
    const fetchedLine = iso ? new Date(iso).toLocaleString() : 'not loaded';
    const runState = fetcherRunner.stateFor(src.key);
    const provider = reconnectProviderForFetcher(src.key);
    const needsReconnect = !runState && isFetcherReconnectRequired(src.key);
    const disconnected = !runState && !needsReconnect && isFetcherDisconnected(src.key);
    const connectProvider = connectProviderForFetcher(src.key);
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
    const queueFullElsewhere = fetcherRunner.inFlightCount() >= 2 && !runState;
    if (queueFullElsewhere) {
      titleLines.push('Queue full - one run is in progress and one is queued. Wait for a slot.');
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
      const plats = (src.platforms || []).join(', ') || 'Windows';
      titleLines.push(`Unavailable on this OS - ${src.label} runs on ${plats} only.`);
    }
    const title = titleLines.join('\n');
    // Disconnected chips stay clickable — the click routes to Connections to
    // connect (handled in bind-events via data-fetcher-connect), not to a run.
    const disabled = platformUnavailable || !apiReady || runState === 'running' || runState === 'queued' || queueFullElsewhere || inAuthCooldown || needsReconnect;
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
      : (needsReconnect ? 'reconnect' : (disconnected ? 'connect' : (inAuthCooldown ? authCooldownLabel(authCooldownMs) : ageLabel)));
    if (persistFailed && !runState) ageText = 'failed';
    else if (status === 'missing' && ageLabel === '?' && (count === 0 || count == null)) ageText = 'empty';
    const connectAttr = disconnected && connectProvider
      ? ` data-fetcher-connect="${escapeAttr(connectProvider)}"`
      : '';
    const chipBtn = `<button type="button" class="fh-chip fh-chip-${escapeAttr(displayStatus)}${needsClass}${readonlyClass}${cooldownClass}${reconnectClass}${disconnectedClass}${unavailableClass}" data-fetcher-key="${escapeAttr(src.key)}" data-status="${escapeAttr(status)}"${connectAttr} style="border-left: 3px solid ${escapeAttr(src.color)}" title="${escapeAttr(title)}"${disabled ? ' disabled' : ''} aria-disabled="${disabled ? 'true' : 'false'}">
      <span class="fh-chip-dot"></span>
      ${warnBadge}
      <span class="fh-chip-label">${escapeHtml(src.label)}</span>
      <span class="fh-chip-count">${escapeHtml(countStr)}</span>
      <span class="fh-chip-age">${escapeHtml(ageText)}</span>
    </button>`;
    const reconnectControls = needsReconnect
      ? `<button type="button" class="fh-chip-reconnect-btn" data-fetcher-reconnect data-provider="${escapeAttr(provider)}" title="Reconnect ${escapeAttr(src.label)}">Reconnect</button>
         <button type="button" class="fh-chip-reconnect-dismiss" data-fetcher-reconnect-dismiss data-provider="${escapeAttr(provider)}" aria-label="Dismiss reconnect hint">&times;</button>`
      : '';
    const chip = needsReconnect
      ? `<div class="fh-chip-wrap fh-chip-wrap--reconnect">${chipBtn}${reconnectControls}</div>`
      : chipBtn;
    if (src.key === 'itad') {
      return chip + `<label class="fh-toggle fh-itad-auto" title="Runs ITAD up to once per hour between 7am and midnight when the dashboard is open.">
        <input id="itadAutoRefreshToggle" type="checkbox" class="rounded" ${state.prefs.itadAutoRefreshDisabled ? '' : 'checked'} />
        Auto-refresh
      </label>`;
    }
    return chip;
  }

  const chipsHtml = visible.length
    ? (showOnlyStale
      ? `<div class="fh-group-chips">${visible.map(chipHtml).join('')}</div>`
      : GROUP_ORDER.map(group => {
          let groupRows = visible.filter(r => r.src.group === group);
          if (!groupRows.length) return '';
          if (group === 'enrich') {
            const ord = k => {
              const i = ENRICH_ORDER.indexOf(k);
              return i < 0 ? ENRICH_ORDER.length : i;
            };
            groupRows = [...groupRows].sort((a, b) => ord(a.src.key) - ord(b.src.key));
          }
          return `<div class="fh-group">
            <div class="fh-group-label">${escapeHtml(GROUP_LABELS[group] || group)}</div>
            <div class="fh-group-chips">${groupRows.map(chipHtml).join('')}</div>
          </div>`;
        }).join(''))
    : '<span class="fh-empty">No stale or missing fetchers - nice.</span>';

  const staleBtnDisabled = !apiReady || !runnableStale.length || Date.now() < runStaleCooldownUntil;
  const staleBtnLabel = `Run stale (${runnableStale.length})`;

  slot.innerHTML = `
    <div class="fh-bar" data-role="fetcher-bar" title="Click status or tail to expand when collapsed">
      <span class="fh-bar-dot" data-role="bar-dot" aria-hidden="true"></span>
      <span class="fh-bar-status" data-role="bar-status">Fetcher health</span>
      <span class="fh-bar-tail" data-role="bar-tail">No fetcher activity yet.</span>
      <button type="button" class="fh-bar-toggle" data-role="bar-toggle" aria-expanded="false" aria-label="Expand fetcher">▸</button>
    </div>
    ${readonlyBanner}
    <div class="fh-head${apiReady ? '' : ' fh-readonly'}">
      <div class="fh-head-left">
        <span class="fh-title">Fetcher health</span>
        <span class="fh-summary">${escapeHtml(summaryText)}</span>
        ${apiNotice}
      </div>
      <div class="fh-head-actions">
        <button type="button" class="fh-log-open" title="Expand fetcher health and run log">Log</button>
        <button type="button" class="fh-run-stale" ${staleBtnDisabled ? 'disabled' : ''} title="Queue every stale or missing fetcher that has credentials">${escapeHtml(staleBtnLabel)}</button>
        <label class="fh-toggle">
          <input id="fetcherHealthStaleOnly" type="checkbox" class="rounded" ${showOnlyStale ? 'checked' : ''} />
          Only stale / missing
        </label>
        <label class="fh-toggle" title="After a library fetch adds new games, queue HLTB, Reviews, Covers, and Co-op tags">
          <input id="autoEnrichOnAddToggle" type="checkbox" class="rounded" ${state.prefs.autoEnrichOnAdd !== false ? 'checked' : ''} />
          Auto-enrich new games
        </label>
      </div>
    </div>
    <details class="fh-legend">
      <summary>Legend</summary>
      <div class="fh-legend-items">
        <span class="fh-legend-item"><span class="fh-chip-warn" aria-hidden="true">!</span> missing keys for this profile</span>
        <span class="fh-legend-item">dim dashed = never fetched</span>
        <span class="fh-legend-item">dot color = cache age</span>
        <span class="fh-legend-item">reconnect = session expired (Connections, not these chips)</span>
      </div>
    </details>
    <div class="fh-chips">${chipsHtml}</div>
  `;
  ensureAgeTicker();
  fetcherRunner.applyFetcherRowLayout();
  if (restoreBarToggleFocus) {
    document.querySelector('[data-role="bar-toggle"]')?.focus();
  }
}
