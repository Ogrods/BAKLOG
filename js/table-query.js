/**
 * Pure filter/sort for the library table (main thread + worker).
 */

import {
  ITCH_NON_GAME_CLASSIFICATIONS,
  isCleanupCandidateFromParts,
} from './state.js';
// Genre canonicalization is single-sourced from genres.js (a worker-safe,
// DOM-free module) so the worker/table path can never drift from the genre
// filter chips / dashboard genre breakdown. See tests/table-query-parity.test.js.
import { gameMatchesGenreFilters } from './genres.js';

const HLTB_BUCKETS_QUERY = [
  { minExclusive: null, maxInclusive: 2 },
  { minExclusive: 2, maxInclusive: 5 },
  { minExclusive: 5, maxInclusive: 10 },
  { minExclusive: 10, maxInclusive: 20 },
  { minExclusive: 20, maxInclusive: 40 },
  { minExclusive: 40, maxInclusive: null },
];

const WORKER_THRESHOLD = 500;
let _worker = null;
let _workerGen = 0;

export function escapeAttr(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/**
 * Snapshot the 6 in-flight filter controls.
 *
 * Reads from the supplied `sessionPrefs` object — typically `state.sessionPrefs`.
 * Pass it explicitly so this module stays importable from the worker (which
 * has no DOM and no live `state` reference).
 */
export function collectTableParams(sessionPrefs) {
  const s = sessionPrefs || {};
  return {
    q: String(s.search || '').trim().toLowerCase(),
    status: s.statusFilter || '',
    unplayed: !!s.unplayedOnly,
    earlyAccess: !!s.earlyAccessOnly,
    gamePass: !!s.gamePassOnly,
    staleOnly: !!s.staleOnly,
    minRating: +(s.minRating || 0),
    maxHours: s.maxHours == null ? 200 : +s.maxHours,
  };
}

const COOP_FILTER_MODES = new Set(['off', 'any', 'online', 'local', 'both']);

/** @returns {'off'|'any'|'online'|'local'|'both'} */
export function resolveCoopFilterMode(prefs) {
  const m = prefs?.coopFilterMode;
  if (COOP_FILTER_MODES.has(m)) return m;
  if (prefs?.coopAny) return 'any';
  return 'off';
}

export function passesCoopFilter(g, mode) {
  if (mode === 'off') return true;
  if (mode === 'any') return !!(g.coop_online || g.coop_local);
  if (mode === 'online') return !!g.coop_online;
  if (mode === 'local') return !!g.coop_local;
  if (mode === 'both') return !!(g.coop_online && g.coop_local);
  return true;
}

export function isEarlyAccess(g) {
  if (!g) return false;
  if (g.early_access === true) return true;
  const tokens = [...(g.genres || []), ...(g.tags || [])];
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i];
    if (typeof t === 'string' && t.toLowerCase().includes('early access')) return true;
  }
  return false;
}

export function isGamePass(g) {
  if (!g) return false;
  if (g.game_pass === true) return true;
  for (const t of g.tags || []) {
    if (typeof t !== 'string') continue;
    const norm = t.toLowerCase().replace(/_/g, '-');
    if (norm === 'game-pass' || norm === 'xbox-game-pass') return true;
  }
  return false;
}

function gameStore(g) {
  return g.store || 'steam';
}

function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id
    ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id ?? g.humble_id ?? g.ea_id;
}

export function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}

function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  return { ...g, store: gameStore(g), id: gameId(g) };
}

export function normalizeNameForDedup(name) {
  return String(name || '')
    .toLowerCase()
    .replace(/[\u2122\u00ae\u00a9]/g, '')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|of the year|game of the year|special|standard|deluxe|collection|anthology|pack|the)\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function getPersonalRecord(personal, g) {
  const key = gameKey(g);
  const found = personal[key] || (typeof personal[gameId(g)] === 'object' ? personal[gameId(g)] : null);
  if (!found) {
    return { status: 'backlog', notes: '', priority: 0, hltb_override: null, hidden: false };
  }
  return {
    status: found.status ?? 'backlog',
    notes: found.notes ?? '',
    priority: found.priority ?? 0,
    hltb_override: found.hltb_override ?? null,
    hidden: found.hidden === true,
  };
}

