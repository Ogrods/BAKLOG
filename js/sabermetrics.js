// Backlog sabermetrics — baseball-inspired library stats (WAR, OPS, BV+, park factors).
// Pure functions; snapshot built once per dashboard render and reused.

import { state } from './state.js';
import { gameKey, hltbMain, ratingValue, hasEnoughReviews, combinedPlaytime, normalizeGame, firstPlayedAt, playSessionCount } from './game-core.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo, computeWishlistWoba, isCleanupCandidate, parsePriceLike } from './deals.js';

const MS_PER_DAY = 86400000;
const LIFE_EXPECTANCY_YRS = 80;
const PLAYFUL_BASE_AGE = 30;
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
  let psnSessionTotal = 0;
  let oldestFirstPlayedMs = null;

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
    const sessions = playSessionCount(g);
    if (sessions != null) psnSessionTotal += sessions;
    const fp = firstPlayedAt(g);
    if (fp != null && (oldestFirstPlayedMs == null || fp < oldestFirstPlayedMs)) {
      oldestFirstPlayedMs = fp;
    }
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
    psnSessionTotal,
    oldestFirstPlayedMs,
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
  if (st === 'unfinished') war *= 0.5;
  return Math.round(war * 10) / 10;
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
  if (pct == null || Number.isNaN(pct)) return '-';
  return pct.toFixed(digits).replace(/^0\./, '.');
}

export function formatPct100(pct, digits = 0) {
  if (pct == null || Number.isNaN(pct)) return '-';
  return `${(pct * 100).toFixed(digits)}%`;
}

/** @param {object} g */
export function metacriticScore(g) {
  const n = Number(g?.metacritic_score);
  return Number.isFinite(n) && n > 0 ? n : null;
}

/** Player % minus Metacritic; positive = crowd rates higher than critics. */
export function criticPlayerGap(g) {
  const mc = metacriticScore(g);
  const steam = ratingValue(g);
  if (mc == null || steam <= 0) return null;
  return steam - mc;
}

/** Mean |Metacritic − Steam%| across games with both scores. */
export function avgCriticGap(games) {
  const gaps = (games || []).map(criticPlayerGap).filter(g => g != null);
  if (!gaps.length) return null;
  return Math.round(gaps.reduce((s, g) => s + Math.abs(g), 0) / gaps.length);
}

/** Biggest positive critic gap (players > critics). */
export function peoplesChamp(games) {
  let best = null;
  let bestGap = -Infinity;
  for (const g of games || []) {
    const gap = criticPlayerGap(g);
    if (gap == null || gap <= 0 || gap <= bestGap) continue;
    bestGap = gap;
    best = g;
  }
  return best ? { g: best, gap: bestGap } : null;
}

/** Highest Metacritic owned title still unplayed. */
export function criticsDarling(games) {
  let best = null;
  let bestMc = -Infinity;
  for (const g of games || []) {
    const mc = metacriticScore(g);
    if (mc == null || combinedPlaytime(g) > 0 || mc <= bestMc) continue;
    bestMc = mc;
    best = g;
  }
  return best ? { g: best, score: bestMc } : null;
}

/** Biggest negative critic gap (critics > players). */
export function overratedLeader(games) {
  let worst = null;
  let worstGap = Infinity;
  for (const g of games || []) {
    const gap = criticPlayerGap(g);
    if (gap == null || gap >= 0 || gap >= worstGap) continue;
    worstGap = gap;
    worst = g;
  }
  return worst ? { g: worst, gap: worstGap } : null;
}

export function perpetualBetaCount(snap) {
  const n = snap.games.filter(g => g.early_access === true).length;
  return n > 0 ? n : null;
}

export function couchReadyRate(snap) {
  if (!snap.total) return null;
  const ready = snap.games.filter(g => {
    const c = g.controller_support;
    return c === 'full' || c === true;
  }).length;
  return ready > 0 ? ready / snap.total : null;
}

