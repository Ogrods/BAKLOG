import { state, ITCH_NON_GAME_CLASSIFICATIONS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { noteFetcherAuthFailure } from './connections.js';

const FRESH_THRESHOLDS = { fresh: 7 * 86400000, recent: 30 * 86400000 };
// ITAD is a deal feed — library-style 7d/30d thresholds are misleading.
const STALE_OVERRIDES = {
  itad: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
};
export const ITAD_LAST_AUTO_RUN_KEY = 'itad-last-auto-run';
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
const ENRICH_KEYS = new Set(['hltb', 'steamReviews', 'steamCovers', 'steamTags']);
const MAX_SSE_HINT = 'max 8 live streams';
const GROUP_ORDER = ['library', 'wishlist', 'prices', 'enrich'];
const GROUP_LABELS = {
  library: 'Library',
  wishlist: 'Wishlist',
  prices: 'Prices',
  enrich: 'Enrichment',
};

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
  steam: 'Sync your Steam library — picks up new purchases & updated playtime',
  gog: 'Sync your GOG library — picks up new purchases & metadata',
  psn: 'Sync your PSN library',
  epic: 'Sync your Epic library',
  amazon: 'Sync your Amazon Prime Gaming library',
  xbox: 'Sync your Xbox library',
  battlenet: 'Sync your Battle.net library',
  ubisoft: 'Sync your Ubisoft Connect library',
  nintendo: 'Sync your Nintendo Switch library',
  itch: 'Sync your itch.io library',
  wishlistSteam: 'Sync your Steam wishlist',
  wishlistGog: 'Sync your GOG wishlist',
  wishlistEpic: 'Sync your Epic wishlist',
  wishlistPsn: 'Sync your PlayStation Store wishlist',
  wishlistUbisoft: 'Sync your Ubisoft Store wishlist',
  wishlistXbox: 'Sync your Xbox Store wishlist',
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
  hltb: 'Also retry titles previously cached as "no HLTB match" — use after HLTB adds new entries',
  steamReviews:
    'Also retry titles previously cached as "no Steam app match" — use after Steam lists the game',
  steamCovers: 'Also retry rows previously cached as "no Steam match" — use after Steam adds new entries',
  steamTags: 'Re-fetch Steam appdetails ignoring the local cache — picks up newly-added Steam categories',
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
    return `Re-tries ${formatNum(pending.retry)} previously-attempted rows that didn't return data. Usually won't change the score — safe to skip.`;
  }
  if (pending.noMatch > 0) {
    const note = src.supportsRefresh
      ? ' Use Shift+click to retry them.'
      : '';
    return `Nothing new to look up — the remaining ${formatNum(pending.noMatch)} are cached as "no match".${note}`;
  }
  return 'Everything is enriched — nothing to do.';
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
  if (!total) return '—';
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
    line += ` ${formatNum(pending.retry)} were tried before with no review score — clicking will re-check but rarely changes the number.`;
  } else if (pending.noMatch > 0) {
    const src = key === 'hltb' ? 'HowLongToBeat' : 'Steam';
    line += ` Remaining ${formatNum(pending.noMatch)} have no match on ${src} — clicking won't add more.`;
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
    const res = await fetch('/api/fetchers');
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
  const running = [];
  const queued = [];
  for (const [key, st] of runStateByKey) {
    const src = sourceFn(key);
    const label = src?.label || key;
    if (st === 'running') running.push(label);
    else if (st === 'queued') queued.push(label);
  }
  if (!running.length && !queued.length) {
    el.classList.add('hidden');
    el.textContent = '';
    el.title = 'Show fetcher log';
    return;
  }
  el.classList.remove('hidden');
  let text;
  if (running.length) {
    const extra = queued.length ? ` (+${queued.length} queued)` : '';
    text = `Fetching: ${running.join(', ')}${extra}`;
  } else {
    text = `Queued: ${queued.join(', ')}`;
  }
  el.textContent = text;
  el.title = `${text} — click to show log`;
}