function hasPersonalEntry(personal, g) {
  const key = gameKey(g);
  return !!(personal[key] || (typeof personal[gameId(g)] === 'object' && personal[gameId(g)]));
}

export function hltbMain(personal, g) {
  const p = getPersonalRecord(personal, g);
  if (p.hltb_override != null && p.hltb_override !== '') return +p.hltb_override;
  return g.hltb_main_hours;
}

export function ratingValue(g) {
  return g.steam_review_percent ?? 0;
}

export function parseReleaseForSort(d) {
  const t = Date.parse(d || '');
  return Number.isNaN(t) ? 0 : t;
}

function parseReleaseYear(d) {
  if (!d) return null;
  const s = String(d);
  const m = s.match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
  if (m) return parseInt(m[1], 10);
  const t = Date.parse(s);
  if (!Number.isNaN(t)) return new Date(t).getUTCFullYear();
  return null;
}

function matchesReleaseYearFilter(g, filterVal) {
  if (!filterVal) return true;
  const y = parseReleaseYear(g.release_date);
  if (y == null) return false;
  const decade = /^(\d{4})s$/.exec(filterVal);
  if (decade) {
    const start = parseInt(decade[1], 10);
    return y >= start && y <= start + 9;
  }
  if (/^\d{4}$/.test(filterVal)) return y === parseInt(filterVal, 10);
  return true;
}