/** Avg days from acquired_at to first_played (PSN/catalog). */
export function acquireToPlayDaysAvg(snap) {
  const spans = [];
  for (const g of snap.games) {
    const acqRaw = g.acquired_at;
    if (!acqRaw) continue;
    const acq = Date.parse(String(acqRaw));
    const fp = firstPlayedAt(g);
    if (!Number.isFinite(acq) || fp == null || fp < acq) continue;
    spans.push((fp - acq) / MS_PER_DAY);
  }
  if (!spans.length) return null;
  return Math.round(spans.reduce((s, d) => s + d, 0) / spans.length);
}

export function dayOnePlayerCount(snap) {
  let count = 0;
  for (const g of snap.games) {
    const acqRaw = g.acquired_at;
    if (!acqRaw) continue;
    const acq = Date.parse(String(acqRaw));
    const fp = firstPlayedAt(g);
    if (!Number.isFinite(acq) || fp == null) continue;
    if (fp - acq <= MS_PER_DAY) count++;
  }
  return count > 0 ? count : null;
}

/** Mean completionist − main HLTB gap (extra content beyond main story). */
export function extraInningsAvg(snap) {
  const gaps = [];
  for (const g of snap.games) {
    const main = hltbMain(g);
    const comp = g.hltb_completionist_hours;
    if (main == null || main <= 0 || comp == null || comp <= main) continue;
    gaps.push(comp - main);
  }
  if (!gaps.length) return null;
  return Math.round((gaps.reduce((s, h) => s + h, 0) / gaps.length) * 10) / 10;
}

export function gamePassCount(snap) {
  const n = snap.games.filter(g => g.game_pass === true).length;
  return n > 0 ? n : null;
}

/** Games owned on 2+ stores (cross-store dedup map). */
export function doubleDipCount() {
  const map = state.crossStoreOwnedStores;
  if (!map?.size) return null;
  let count = 0;
  for (const stores of map.values()) {
    if (stores.length >= 2) count++;
  }
  return count > 0 ? count : null;
}

/** Total priced MSRP ÷ finished games. */
export function costPerFinish(snap) {
  if (!snap.finished) return null;
  let msrp = 0;
  for (const g of snap.games) {
    const reg = getDealInfo(g)?.regular;
    if (reg != null && reg > 0) msrp += reg;
  }
  return msrp > 0 ? Math.round(msrp / snap.finished) : null;
}

/** MSRP sum for owned games with zero playtime. */
export function sunkCostUnplayed(snap) {
  let sum = 0;
  for (const g of snap.games) {
    if (combinedPlaytime(g) > 0) continue;
    const reg = getDealInfo(g)?.regular;
    if (reg != null && reg > 0) sum += reg;
  }
  return sum > 0 ? Math.round(sum) : null;
}

/**
 * Backlog clear-by age at 2h/day vs life expectancy.
 * @returns {{ finishByAge: number, verdict: 'backlog'|'you' } | null}
 */
export function backlogMortality(snap) {
  if (!snap.backlogHrs || snap.backlogHrs <= 0) return null;
  const yearsNeeded = snap.backlogHrs / (2 * 365);
  const finishByAge = PLAYFUL_BASE_AGE + Math.round(yearsNeeded);
  return {
    finishByAge,
    verdict: finishByAge >= LIFE_EXPECTANCY_YRS ? 'backlog' : 'you',
  };
}

/** ProtonDB tier rank (higher = better Deck/Linux compatibility). */
const PROTON_TIER_RANK = {
  native: 6,
  platinum: 5,
  gold: 4,
  silver: 3,
  bronze: 2,
  borked: 0,
  pending: -1,
};

function protonTierRank(tier) {
  if (!tier) return null;
  const key = String(tier).toLowerCase();
  return Object.prototype.hasOwnProperty.call(PROTON_TIER_RANK, key) ? PROTON_TIER_RANK[key] : null;
}

