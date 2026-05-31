/**
 * Pure filter/sort for the library table (main thread + worker).
 */

import {
  CLEANUP_MAX_RATING,
  CLEANUP_MIN_AGE_MS,
  GENRE_ALIASES,
  ITCH_NON_GAME_CLASSIFICATIONS,
} from './state.js';

const NON_GENRE_TOKENS = new Set([
  'ps3', 'ps4', 'ps5', 'psp', 'ps vita', 'psvita', 'vita',
  'xbox', 'xbox 360', 'xbox one', 'xbox series x', 'xbox series s', 'xbox series x|s', 'xbox series x/s', 'xbox series',
  'nintendo switch', 'switch', 'wii', 'wii u', 'ds', '3ds', 'nintendo ds', 'nintendo 3ds',
  'pc', 'windows', 'mac', 'macos', 'osx', 'linux', 'steamos',
  'ios', 'android', 'browser', 'stadia', 'google stadia',
]);

const WORKER_THRESHOLD = 500;
let _worker = null;
let _workerGen = 0;

export function escapeAttr(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

export function collectTableParams() {
  return {
    q: (document.getElementById('search')?.value || '').trim().toLowerCase(),
    status: document.getElementById('statusFilter')?.value || '',
    unplayed: !!document.getElementById('unplayedOnly')?.checked,
    earlyAccess: !!document.getElementById('earlyAccessOnly')?.checked,
    coopOnline: !!document.getElementById('coopOnlineOnly')?.checked,
    coopLocal: !!document.getElementById('coopLocalOnly')?.checked,
    minRating: +(document.getElementById('minRating')?.value || 0),
    maxHours: +(document.getElementById('maxHours')?.value || 200),
  };
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

function gameStore(g) {
  return g.store || 'steam';
}

function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id
    ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
}

export function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}

function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  return { ...g, store: gameStore(g), id: gameId(g) };
}

function aliasCanonicalGenre(name) {
  return GENRE_ALIASES[name] || name;
}

function gameGenresCanonical(g) {
  return [...new Set((g.genres || []).filter(x => !NON_GENRE_TOKENS.has(String(x || '').trim().toLowerCase())).map(aliasCanonicalGenre))];
}

function gameMatchesGenreFilters(g, genres, genreMode) {
  const gameGenres = gameGenresCanonical(g);
  if (!genres.length) return true;
  if (genreMode === 'AND') return genres.every(x => gameGenres.includes(x));
  return genres.some(x => gameGenres.includes(x));
}

function normalizeNameForDedup(name) {
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
    return { status: 'backlog', notes: '', priority: 0, hltb_override: null, tags: [] };
  }
  return {
    status: found.status ?? 'backlog',
    notes: found.notes ?? '',
    priority: found.priority ?? 0,
    hltb_override: found.hltb_override ?? null,
    tags: Array.isArray(found.tags) ? found.tags : [],
  };
}

function hasPersonalEntry(personal, g) {
  const key = gameKey(g);
  return !!(personal[key] || (typeof personal[gameId(g)] === 'object' && personal[gameId(g)]));
}

function hltbMain(personal, g) {
  const p = getPersonalRecord(personal, g);
  if (p.hltb_override != null && p.hltb_override !== '') return +p.hltb_override;
  return g.hltb_main_hours;
}

function ratingValue(g) {
  return g.steam_review_percent ?? 0;
}