function parsePriceLike(v) {
  if (v == null) return null;
  if (typeof v === 'number') return v;
  const m = String(v).match(/-?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

function getItadForGame(itadByKey, g) {
  const key = gameKey(g);
  if (itadByKey[key]) return itadByKey[key];
  const ng = normalizeGame(g);
  if (ng.store === 'steam' || ng.store === 'wishlist') {
    return itadByKey[`steam:${ng.id}`] || itadByKey[`wishlist:${ng.id}`] || null;
  }
  return null;
}

function normalizeRowCurrency(code) {
  const raw = String(code || '').trim().toUpperCase();
  return /^[A-Z]{3}$/.test(raw) ? raw : '';
}

export function comparableStorePrice(g, displayCcy) {
  const disp = normalizeRowCurrency(displayCcy);
  if (g?.price_amount != null && Number.isFinite(Number(g.price_amount))) {
    return Number(g.price_amount);
  }
  const rowCur = normalizeRowCurrency(g?.currency);
  if (rowCur && disp && rowCur !== disp) return null;
  return parsePriceLike(g.price);
}

export function getDealInfo(itadByKey, g, displayCcy) {
  const itad = getItadForGame(itadByKey, g);
  if (itad && itad.price != null) {
    return {
      price: itad.price,
      cut: itad.cut || 0,
      // Mirror deals.js getDealInfo: a 1-year low counts as a historical low for
      // the wishlist "historical low only" filter and sort, so the worker/table
      // path agrees with the dashboard steals card.
      isHistoricalLow: !!itad.is_historical_low || !!itad.is_historical_low_year,
    };
  }
  const steamPrice = comparableStorePrice(g, displayCcy);
  const cut = g.discount_percent || 0;
  if (steamPrice != null || cut) {
    return { price: steamPrice, cut, isHistoricalLow: false };
  }
  return null;
}

export function isOwnedByTitle(ownedNormNames, name) {
  const n = normalizeNameForDedup(name);
  return !!(n && ownedNormNames.has(n));
}

export function passesDealFilters(ctx, g) {
  const { prefs, ownedNormNames, itadByKey, displayCurrency: displayCcy } = ctx;
  if (prefs.dealHideOwned && isOwnedByTitle(ownedNormNames, g.name)) return false;
  const d = getDealInfo(itadByKey, g, displayCcy);
  const onSale = prefs.dealOnSaleOnly;
  const lowOnly = prefs.dealHistoricalLowOnly;
  const minCut = +(prefs.dealMinDiscount || 0);
  const maxPrice = +(prefs.dealMaxPrice ?? 100);
  if (onSale && (!d || (d.cut || 0) <= 0)) return false;
  if (lowOnly && !(d && d.isHistoricalLow)) return false;
  if (minCut > 0 && (!d || (d.cut || 0) < minCut)) return false;
  if (maxPrice < 100) {
    if (!d) return false;
    if (d.price == null) {
      if (g.manual && (d.cut || 0) > 0) return true;
      return false;
    }
    if (d.price > maxPrice) return false;
  }
  return true;
}

/**
 * Combined playtime for a row, honoring cross-store dedup aggregation.
 * `ctx.combinedPlaytime` is built fresh per query (Map on main thread, hydrated
 * from an array of entries inside the worker — see queryGamesAsync + the worker
 * bridge). Falls back to the row's own `playtime_minutes` when no aggregate.
 */
function rowPlaytime(ctx, g) {
  const entry = ctx?.combinedPlaytime?.get(gameKey(g));
  if (entry != null) return entry;
  return Math.max(0, Number(g.playtime_minutes) || 0);
}

export function isCleanupCandidate(ctx, g) {
  const p = getPersonalRecord(ctx.personal, g);
  const explicitBacklog = hasPersonalEntry(ctx.personal, g) && p.status === 'backlog';
  const norm = normalizeNameForDedup(g.name);
  const played = rowPlaytime(ctx, g) > 0 || !!(norm && ctx.playedTitleNorms?.has(norm));
  const rating = ratingValue(g);
  const releaseMs = parseReleaseForSort(g.release_date);
  return isCleanupCandidateFromParts({ explicitBacklog, played, rating, releaseMs });
}

export function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === 'game') return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

export function priorityScore(ctx, g) {
  const review = ratingValue(g);
  const h = hltbMain(ctx.personal, g) || 20;
  return review / Math.log2(h + 2);
}

export function effectiveDiscountPercent(ctx, g) {
  const d = getDealInfo(ctx.itadByKey, g, ctx.displayCurrency);
  if (d) return d.cut || 0;
  return g.discount_percent || 0;
}

export function effectiveSortPrice(ctx, g) {
  const d = getDealInfo(ctx.itadByKey, g, ctx.displayCurrency);
  if (d && d.price != null) return d.price;
  return comparableStorePrice(g, ctx.displayCurrency);
}

function passesSearchQuery(g, p, q) {
  if (g.name.toLowerCase().includes(q)) return true;
  const notes = String(p.notes || "").toLowerCase();
  if (notes.includes(q)) return true;
  return false;
}

function passesFilter(ctx, g) {
  const { view, prefs, params, personal, hiddenKeys, ownedNormNames } = ctx;
  const ng = normalizeGame(g);
  const p = getPersonalRecord(personal, g);
  if (p.hidden) return false;
  if (view === 'library') {
    if (prefs.storeFilter && ng.store !== prefs.storeFilter) return false;
    if (prefs.releaseYearFilter && !matchesReleaseYearFilter(g, prefs.releaseYearFilter)) return false;
    if (hiddenKeys.has(gameKey(g))) return false;
  }
  if (view === 'wishlist') {
    if (prefs.wishlistStoreFilter) {
      const target = g.wishlist_store || g.store_target || (g.manual ? 'manual' : 'steam');
      if (target !== prefs.wishlistStoreFilter) return false;
    }
    if (hiddenKeys && hiddenKeys.has(gameKey(g))) return false;
    if (!passesDealFilters(ctx, g)) return false;
  }
  if (view === 'itch' && ctx.sessionPrefs?.itchHideNonGames && !itchIsGame(g)) return false;
  if (ctx.cleanupModeActive && view === 'library' && !isCleanupCandidate(ctx, g)) return false;
  if (params.q && !passesSearchQuery(g, p, params.q)) return false;
  if ((view === 'library' || view === 'itch') && params.status) {
    if (params.status === '__none__') {
      if (hasPersonalEntry(personal, g)) return false;
    } else if (params.status === 'backlog') {
      if (hasPersonalEntry(personal, g) && p.status !== 'backlog') return false;
    } else if (p.status !== params.status) {
      return false;
    }
  }
  if (view === 'wishlist' && params.status) {
    if (params.status === '__none__') {
      if (hasPersonalEntry(personal, g)) return false;
    } else if (params.status === 'backlog') {
      if (hasPersonalEntry(personal, g) && p.status !== 'backlog') return false;
    } else if (p.status !== params.status) {
      return false;
    }
  }
  if (params.unplayed && rowPlaytime(ctx, g) > 0) return false;
  if (params.earlyAccess && !isEarlyAccess(g)) return false;
  if (params.gamePass && !isGamePass(g)) return false;
  if (params.staleOnly && !g.stale) return false;
  if (!passesCoopFilter(g, resolveCoopFilterMode(prefs))) return false;
  const rating = ratingValue(g);
  if (params.minRating > 0 && rating < params.minRating) return false;
  const h = hltbMain(personal, g);
  if (params.maxHours < 200 && h != null && h > params.maxHours) return false;
  if (prefs.hltbBucket != null && HLTB_BUCKETS_QUERY[prefs.hltbBucket]) {
    if (h == null) return false;
    const b = HLTB_BUCKETS_QUERY[prefs.hltbBucket];
    if (b.minExclusive != null && h <= b.minExclusive) return false;
    if (b.maxInclusive != null && h > b.maxInclusive) return false;
  }
  const genres = prefs.genreFilters || [];
  if (genres.length && !gameMatchesGenreFilters(g, genres, prefs.genreFilterMode)) return false;
  return true;
}

function sortCompare(ctx, a, b) {
  const { sortKey, sortDir, personal } = ctx;
  const pa = getPersonalRecord(personal, a);
  const pb = getPersonalRecord(personal, b);
  let va;
  let vb;
  switch (sortKey) {
    case 'status': va = pa.status; vb = pb.status; break;
    case 'priority_score': va = priorityScore(ctx, a); vb = priorityScore(ctx, b); break;
    case 'last_played': va = a.last_played || 0; vb = b.last_played || 0; break;
    case 'release_date': va = parseReleaseForSort(a.release_date); vb = parseReleaseForSort(b.release_date); break;
    case 'hltb_main_hours': va = hltbMain(personal, a); vb = hltbMain(personal, b); break;
    case 'discount_percent': va = effectiveDiscountPercent(ctx, a); vb = effectiveDiscountPercent(ctx, b); break;
    case 'deal_price': va = effectiveSortPrice(ctx, a); vb = effectiveSortPrice(ctx, b); break;
    case 'playtime_minutes': va = rowPlaytime(ctx, a); vb = rowPlaytime(ctx, b); break;
    default: va = a[sortKey]; vb = b[sortKey];
  }
  if (va == null) va = sortDir > 0 ? Infinity : -Infinity;
  if (vb == null) vb = sortDir > 0 ? Infinity : -Infinity;
  if (typeof va === 'string') return sortDir * va.localeCompare(vb);
  return sortDir * (va - vb);
}

export function buildQueryContext(state, params) {
  const itadMeta = state.libraryMeta?.itad;
  let displayCurrency = 'USD';
  if (itadMeta?.currency) {
    const c = String(itadMeta.currency).trim().toUpperCase();
    if (/^[A-Z]{3}$/.test(c)) displayCurrency = c;
  } else if (itadMeta?.country) {
    const cc = String(itadMeta.country).trim().toUpperCase();
    const map = { US: 'USD', GB: 'GBP', UK: 'GBP', CA: 'CAD', AU: 'AUD', DE: 'EUR', FR: 'EUR' };
    displayCurrency = map[cc] || 'USD';
  }
  return {
    view: state.activeView,
    displayCurrency,
    prefs: state.prefs,
    // Session-scoped prefs (itchHideNonGames, crossStoreDedup) — serialize across
    // to the worker so passesFilter() can read them on the off-main-thread path too.
    sessionPrefs: { ...(state.sessionPrefs || {}) },
    params,
    personal: state.personal,
    hiddenKeys: state.activeView === 'wishlist'
      ? state.wishlistCrossStoreHiddenKeys
      : state.crossStoreHiddenKeys,
    ownedNormNames: state.ownedNormNames,
    itadByKey: state.itadByKey,
    cleanupModeActive: state.cleanupModeActive,
    sortKey: state.sortKey,
    sortDir: state.sortDir,
    // Map<gameKey, totalMinutes> — only populated for cross-store dedup
    // representatives. Used by rowPlaytime() so the worker path stays
    // consistent with the main-thread display.
    combinedPlaytime: combinedPlaytimeLookup(state),
    playedTitleNorms: state.playedTitleNorms,
  };
}

function combinedPlaytimeLookup(state) {
  const src = state.crossStorePlaytimeByKey;
  if (!src || src.size === 0) return new Map();
  const out = new Map();
  for (const [key, entry] of src) out.set(key, entry.total);
  return out;
}

export function querySourceForView(state) {
  if (state.activeView === 'wishlist') return state.wishlistGames;
  if (state.activeView === 'itch') return state.itchGames;
  return state.allGames;
}

export function queryGames(payload) {
  const ctx = payload.ctx;
  const source = payload.source;
  const filtered = [];
  for (let i = 0; i < source.length; i++) {
    const g = source[i];
    if (passesFilter(ctx, g)) filtered.push(g);
  }
  filtered.sort((a, b) => sortCompare(ctx, a, b));
  return filtered;
}

function getWorker() {
  if (_worker) return _worker;
  try {
    _worker = new Worker(new URL('./table-query.worker.js', import.meta.url), { type: 'module' });
  } catch {
    _worker = null;
  }
  return _worker;
}

export function queryGamesAsync(state, params) {
  const source = querySourceForView(state);
  const baseCtx = buildQueryContext(state, params);
  const payload = {
    source,
    ctx: {
      ...baseCtx,
      hiddenKeys: [
        ...(state.activeView === 'wishlist'
          ? state.wishlistCrossStoreHiddenKeys
          : state.crossStoreHiddenKeys),
      ],
      ownedNormNames: [...state.ownedNormNames],
      // Maps don't survive structured clone for our worker bridge cleanly when
      // we treat the payload as opaque, so flatten to entries; the worker
      // rebuilds the Map on the other side.
      combinedPlaytime: [...baseCtx.combinedPlaytime],
      playedTitleNorms: [...state.playedTitleNorms],
    },
  };
  if (source.length < WORKER_THRESHOLD) {
    return Promise.resolve(queryGames({
      source,
      ctx: {
        ...payload.ctx,
        hiddenKeys: state.activeView === 'wishlist'
          ? state.wishlistCrossStoreHiddenKeys
          : state.crossStoreHiddenKeys,
        ownedNormNames: state.ownedNormNames,
        combinedPlaytime: baseCtx.combinedPlaytime,
      },
    }));
  }
  const worker = getWorker();
  if (!worker) {
    return Promise.resolve(queryGames({ source, ctx: buildQueryContext(state, params) }));
  }
  const id = ++_workerGen;
  return new Promise((resolve, reject) => {
    const onMessage = (ev) => {
      if (ev.data?.id !== id) return;
      worker.removeEventListener('message', onMessage);
      worker.removeEventListener('error', onError);
      const indices = ev.data.indices || [];
      resolve(indices.map(i => source[i]));
    };
    const onError = (err) => {
      worker.removeEventListener('message', onMessage);
      worker.removeEventListener('error', onError);
      reject(err);
    };
    worker.addEventListener('message', onMessage);
    worker.addEventListener('error', onError);
    worker.postMessage({ id, payload });
  });
}