function gamesWithProtonTier(games) {
  return (games || []).filter(g => protonTierRank(g.protondb_tier) != null && g.protondb_tier !== 'pending');
}

/** Share of ProtonDB-rated games that are platinum or gold (Deck-ready). */
export function protonReadyShare(games) {
  const rated = gamesWithProtonTier(games);
  if (!rated.length) return null;
  const ready = rated.filter(g => {
    const t = String(g.protondb_tier).toLowerCase();
    return t === 'platinum' || t === 'gold';
  }).length;
  return ready / rated.length;
}

/** Count games with a given ProtonDB tier. */
export function protonCount(games, tier) {
  const want = String(tier).toLowerCase();
  const n = (games || []).filter(g => String(g.protondb_tier || '').toLowerCase() === want).length;
  return n > 0 ? n : null;
}

/** Games whose recent ProtonDB trending tier ranks above their overall tier. */
export function protonTrendingUp(games) {
  let n = 0;
  for (const g of games || []) {
    const cur = protonTierRank(g.protondb_tier);
    const trend = protonTierRank(g.protondb_trending_tier);
    if (cur == null || trend == null || trend <= cur) continue;
    n++;
  }
  return n > 0 ? n : null;
}

/** Backlog games with ProtonDB platinum or gold tier. */
export function protonDeckReadyBacklog(games, statusOf) {
  const isBacklog = statusOf || (g => (getPersonal(g).status || 'backlog') === 'backlog');
  const n = (games || []).filter(g => {
    if (!isBacklog(g)) return false;
    const t = String(g.protondb_tier || '').toLowerCase();
    return t === 'platinum' || t === 'gold';
  }).length;
  return n > 0 ? n : null;
}

export function psnPlatinumsEarned(games) {
  const n = (games || []).filter(g => g.psn_platinum_earned === true).length;
  return n > 0 ? n : null;
}

export function psnPlatinumHunt(games) {
  const n = (games || []).filter(g => g.psn_has_platinum === true && g.psn_platinum_earned !== true).length;
  return n > 0 ? n : null;
}

export function psnTrophiesEarned(games) {
  let sum = 0;
  let any = false;
  for (const g of games || []) {
    const n = Number(g.psn_trophies_earned);
    if (!Number.isFinite(n) || n < 0) continue;
    any = true;
    sum += n;
  }
  return any && sum > 0 ? sum : null;
}

function psnRows(games) {
  return (games || []).filter(g => normalizeGame(g).store === 'psn');
}

/** Share of PSN library with PS5 in psn_platforms. */
export function ps5NativeShare(games) {
  const psn = psnRows(games).filter(g => (g.psn_platforms || []).length);
  if (!psn.length) return null;
  const ps5 = psn.filter(g => (g.psn_platforms || []).some(p => String(p).toUpperCase().includes('PS5'))).length;
  return ps5 > 0 ? ps5 / psn.length : null;
}

export function ps4Holdouts(games) {
  const n = psnRows(games).filter(g => {
    const plats = (g.psn_platforms || []).map(p => String(p).toUpperCase());
    return plats.some(p => p.includes('PS4')) && !plats.some(p => p.includes('PS5'));
  }).length;
  return n > 0 ? n : null;
}

/** Most frequent Steam community tag across the library. */
export function topTag(games) {
  const counts = new Map();
  for (const g of games || []) {
    for (const tag of g.tags || []) {
      const t = String(tag).trim();
      if (!t) continue;
      counts.set(t, (counts.get(t) || 0) + 1);
    }
  }
  if (!counts.size) return null;
  let best = null;
  let bestN = 0;
  for (const [tag, n] of counts) {
    if (n > bestN) {
      bestN = n;
      best = tag;
    }
  }
  return best ? { tag: best, count: bestN } : null;
}

const MULTIPLAYER_TAG = /multi.?player|co-?op|pvp|online/i;
const SINGLEPLAYER_TAG = /single.?player/i;

