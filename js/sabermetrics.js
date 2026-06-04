// Backlog sabermetrics — baseball-inspired library stats (WAR, OPS, BV+, park factors).
// Pure functions; snapshot built once per dashboard render and reused.

import { state } from './state.js';
import { gameKey, hltbMain, ratingValue, hasEnoughReviews, combinedPlaytime, normalizeGame } from './game-core.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo, computeWishlistWoba, isCleanupCandidate } from './deals.js';
import { gameGenresCanonical } from './genres.js';

export const MIN_REVIEW_COUNT = 50;

/** @typedef {'quick'|'short'|'long'|'epic'|'unknown'} LengthTier */

/** @typedef {{
 *   games: object[],
 *   total: number,
 *   finished: number,
 *   unfinished: number,
 *   touched: number,
 *   backlog: number,
 *   playing: number,
 *   next: number,
 *   backlogHrs: number,
 *   playedHrs: number,
 *   rBar: number,
 *   rRep: number,
 *   mendozaLine: number,
 * }} LibrarySnapshot */

export function lengthTier(g) {
  const h = hltbMain(g);
  if (h == null || h <= 0) return 'unknown';
  if (h <= 5) return 'quick';
  if (h <= 15) return 'short';
  if (h <= 40) return 'long';
  return 'epic';
}

export function lengthBases(tier) {
  switch (tier) {
    case 'quick': return 1;
    case 'short': return 2;
    case 'long': return 3;
    case 'epic': return 4;
    default: return 1;
  }
}

export function regressionWeight(g) {
  const n = g.steam_review_count || 0;
  if (n <= 0) return 0;
  return Math.min(1, n / MIN_REVIEW_COUNT);
}

export function luckAdjustedRating(g, rBar) {
  const raw = ratingValue(g);
  if (raw <= 0) return raw;
  const w = regressionWeight(g);
  return Math.round(raw * w + rBar * (1 - w));
}