export function humanizeAge(ms) {
  if (!Number.isFinite(ms)) return '—';
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
    return { status: 'missing', ageMs: Infinity, count, ageLabel: meta ? '?' : '—', iso: null };
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
export function maybeAutoRefreshItad(deps = {}) {
  if (state.prefs.itadAutoRefreshDisabled) return false;
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

export const fetcherRunner = (() => {
  let apiAvailable = null;
  const runStateByKey = new Map();
  // One EventSource per run (queued or running). Keeping all of them open
  // means a still-running fetcher keeps streaming lines even after the user
  // queues another one, and every run gets its own `done` event so its chip
  // can clear independently.
  const sourcesByRunId = new Map();
  const reconnectTimers = new Map();
  const reconnectAttempts = new Map();
  /** Run ids the user cancelled — do not reconnect or re-subscribe until gone from server. */
  const suppressedRunIds = new Set();
  const RECONNECT_BASE_MS = 2000;
  const RECONNECT_MAX_MS = 30000;
  const RECONNECT_MAX_ATTEMPTS = 8;
  let runsSnapshotPromise = null;
  let runsSnapshotAt = 0;
  const RUNS_SNAPSHOT_MIN_MS = 1500;

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

  async function fetchRunsSnapshot() {
    const now = Date.now();
    if (runsSnapshotPromise && now - runsSnapshotAt < RUNS_SNAPSHOT_MIN_MS) {
      return runsSnapshotPromise;
    }
    runsSnapshotAt = now;
    runsSnapshotPromise = fetch('/api/runs')
      .then(r => (r.ok ? r.json() : null))
      .catch(() => null)
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
    const live = new Set();
    if (snap.active) live.add(snap.active.id);
    for (const q of snap.queue || []) live.add(q.id);
    for (const id of suppressedRunIds) {
      if (!live.has(id)) suppressedRunIds.delete(id);
    }
  }

  function scheduleReconnect(runId, key, src) {
    if (suppressedRunIds.has(runId)) return;
    if (reconnectTimers.has(runId)) return;
    const attempt = (reconnectAttempts.get(runId) || 0) + 1;
    if (attempt > RECONNECT_MAX_ATTEMPTS) {
      reconnectAttempts.delete(runId);
      appendLine(
        `[${src.label}: stream dropped too many times — refresh the page or use Cancel]`,
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
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempt - 1), RECONNECT_MAX_MS);
    appendLine(`[${src.label}: stream dropped — reconnecting in ${Math.round(delay / 1000)}s]`, 'meta');
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
  let pollTimer = null;
  let syncedOnce = false;
  /** Avoid re-running refreshAfterFetch on every dashboard tab return when syncFromServer
   *  keeps seeing the same recent "done" run in the 5-minute window. */
  let _lastAppliedDoneRunId = null;

  function logPanel() {
    if (!logEl) logEl = document.getElementById('fetcherRunLog');
    return logEl;
  }

  function logBody() {
    if (!logBodyEl || !document.body.contains(logBodyEl)) {
      logBodyEl = logPanel()?.querySelector('.fh-log-body') || null;
    }
    return logBodyEl;
  }

  function invalidateApiProbe() {
    apiAvailable = null;
  }

  async function probeApi(force = false) {
    if (force) apiAvailable = null;
    if (apiAvailable !== null) return apiAvailable;
    try {
      await loadFetcherSources(force);
      const res = await fetch('/api/fetchers', { method: 'GET' });
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
    return new Promise(resolve => {
      const tick = () => {
        if (!isQueueFull()) resolve();
        else setTimeout(tick, 200);
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
        <button type="button" class="fh-log-btn fh-log-btn-cancel hidden" data-role="cancel">Cancel</button>
        <button type="button" class="fh-log-btn" data-role="clear">Clear</button>
        <button type="button" class="fh-log-btn" data-role="close">Close</button>
      </div>
      <div class="fh-log-body" data-role="body"></div>
    `;
    panel.dataset.built = '1';
    panel.addEventListener('click', e => {
      const btn = e.target.closest('[data-role]');
      if (!btn) return;
      if (btn.dataset.role === 'close') closePanel();
      else if (btn.dataset.role === 'clear') clearLog();
      else if (btn.dataset.role === 'cancel') cancelInFlightRuns();
    });
    return panel;
  }

  function ensurePanel(src) {
    const panel = buildLogPanelChrome();
    if (!panel) return;
    panel.classList.add('open');
    panel.querySelector('[data-role="title"]').textContent = src ? `Running: ${src.label}` : 'Fetcher log';
    setStatus('queued');
    updateCancelButton();
    logBodyEl = panel.querySelector('[data-role="body"]');
  }

  /**
   * Reopen the run-log panel (e.g. after the user clicked Close mid-run and
   * wants it back). Builds the chrome shell if it hasn't been built yet so
   * the kebab "Show fetcher log" entry works on a fresh page load with no
   * activity. Doesn't change status or clear existing log lines — preserves
   * whatever's already there so the user picks up where they left off.
   *
   * Note: the panel lives inside #dashboardContainer; callers from other
   * views should switchView('dashboard') first so it's actually visible.
   * @returns {boolean} true if the panel exists and was opened.
   */
  function reopenLogPanel() {
    const panel = buildLogPanelChrome();
    if (!panel) return false;
    panel.classList.add('open');
    const body = panel.querySelector('[data-role="body"]');
    if (body && !body.children.length) {
      const empty = document.createElement('div');
      empty.className = 'fh-log-empty';
      empty.textContent = 'No fetcher activity yet. Run a fetcher from the dashboard chips to populate.';
      body.appendChild(empty);
    }
    logBodyEl = body || null;
    return true;
  }

  function updateCancelButton() {
    const panel = logPanel();
    if (!panel) return;
    const btn = panel.querySelector('[data-role="cancel"]');
    if (!btn) return;
    const show = inFlightCount() > 0 && isApiAvailable();
    btn.classList.toggle('hidden', !show);
    btn.disabled = !show;
  }

  async function cancelInFlightRuns() {
    if (!isApiAvailable() || inFlightCount() === 0) return;
    let snap = null;
    try {
      snap = await fetchRunsSnapshot();
    } catch (_) {}
    const ids = [];
    if (snap?.active) ids.push(snap.active.id);
    for (const q of snap?.queue || []) ids.push(q.id);
    for (const id of ids) suppressedRunIds.add(id);
    closeAllStreams();
    for (const key of [...runStateByKey.keys()]) markChipState(key, null);
    liveRunId = null;
    setStatus('failed');
    updateCancelButton();
    renderDashboardFetcherHealth();
    try {
      const res = await fetch('/api/runs/cancel', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        const n = data.cancelled?.length ?? 0;
        appendLine(n ? `[cancelled ${n} run(s)]` : '[cancelled]', 'meta');
      } else {
        const txt = await res.text().catch(() => '');
        appendLine(`[cancel failed ${res.status}] ${txt}`, 'stderr');
      }
    } catch (err) {
      appendLine(`[cancel failed] ${err}`, 'stderr');
    }
    try {
      snap = await fetchRunsSnapshot();
      pruneSuppressedRuns(snap);
    } catch (_) {}
  }

  function closePanel() {
    logPanel()?.classList.remove('open');
  }

  function clearLog() {
    const body = logBody();
    if (body) body.innerHTML = '';
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
      if (status === 'running' || status === 'queued') {
        body.setAttribute('data-running', '1');
      } else {
        body.removeAttribute('data-running');
      }
    }
  }

  function appendLine(text, kind = 'stdout') {
    const body = logBody();
    if (!body) return;
    const div = document.createElement('div');
    div.className = `fh-log-line ${kind}`;
    div.textContent = text;
    body.appendChild(div);
    while (body.children.length > 4000) body.removeChild(body.firstChild);
    body.scrollTop = body.scrollHeight;
  }

  function markChipState(key, runState) {
    if (runState) runStateByKey.set(key, runState);
    else runStateByKey.delete(key);
    updateGlobalFetcherIndicator(runStateByKey, source);
    renderDashboardFetcherHealth();
  }

  async function run(key, { refresh = false, auto = false } = {}) {
    if (!isApiAvailable()) return;
    await loadFetcherSources(true);
    const src = source(key);
    if (!src || runStateByKey.has(key)) return;
    // Hard cap mirrors server-side enforcement (max 1 active + 1 queued).
    // Without this guard a fast double-click could land two POSTs before the
    // server's lock saw the first one as pending.
    if (isQueueFull()) {
      ensurePanel(src);
      appendLine(
        `[${src.label}: queue full — one run is in progress and one is queued]`,
        'meta',
      );
      return;
    }
    if (refresh && !src.supportsRefresh) {
      appendLine(
        `[${src.label}: this fetcher has no force-refresh mode — a normal click already pulls the latest data]`,
        'stderr',
      );
      return;
    }

    if (auto && key === 'itad') {
      itadPendingAutoRun = true;
    } else {
      ensurePanel(src);
      if (src.missingRequirements?.length) {
        appendLine(
          `[warning: ${src.missingRequirements.join(', ')} not set — run will likely fail]`,
          'meta',
        );
      }
      const cmdSuffix = refresh ? ' --refresh' : '';
      appendLine(`$ ${src.cmd}${cmdSuffix}`, 'cmd');
    }
    markChipState(key, 'queued');

    const url = `/api/run/${encodeURIComponent(key)}${refresh ? '?refresh=1' : ''}`;
    let res;
    try {
      res = await fetch(url, { method: 'POST' });
    } catch (err) {
      invalidateApiProbe();
      appendLine(`[client] cannot reach server: ${err}`, 'stderr');
      setStatus('failed');
      markChipState(key, null);
      return;
    }
    if (res.status === 409) {
      const txt = await res.text().catch(() => '');
      appendLine(`[server 409] ${txt || 'already queued or running'}`, 'stderr');
      markChipState(key, null);
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
    if (liveRunId && liveRunId !== runId) {
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
        if (src.missingRequirements?.length) return false;
        if (runStateByKey.has(src.key)) return false;
        return true;
      })
      .map(src => src.key);
    if (!staleKeys.length) return;
    // Respect the global cap. Wait for an open slot between submits so we
    // never stack the queue beyond 1 active + 1 queued, matching the rule
    // the server enforces and the chip-disable logic in chipHtml.
    for (const key of staleKeys) {
      await waitForQueueSlot();
      await run(key);
    }
  }

  function subscribe(runId, key, src, { reconnect = false } = {}) {
    if (suppressedRunIds.has(runId)) return;
    clearReconnect(runId);
    const prior = sourcesByRunId.get(runId);
    if (prior) {
      try { prior.es.close(); } catch (_) {}
      sourcesByRunId.delete(runId);
    }
    const es = new EventSource(`/api/stream/${encodeURIComponent(runId)}`);
    sourcesByRunId.set(runId, { es, key, src });
    const recentLog = [];

    es.addEventListener('status', evt => {
      try {
        const data = JSON.parse(evt.data);
        if (data.status === 'running') {
          markChipState(key, 'running');
          liveRunId = runId;
          const panel = logPanel();
          if (panel) panel.querySelector('[data-role="title"]').textContent = `Running: ${src.label}`;
          if (reconnect) {
            appendLine(`[reconnected · ${src.label} running]`, 'meta');
          } else {
            appendLine(`--- ${src.label} starting ---`, 'meta');
          }
          setStatus('running');
          updateCancelButton();
        } else if (data.status === 'queued') {
          markChipState(key, 'queued');
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
        if (liveRunId === runId) {
          setStatus(cancelled ? 'failed' : ok ? 'done' : 'failed', duration);
          updateCancelButton();
        }
        if (ok) {
          await refreshAfterFetch(key);
          markChipState(key, null);
        } else if (cancelled) {
          markChipState(key, null);
        } else {
          markChipState(key, 'failed');
          noteFetcherAuthFailure(key, recentLog.join('\n'));
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
        try { es.close(); } catch (_) {}
        sourcesByRunId.delete(runId);
        if (liveRunId === runId) {
          liveRunId = null;
          updateCancelButton();
        }
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
          scheduleReconnect(runId, key, src);
          return;
        }
        if (finished) {
          const ok = finished.status === 'done' && finished.exit_code === 0;
          appendLine(`[${src.label}: stream dropped after exit ${finished.exit_code}]`, 'meta');
          if (liveRunId === runId) setStatus(ok ? 'done' : 'failed');
          if (ok) await refreshAfterFetch(key);
          markChipState(key, null);
          if (liveRunId === runId) liveRunId = null;
          return;
        }
      } catch (_) {}
      appendLine(
        `[${src.label}: stream error — server stopped, too many tabs, or connection limit (${MAX_SSE_HINT})]`,
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
  }

  /** Re-attach SSE streams after a page load (or tab return). */
  async function syncFromServer() {
    if (!isApiAvailable()) return;
    await loadFetcherSources(true);
    let snap;
    try {
      snap = await fetchRunsSnapshot();
      if (!snap) return;
    } catch {
      return;
    }
    pruneSuppressedRuns(snap);

    const pending = [];
    if (snap.active) pending.push(snap.active);
    for (const q of snap.queue || []) pending.push(q);

    if (pending.length) {
      const panelSrc = source(snap.active?.key) || source(pending[0].key);
      ensurePanel(panelSrc);
      const isFirstSync = !syncedOnce;
      syncedOnce = true;
      if (isFirstSync) {
        appendLine('[reconnected to in-flight fetcher(s)]', 'meta');
      }
      for (const run of pending) {
        if (suppressedRunIds.has(run.id)) continue;
        const src = source(run.key);
        if (!src) continue;
        const chipState = run.status === 'running' ? 'running' : 'queued';
        markChipState(run.key, chipState);
        if (run.status === 'running') liveRunId = run.id;
        if (sourcesByRunId.has(run.id)) continue;
        subscribe(run.id, run.key, src, { reconnect: true });
      }
      updateCancelButton();
      if (snap.active?.status === 'running') setStatus('running');
      else if (snap.queue?.length) setStatus('queued');
      renderDashboardFetcherHealth();
      updateGlobalFetcherIndicator(runStateByKey, source);
      return;
    }

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

  function startDashboardPolling() {
    if (pollTimer || !isApiAvailable()) return;
    maybeAutoRefreshItad();
    pollTimer = setInterval(() => {
      syncFromServer();
      maybeAutoRefreshItad();
    }, 30_000);
  }

  function stopDashboardPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  return {
    probeApi,
    invalidateApiProbe,
    isApiAvailable,
    apiProbeFinished,
    stateFor,
    inFlightCount,
    isQueueFull,
    run,
    runAllStale,
    syncFromServer,
    startDashboardPolling,
    stopDashboardPolling,
    closeAllStreams,
    reopenLogPanel,
  };
})();

export function renderDashboardFetcherHealth() {
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return;
  const showOnlyStale = !!state.prefs.fetcherHealthStaleOnly;
  const rows = fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
  const staleRows = rows.filter(r => r.status === 'stale');
  const missingRows = rows.filter(r => r.status === 'missing');
  const runnableStale = rows.filter(r => {
    if (r.status !== 'stale' && r.status !== 'missing') return false;
    if (r.src.missingRequirements?.length) return false;
    if (fetcherRunner.stateFor(r.src.key)) return false;
    return true;
  });
  const visible = showOnlyStale
    ? rows.filter(r => r.status === 'stale' || r.status === 'missing')
    : rows;
  const rank = { missing: 0, stale: 1, recent: 2, fresh: 3 };
  visible.sort((a, b) => rank[a.status] - rank[b.status] || a.src.label.localeCompare(b.src.label));

  const summaryParts = [];
  if (staleRows.length) summaryParts.push(`${staleRows.length} stale`);
  if (missingRows.length) summaryParts.push(`${missingRows.length} missing`);
  const summaryText = summaryParts.length ? summaryParts.join(' · ') : 'All fresh';
  const apiReady = fetcherRunner.isApiAvailable();
  const probeDone = fetcherRunner.apiProbeFinished();
  const showReadonly = probeDone && !apiReady;
  const summaryTooltip = [
    'Click a chip → run an incremental sync (fast — fills gaps, uses cache where safe).',
    'Shift+click → force a full refresh that ignores local cache (slower; only on chips that support it).',
    'Hover any chip to see exactly what click vs. Shift+click will do for that source.',
  ].join('\n');
  const apiNotice = apiReady
    ? `<span class="fh-summary" title="${escapeAttr(summaryTooltip)}">· click = sync · Shift+click = full refresh</span>`
    : '';
  const readonlyBanner = showReadonly
    ? `<div class="fh-readonly-banner" role="status">
        Fetcher health is read-only. Run <code>python server.py</code> and open
        <a href="http://127.0.0.1:8765" class="fh-readonly-link">http://127.0.0.1:8765</a>
        to click chips and stream logs.
      </div>`
    : '';

  function chipHtml({ src, status, count, ageLabel, iso }) {
    const covLabel = ENRICH_KEYS.has(src.key) ? coverageLabel(src.key) : null;
    const countStr = covLabel != null
      ? covLabel
      : (count != null && count > 0 ? formatNum(count) : '—');
    const fetchedLine = iso ? new Date(iso).toLocaleString() : 'not loaded';
    const runState = fetcherRunner.stateFor(src.key);
    const displayStatus = runState || status;
    const runLabel = runState ? ` · ${runState.toUpperCase()}` : '';
    const needsConfig = (src.missingRequirements || []).length > 0;
    const configHint = needsConfig
      ? ` · missing: ${src.missingRequirements.join(', ')} (see README / .env.example)`
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
          configHint ? `Note: ${src.missingRequirements.join(', ')} not set (see README / .env.example)` : '',
        ].filter(Boolean)
      : [
          `${src.label} · ${countStr} · fetched ${fetchedLine}`,
          enrichLine,
          `Click: ${clickHint}`,
          `Command: ${src.cmd}`,
          configHint ? `Note: ${src.missingRequirements.join(', ')} not set (see README / .env.example)` : '',
          'Server is offline — start `python server.py` to run fetchers from the UI.',
        ].filter(Boolean);
    // Disable when the queue cap is reached AND this chip isn't already in
    // the pipeline — without this, clicking a third chip while two are
    // active/queued would silently 409 on the server. inFlightCount comes
    // from fetcherRunner so chipHtml never touches the runner's private
    // runStateByKey directly.
    const queueFullElsewhere = fetcherRunner.inFlightCount() >= 2 && !runState;
    if (queueFullElsewhere) {
      titleLines.push('Queue full — one run is in progress and one is queued. Wait for a slot.');
    }
    const title = titleLines.join('\n');
    const disabled = !apiReady || runState === 'running' || runState === 'queued' || queueFullElsewhere;
    const needsClass = needsConfig ? ' fh-chip-needs-config' : '';
    const readonlyClass = !apiReady ? ' fh-chip-readonly' : '';
    const warnBadge = needsConfig ? '<span class="fh-chip-warn" title="Missing credentials">!</span>' : '';
    return `<button type="button" class="fh-chip fh-chip-${displayStatus}${needsClass}${readonlyClass}" data-fetcher-key="${escapeAttr(src.key)}" data-status="${escapeAttr(status)}" style="border-left: 3px solid ${escapeAttr(src.color)}" title="${escapeAttr(title)}"${disabled ? ' disabled' : ''} aria-disabled="${disabled ? 'true' : 'false'}">
      <span class="fh-chip-dot"></span>
      ${warnBadge}
      <span class="fh-chip-label">${escapeHtml(src.label)}</span>
      <span class="fh-chip-count">${escapeHtml(countStr)}</span>
      <span class="fh-chip-age">${escapeHtml(runState ? runState : ageLabel)}</span>
    </button>`;
  }

  const chipsHtml = visible.length
    ? (showOnlyStale
      ? `<div class="fh-group-chips">${visible.map(chipHtml).join('')}</div>`
      : GROUP_ORDER.map(group => {
          const groupRows = visible.filter(r => r.src.group === group);
          if (!groupRows.length) return '';
          return `<div class="fh-group">
            <div class="fh-group-label">${escapeHtml(GROUP_LABELS[group] || group)}</div>
            <div class="fh-group-chips">${groupRows.map(chipHtml).join('')}</div>
          </div>`;
        }).join(''))
    : '<span class="fh-empty">No stale or missing fetchers — nice.</span>';

  const staleBtnDisabled = !apiReady || !runnableStale.length || Date.now() < runStaleCooldownUntil;
  const staleBtnLabel = `Run stale (${runnableStale.length})`;

  slot.innerHTML = `
    ${readonlyBanner}
    <div class="fh-head${apiReady ? '' : ' fh-readonly'}">
      <div class="fh-head-left">
        <span class="fh-title">Fetcher health</span>
        <span class="fh-summary">${escapeHtml(summaryText)}</span>
        ${apiNotice}
      </div>
      <div class="fh-head-actions">
        <button type="button" class="fh-run-stale" ${staleBtnDisabled ? 'disabled' : ''} title="Queue every stale or missing fetcher that has credentials">${escapeHtml(staleBtnLabel)}</button>
        <label class="fh-toggle">
          <input id="fetcherHealthStaleOnly" type="checkbox" class="rounded" ${showOnlyStale ? 'checked' : ''} />
          Only stale / missing
        </label>
      </div>
    </div>
    <div class="fh-chips">${chipsHtml}</div>
  `;
}