function hasTagMatching(g, pattern) {
  return (g.tags || []).some(t => pattern.test(String(t)));
}

/** Share of library tagged multiplayer/co-op/PvP/online. */
export function multiplayerTagShare(games) {
  const list = games || [];
  if (!list.length) return null;
  const tagged = list.filter(g => (g.tags || []).length);
  if (!tagged.length) return null;
  const mp = tagged.filter(g => hasTagMatching(g, MULTIPLAYER_TAG)).length;
  return mp > 0 ? mp / tagged.length : null;
}

/** Backlog games tagged single-player. */
export function singleplayerBacklogCount(games, statusOf) {
  const isBacklog = statusOf || (g => (getPersonal(g).status || 'backlog') === 'backlog');
  const n = (games || []).filter(g => isBacklog(g) && hasTagMatching(g, SINGLEPLAYER_TAG)).length;
  return n > 0 ? n : null;
}

export function freeItchCount(games) {
  const n = (games || []).filter(g => normalizeGame(g).store === 'itch' && Number(g.min_price) === 0).length;
  return n > 0 ? n : null;
}

export function itchSpendTotal(games) {
  let sum = 0;
  for (const g of games || []) {
    if (normalizeGame(g).store !== 'itch') continue;
    const p = Number(g.min_price);
    if (!Number.isFinite(p) || p <= 0) continue;
    sum += p;
  }
  return sum > 0 ? Math.round(sum * 100) / 100 : null;
}

export function installedLocalCount(games) {
  const n = (games || []).filter(g => String(g.source || '').toLowerCase() === 'local').length;
  return n > 0 ? n : null;
}

export function recentlyPlayedCount(games, days = 30) {
  const cutoff = Date.now() - days * MS_PER_DAY;
  let n = 0;
  for (const g of games || []) {
    const lp = g.last_played;
    if (!lp) continue;
    const t = Date.parse(String(lp));
    if (Number.isFinite(t) && t >= cutoff) n++;
  }
  return n > 0 ? n : null;
}

/** Played game with the oldest last_played timestamp. */
export function longestDormant(games) {
  let best = null;
  let oldest = Infinity;
  for (const g of games || []) {
    if (combinedPlaytime(g) <= 0) continue;
    const lp = g.last_played;
    if (!lp) continue;
    const t = Date.parse(String(lp));
    if (!Number.isFinite(t) || t >= oldest) continue;
    oldest = t;
    best = g;
  }
  return best ? { g: best, lastPlayed: best.last_played } : null;
}

export function avgMetacritic(games) {
  const scores = (games || []).map(metacriticScore).filter(s => s != null);
  if (!scores.length) return null;
  return Math.round(scores.reduce((s, n) => s + n, 0) / scores.length);
}

export function metacriticClubCount(games, minScore = 90) {
  const n = (games || []).filter(g => {
    const s = metacriticScore(g);
    return s != null && s >= minScore;
  }).length;
  return n > 0 ? n : null;
}

function wishlistAddedMs(g) {
  const wa = g.wishlist_added;
  if (wa != null && wa !== '') {
    const n = Number(wa);
    if (Number.isFinite(n) && n > 0) return n < 1e12 ? n * 1000 : n;
    const t = Date.parse(String(wa));
    if (Number.isFinite(t)) return t;
  }
  const aa = g.added_at;
  if (aa) {
    const t = Date.parse(String(aa));
    if (Number.isFinite(t)) return t;
  }
  return null;
}

/** Wishlist item waiting longest (by wishlist_added or added_at). */
export function oldestWishlist(wishlist) {
  const dated = (wishlist || [])
    .map(g => ({ g, t: wishlistAddedMs(g) }))
    .filter(x => x.t != null)
    .sort((a, b) => a.t - b.t);
  if (!dated[0]) return null;
  const days = Math.round((Date.now() - dated[0].t) / MS_PER_DAY);
  return { g: dated[0].g, days };
}