function median(nums) {
  if (!nums.length) return 70;
  const s = [...nums].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

export function libraryMeanRating(games) {
  const rated = games.filter(g => ratingValue(g) > 0);
  if (!rated.length) return 70;
  return rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length;
}

export function replacementRating(games) {
  const backlogRated = games
    .filter(g => (getPersonal(g).status || 'backlog') === 'backlog')
    .map(g => ratingValue(g))
    .filter(r => r > 0);
  return median(backlogRated.length ? backlogRated : games.map(g => ratingValue(g)).filter(r => r > 0));
}

/** @param {object[]} games */
export function buildLibrarySnapshot(games) {
  const list = games || [];
  let finished = 0;
  let unfinished = 0;
  let touched = 0;
  let backlog = 0;
  let playing = 0;
  let next = 0;
  let skip = 0;
  let backlogHrs = 0;
  let playedHrs = 0;

  for (const g of list) {
    const st = getPersonal(g).status || 'backlog';
    if (st === 'finished') finished++;
    if (st === 'unfinished') unfinished++;
    if (st === 'skip') skip++;
    if (st === 'backlog') {
      backlog++;
      backlogHrs += hltbMain(g) || 0;
    }
    if (st === 'playing') playing++;
    if (st === 'next') next++;
    if (combinedPlaytime(g) > 0) touched++;
    playedHrs += combinedPlaytime(g) / 60;
  }

  const rBar = libraryMeanRating(list);
  const rRep = replacementRating(list);
  const nonSkip = list.length - skip;
  const completionRate = nonSkip ? finished / nonSkip : 0;

  return {
    games: list,
    total: list.length,
    finished,
    unfinished,
    touched,
    backlog,
    playing,
    next,
    skip,
    nonSkip,
    completionRate,
    backlogHrs,
    playedHrs,
    rBar,
    rRep,
    mendozaLine: rRep,
  };
}

let _snapCacheKey = '';
let _snapCache = null;

/** Cache key: data version + library length (invalidates on load/personal edits). */
export function librarySnapshotCacheKey(games) {
  const ver = typeof window !== 'undefined' ? (window._dataVersion || 0) : 0;
  return `${ver}:${(games || []).length}`;
}

/** Memoized snapshot for table paints and repeated dashboard passes. */
export function getLibrarySnapshot(games) {
  const list = games || [];
  const key = librarySnapshotCacheKey(list);
  if (_snapCacheKey === key && _snapCache) return _snapCache;
  const snap = buildLibrarySnapshot(list);
  _snapCacheKey = key;
  _snapCache = snap;
  return snap;
}

export function invalidateLibrarySnapshot() {
  _snapCacheKey = '';
  _snapCache = null;
}

export function completionAverage(snap) {
  const ab = snap.finished + snap.unfinished;
  if (!ab) return null;
  return snap.finished / ab;
}

export function startRate(snap) {
  if (!snap.total) return null;
  return snap.touched / snap.total;
}

export function abandonRate(snap) {
  if (!snap.touched) return null;
  return snap.unfinished / snap.touched;
}

export function sluggingPct(snap) {
  const ab = snap.finished + snap.unfinished;
  if (!ab) return null;
  let bases = 0;
  for (const g of snap.games) {
    if ((getPersonal(g).status || '') !== 'finished') continue;
    bases += lengthBases(lengthTier(g));
  }
  return bases / ab;
}

export function backlogObp(snap) {
  return startRate(snap);
}

export function backlogSlg(snap) {
  return sluggingPct(snap);
}

export function backlogOps(snap) {
  const obp = backlogObp(snap);
  const slg = backlogSlg(snap);
  if (obp == null || slg == null) return null;
  return obp + slg;
}

export function closerPower(snap) {
  const avg = completionAverage(snap);
  const slg = backlogSlg(snap);
  if (avg == null || slg == null) return null;
  return slg - avg;
}

export function pythagoreanCompletion(snap) {
  const played = snap.playedHrs;
  const remaining = snap.backlogHrs;
  const denom = played * played + remaining * remaining;
  if (denom <= 0) return null;
  const expected = (played * played) / denom;
  const actual = snap.completionRate ?? 0;
  return { expected, actual, delta: actual - expected };
}

export function isBarrel(g) {
  const r = ratingValue(g);
  const h = hltbMain(g);
  return r >= 85 && h != null && h > 0 && h <= 12;
}

export function barrelRate(snap) {
  if (!snap.total) return null;
  const barrels = snap.games.filter(isBarrel).length;
  return barrels / snap.total;
}

export function magicNumber(snap, goalPct = 0.5) {
  const nonSkip = snap.games.filter(g => (getPersonal(g).status || 'backlog') !== 'skip').length;
  if (!nonSkip) return null;
  const target = Math.ceil(nonSkip * goalPct);
  const need = Math.max(0, target - snap.finished);
  return need;
}

export function backlogPace(snap) {
  const hrs = snap.games
    .filter(g => (getPersonal(g).status || 'backlog') === 'backlog')
    .map(g => hltbMain(g))
    .filter(h => h != null && h > 0)
    .sort((a, b) => a - b);
  if (!hrs.length) return null;
  return hrs[Math.floor(hrs.length / 2)];
}

export function isLeveragePick(g) {
  const d = getDealInfo(g);
  const r = ratingValue(g);
  const h = hltbMain(g);
  if (!d || r < 80) return false;
  const onSale = (d.cut || 0) > 0 || d.isHistoricalLow;
  return onSale && h != null && h <= 15;
}

export function hoardRate(snap) {
  if (!snap.total) return null;
  const hoarded = snap.games.filter(g => combinedPlaytime(g) === 0).length;
  return hoarded / snap.total;
}

export function qualityStartRate(snap) {
  const played = snap.games.filter(g => combinedPlaytime(g) > 0);
  if (!played.length) return null;
  let qs = 0;
  for (const g of played) {
    const h = hltbMain(g);
    if (!h || h <= 0) continue;
    const mins = combinedPlaytime(g);
    if (mins >= h * 60 * 0.4) qs++;
  }
  return qs / played.length;
}

export function backlogWar(g, snap) {
  const r = ratingValue(g);
  const st = getPersonal(g).status || 'backlog';
  if (st === 'skip' || st === 'live' || st === 'finished') return null;
  let war = (r - snap.rRep) / 10;
  const tier = lengthTier(g);
  if (tier === 'long' || tier === 'epic') war += 0.3;
  if (tier === 'quick' && r >= 80) war += 0.15;
  const d = getDealInfo(g);
  if (d) {
    if ((d.cut || 0) >= 50) war += 0.25;
    if (d.isHistoricalLow) war += 0.2;
  }
  if (st === 'finished') war *= 0.35;
  if (st === 'unfinished') war *= 0.5;
  return Math.round(war * 10) / 10;
}

export function backlogValuePlus(g, snap) {
  const r = luckAdjustedRating(g, snap.rBar);
  if (r <= 0) return null;
  const h = hltbMain(g) || 20;
  const raw = (r / Math.log2(h + 2)) * 10;
  const league = snap.rBar / Math.log2(22);
  if (!league) return 100;
  return Math.round((raw / league) * 100);
}

export function wishlistWoba(g) {
  return computeWishlistWoba(g);
}

export function quickWinSpeedIndex(snap, maxHrs = 15) {
  const qw = snap.games.filter(g => {
    const st = getPersonal(g).status || 'backlog';
    if (st !== 'backlog') return false;
    const h = hltbMain(g);
    return ratingValue(g) >= 75 && h != null && h <= maxHrs;
  }).length;
  return qw;
}

export function cleanupCandidateCount(snap) {
  return snap.games.filter(g => isCleanupCandidate(g)).length;
}

export function powerSpeedNumber(snap) {
  const finished = snap.games.filter(g => (getPersonal(g).status || '') === 'finished');
  if (!finished.length) return null;
  let power = 0;
  let speed = 0;
  for (const g of finished) {
    const r = ratingValue(g);
    const tier = lengthTier(g);
    if (tier === 'long' || tier === 'epic') power++;
    if (tier === 'quick' && r >= 75) speed++;
  }
  if (!power || !speed) return null;
  return Math.round((2 * power * speed) / (power + speed) * 10) / 10;
}

export function trophyEfficiency(snap) {
  const tracked = snap.games.filter(g => g.trophy_progress != null);
  if (!tracked.length) return null;
  return Math.round(tracked.reduce((s, g) => s + g.trophy_progress, 0) / tracked.length);
}

export function gamerscoreEfficiency(snap) {
  const xbox = snap.games.filter(g => (g.xbox_gamerscore_total || 0) > 0);
  if (!xbox.length) return null;
  const cur = xbox.reduce((s, g) => s + (g.xbox_gamerscore_current || 0), 0);
  const tot = xbox.reduce((s, g) => s + (g.xbox_gamerscore_total || 0), 0);
  return tot ? Math.round((cur / tot) * 100) : null;
}

export function hotColdStreak(snap) {
  const finished = snap.games
    .filter(g => (getPersonal(g).status || '') === 'finished' && g.last_played)
    .sort((a, b) => String(b.last_played).localeCompare(String(a.last_played)));
  if (!finished.length) return 'cold';
  if (finished.length < 2) return 'warm';
  const latest = finished[0].last_played;
  const t = Date.parse(String(latest));
  if (Number.isFinite(t) && (Date.now() - t) > 90 * 86400000) return 'cold';
  return finished.length >= 3 ? 'hot' : 'warm';
}

export function genrePlusMap(snap) {
  const counts = {};
  const sums = {};
  for (const g of snap.games) {
    const r = ratingValue(g);
    if (r <= 0) continue;
    for (const genre of gameGenresCanonical(g)) {
      if (!genre) continue;
      counts[genre] = (counts[genre] || 0) + 1;
      sums[genre] = (sums[genre] || 0) + r;
    }
  }
  const out = {};
  for (const [genre, n] of Object.entries(counts)) {
    if (n < 2) continue;
    const avg = sums[genre] / n;
    out[genre] = Math.round((avg / snap.rBar) * 100);
  }
  return out;
}

export function storePlusMap(snap) {
  const counts = {};
  const sums = {};
  for (const g of snap.games) {
    const r = ratingValue(g);
    if (r <= 0) continue;
    const store = normalizeGame(g).store;
    counts[store] = (counts[store] || 0) + 1;
    sums[store] = (sums[store] || 0) + r;
  }
  const out = {};
  for (const [store, n] of Object.entries(counts)) {
    if (n < 2) continue;
    out[store] = Math.round((sums[store] / n / snap.rBar) * 100);
  }
  return out;
}

export function agingCurveBuckets(snap) {
  const seen = state.libraryFirstSeenByKey || {};
  const now = Date.now();
  const buckets = [
    { label: '<30d', maxMs: 30 * 86400000, finish: 0, total: 0 },
    { label: '30–90d', maxMs: 90 * 86400000, finish: 0, total: 0 },
    { label: '90d–1y', maxMs: 365 * 86400000, finish: 0, total: 0 },
    { label: '1y+', maxMs: Infinity, finish: 0, total: 0 },
  ];
  for (const g of snap.games) {
    const at = seen[gameKey(g)] || 0;
    if (!at) continue;
    const age = now - at;
    const st = getPersonal(g).status || 'backlog';
    let b = buckets[3];
    if (age < buckets[0].maxMs) b = buckets[0];
    else if (age < buckets[1].maxMs) b = buckets[1];
    else if (age < buckets[2].maxMs) b = buckets[2];
    b.total++;
    if (st === 'finished') b.finish++;
  }
  return buckets.map(b => ({
    label: b.label,
    finishRate: b.total ? Math.round((b.finish / b.total) * 100) : 0,
    total: b.total,
  }));
}

export function winSharesByGenre(snap) {
  const shares = {};
  for (const g of snap.games) {
    if ((getPersonal(g).status || '') !== 'finished') continue;
    for (const genre of gameGenresCanonical(g)) {
      if (!genre) continue;
      shares[genre] = (shares[genre] || 0) + 1;
    }
  }
  return Object.entries(shares).sort((a, b) => b[1] - a[1]).slice(0, 8);
}

export function topWarGame(snap) {
  let best = null;
  let bestWar = -Infinity;
  for (const g of snap.games) {
    const w = backlogWar(g, snap);
    if (w == null || w <= bestWar) continue;
    const st = getPersonal(g).status || 'backlog';
    if (!['backlog', 'next', 'playing'].includes(st)) continue;
    bestWar = w;
    best = g;
  }
  return best ? { g: best, war: bestWar } : null;
}

export function formatRate(pct, digits = 3) {
  if (pct == null || Number.isNaN(pct)) return '—';
  return pct.toFixed(digits).replace(/^0\./, '.');
}

export function formatPct100(pct, digits = 0) {
  if (pct == null || Number.isNaN(pct)) return '—';
  return `${(pct * 100).toFixed(digits)}%`;
}