function parseReleaseForSort(d) {
  const t = Date.parse(d || '');
  return Number.isNaN(t) ? 0 : t;
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

function getDealInfo(itadByKey, g) {
  const itad = getItadForGame(itadByKey, g);
  if (itad && itad.price != null) {
    return {
      price: itad.price,
      cut: itad.cut || 0,
      isHistoricalLow: !!itad.is_historical_low,
    };
  }
  const steamPrice = parsePriceLike(g.price);
  const cut = g.discount_percent || 0;
  if (steamPrice != null || cut) {
    return { price: steamPrice, cut, isHistoricalLow: false };
  }
  return null;
}

function isOwnedByTitle(ownedNormNames, name) {
  const n = normalizeNameForDedup(name);
  return !!(n && ownedNormNames.has(n));
}

function passesDealFilters(ctx, g) {
  const { prefs, ownedNormNames, itadByKey } = ctx;
  if (prefs.dealHideOwned && isOwnedByTitle(ownedNormNames, g.name)) return false;
  const d = getDealInfo(itadByKey, g);
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

function isCleanupCandidate(ctx, g) {
  const p = getPersonalRecord(ctx.personal, g);
  if (p.status !== 'backlog') return false;
  if ((g.playtime_minutes || 0) > 0) return false;
  const rating = ratingValue(g);
  if (rating > 0 && rating >= CLEANUP_MAX_RATING) return false;
  const released = parseReleaseForSort(g.release_date);
  if (!released) return true;
  return Date.now() - released >= CLEANUP_MIN_AGE_MS;
}

function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === 'game') return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

function priorityScore(ctx, g) {
  const review = ratingValue(g);
  const h = hltbMain(ctx.personal, g) || 20;
  return review / Math.log2(h + 2);
}

function effectiveDiscountPercent(ctx, g) {
  const d = getDealInfo(ctx.itadByKey, g);
  if (d) return d.cut || 0;
  return g.discount_percent || 0;
}

function effectiveSortPrice(ctx, g) {
  const d = getDealInfo(ctx.itadByKey, g);
  if (d && d.price != null) return d.price;
  return parsePriceLike(g.price);
}

function passesFilter(ctx, g) {
  const { view, prefs, params, personal, hiddenKeys, ownedNormNames } = ctx;
  const ng = normalizeGame(g);
  const p = getPersonalRecord(personal, g);
  if (view === 'library') {
    if (prefs.storeFilter && ng.store !== prefs.storeFilter) return false;
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
  if (view === 'itch' && prefs.itchHideNonGames && !itchIsGame(g)) return false;
  if (ctx.cleanupModeActive && view === 'library' && !isCleanupCandidate(ctx, g)) return false;
  if (params.q && !g.name.toLowerCase().includes(params.q)) return false;
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
  if (params.unplayed && (g.playtime_minutes || 0) > 0) return false;
  if (params.earlyAccess && !isEarlyAccess(g)) return false;
  if (params.coopOnline && !g.coop_online) return false;
  if (params.coopLocal && !g.coop_local) return false;
  const rating = ratingValue(g);
  if (params.minRating > 0 && rating < params.minRating) return false;
  const h = hltbMain(personal, g);
  if (params.maxHours < 200 && h != null && h > params.maxHours) return false;
  const genres = prefs.genreFilters || [];
  if (genres.length && !gameMatchesGenreFilters(g, genres, prefs.genreFilterMode)) return false;
  const tagFilters = prefs.tagFilters || [];
  if (tagFilters.length) {
    const gameTags = p.tags || [];
    if (prefs.tagFilterMode === 'AND') {
      if (!tagFilters.every(t => gameTags.includes(t))) return false;
    } else if (!tagFilters.some(t => gameTags.includes(t))) {
      return false;
    }
  }
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
    default: va = a[sortKey]; vb = b[sortKey];
  }
  if (va == null) va = sortDir > 0 ? Infinity : -Infinity;
  if (vb == null) vb = sortDir > 0 ? Infinity : -Infinity;
  if (typeof va === 'string') return sortDir * va.localeCompare(vb);
  return sortDir * (va - vb);
}

export function buildQueryContext(state, params) {
  return {
    view: state.activeView,
    prefs: state.prefs,
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
  };
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
  const payload = {
    source,
    ctx: {
      ...buildQueryContext(state, params),
      hiddenKeys: [
        ...(state.activeView === 'wishlist'
          ? state.wishlistCrossStoreHiddenKeys
          : state.crossStoreHiddenKeys),
      ],
      ownedNormNames: [...state.ownedNormNames],
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