export function upcomingWishlistCount(wishlist) {
  const n = (wishlist || []).filter(g => g.release_coming_soon === true).length;
  return n > 0 ? n : null;
}

/** Share of ProtonDB-rated games that are silver or native tier. */
export function protonSilverNativeShare(games) {
  const rated = gamesWithProtonTier(games);
  if (!rated.length) return null;
  const n = rated.filter(g => {
    const t = String(g.protondb_tier).toLowerCase();
    return t === 'silver' || t === 'native';
  }).length;
  return n > 0 ? n / rated.length : null;
}

export function protonLowConfidenceCount(games) {
  const n = (games || []).filter(g => {
    const tier = g.protondb_tier;
    if (!tier || tier === 'pending') return false;
    return String(g.protondb_confidence || '').toLowerCase() === 'inadequate';
  }).length;
  return n > 0 ? n : null;
}

export function avgProtonScore(games) {
  const scores = (games || [])
    .map(g => Number(g.protondb_score))
    .filter(n => Number.isFinite(n) && n > 0);
  if (!scores.length) return null;
  return Math.round((scores.reduce((s, n) => s + n, 0) / scores.length) * 100) / 100;
}

function ownedSteamPrice(g) {
  if (normalizeGame(g).store !== 'steam') return null;
  if (g.price_amount != null && Number.isFinite(Number(g.price_amount))) {
    return Number(g.price_amount);
  }
  return parsePriceLike(g.price);
}

export function boughtOnSaleCount(games) {
  const n = (games || []).filter(g => {
    if (normalizeGame(g).store !== 'steam') return false;
    const d = Number(g.discount_percent);
    return Number.isFinite(d) && d > 0;
  }).length;
  return n > 0 ? n : null;
}

export function paidItchCount(games) {
  const n = (games || []).filter(g => {
    if (normalizeGame(g).store !== 'itch') return false;
    const p = Number(g.min_price);
    return Number.isFinite(p) && p > 0;
  }).length;
  return n > 0 ? n : null;
}

export function avgOwnedSteamPrice(games) {
  const prices = (games || []).map(ownedSteamPrice).filter(p => p != null && p > 0);
  if (!prices.length) return null;
  return Math.round((prices.reduce((s, p) => s + p, 0) / prices.length) * 100) / 100;
}

export function priorityWishlistCount(wishlist) {
  const n = (wishlist || []).filter(g => Number(g.wishlist_priority) > 0).length;
  return n > 0 ? n : null;
}

export function wishlistAddedThisYear(wishlist) {
  const year = new Date().getFullYear();
  const start = Date.UTC(year, 0, 1);
  const n = (wishlist || []).filter(g => {
    const t = wishlistAddedMs(g);
    return t != null && t >= start;
  }).length;
  return n > 0 ? n : null;
}

export function wishlistStoreCount(wishlist) {
  const stores = new Set();
  for (const g of wishlist || []) {
    const s = g.wishlist_store || g.store_target;
    if (s) stores.add(String(s));
  }
  return stores.size > 0 ? stores.size : null;
}

export function lastSeenThisWeek(games, days = 7) {
  const cutoff = Date.now() - days * MS_PER_DAY;
  let n = 0;
  for (const g of games || []) {
    const ls = g.last_seen;
    if (!ls) continue;
    const t = Date.parse(String(ls));
    if (Number.isFinite(t) && t >= cutoff) n++;
  }
  return n > 0 ? n : null;
}

export function launcherInstallCount(games) {
  const n = (games || []).filter(g => String(g.source || '').toLowerCase() === 'launcher').length;
  return n > 0 ? n : null;
}

export function hltbLowConfidenceCount(games) {
  const n = (games || []).filter(g => {
    if (hltbMain(g) == null) return false;
    const c = Number(g.hltb_match_confidence);
    return Number.isFinite(c) && c < 1;
  }).length;
  return n > 0 ? n : null;
}

const COOP_TAG_RE = /co-?op|multi.?player|multiplayer/i;

function hasCoopTag(g) {
  return (g.tags || []).some(t => COOP_TAG_RE.test(String(t)));
}

export function coopTaggedOnlyCount(games) {
  const n = (games || []).filter(g => {
    if (!hasCoopTag(g)) return false;
    return !g.coop_online && !g.coop_local;
  }).length;
  return n > 0 ? n : null;
}

export function partialControllerCount(games) {
  const n = (games || []).filter(g => String(g.controller_support || '').toLowerCase() === 'partial').length;
  return n > 0 ? n : null;
}

export function indieTaggedShare(games) {
  const tagged = (games || []).filter(g => (g.tags || []).length);
  if (!tagged.length) return null;
  const indie = tagged.filter(g =>
    (g.tags || []).some(t => /^indie$/i.test(String(t).trim())),
  ).length;
  return indie > 0 ? indie / tagged.length : null;
}

export function avgTrophyCompletion(games) {
  const rows = psnRows(games).filter(g => {
    const earned = Number(g.psn_trophies_earned);
    const total = Number(g.psn_trophies_total);
    return Number.isFinite(earned) && Number.isFinite(total) && total > 0;
  });
  if (!rows.length) return null;
  const avg = rows.reduce((s, g) => s + g.psn_trophies_earned / g.psn_trophies_total, 0) / rows.length;
  return avg;
}

export function gamerscoreCompletionShare(games) {
  let earned = 0;
  let total = 0;
  for (const g of games || []) {
    if (normalizeGame(g).store !== 'xbox') continue;
    const tot = Number(g.xbox_gamerscore_total);
    if (!Number.isFinite(tot) || tot <= 0) continue;
    const cur = Number(g.xbox_gamerscore_current);
    earned += Number.isFinite(cur) && cur >= 0 ? cur : 0;
    total += tot;
  }
  return total > 0 ? earned / total : null;
}

export function metacritic80UnplayedCount(games) {
  const n = (games || []).filter(g => {
    const mc = metacriticScore(g);
    return mc != null && mc >= 80 && combinedPlaytime(g) <= 0;
  }).length;
  return n > 0 ? n : null;
}

/** Owned title with the largest |Steam% − Metacritic| gap. */
export function biggestCriticGapGame(games) {
  let best = null;
  let bestGap = -1;
  for (const g of games || []) {
    const gap = criticPlayerGap(g);
    if (gap == null) continue;
    const abs = Math.abs(gap);
    if (abs <= bestGap) continue;
    bestGap = abs;
    best = { g, gap: abs };
  }
  return best;
}

export function earlyAccessBacklogCount(games, statusOf) {
  const isBacklog = statusOf || (g => (getPersonal(g).status || 'backlog') === 'backlog');
  const n = (games || []).filter(g => g.early_access === true && isBacklog(g)).length;
  return n > 0 ? n : null;
}

export function doubleDipBacklogCount(games, statusOf) {
  const map = state.crossStoreOwnedStores;
  if (!map?.size) return null;
  const isBacklog = statusOf || (g => (getPersonal(g).status || 'backlog') === 'backlog');
  let n = 0;
  for (const g of games || []) {
    if (!isBacklog(g)) continue;
    const stores = map.get(gameKey(g));
    if (stores && stores.length >= 2) n++;
  }
  return n > 0 ? n : null;
}

/** Share of A–Z title initials present in the library (26 = full alphabet). */
export function letterCoverageShare(games) {
  const list = games || [];
  if (!list.length) return null;
  const letters = new Set();
  for (const g of list) {
    const ch = String(g.name || '').trim().charAt(0).toUpperCase();
    if (ch >= 'A' && ch <= 'Z') letters.add(ch);
  }
  return letters.size > 0 ? letters.size / 26 : null;
}
