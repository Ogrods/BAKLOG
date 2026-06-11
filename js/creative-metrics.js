// Creative dashboard insights & marquee chips (edgy / identity / money / time).
// Wired from dashboard-insights.js; weights passed in to avoid circular imports.

import { state } from './state.js';
import { escapeHtml, formatNum } from './dom-util.js';
import {
  gameKey,
  normalizeGame,
  normalizeNameForDedup,
  hltbMain,
  ratingValue,
  combinedPlaytime,
  firstPlayedAt,
  playSessionCount,
} from './game-core.js';
import { gameGenresCanonical } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo, dealScore } from './deals.js';
import { formatMoney, displayCurrency } from './currency.js';
import { hoardRate, oldestWishlist } from './sabermetrics.js';

const MS_PER_DAY = 86400000;
const PLAYFUL_BASE_AGE = 30;
const HOURS_PER_DAY_PACE = 2;
const WORK_WEEK_HRS = 40;

function statusOf(g) {
  return getPersonal(g).status || 'backlog';
}

function untouched(g) {
  return combinedPlaytime(g) === 0;
}

function parseReleaseYear(d) {
  if (!d) return null;
  const s = String(d);
  const m = s.match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
  if (m) return parseInt(m[1], 10);
  const t = Date.parse(s);
  if (!isNaN(t)) return new Date(t).getUTCFullYear();
  return null;
}

function formatDollar(n) {
  if (n == null || Number.isNaN(n)) return '-';
  return formatMoney(n, displayCurrency(), { maximumFractionDigits: 0, minimumFractionDigits: 0 });
}

function firstSeenAt(g) {
  const seen = state.libraryFirstSeenByKey || {};
  return seen[gameKey(g)] || 0;
}

function daysSince(ts) {
  if (!ts) return null;
  const n = typeof ts === 'number' ? ts : Date.parse(String(ts));
  if (!n || Number.isNaN(n)) return null;
  return Math.max(0, Math.floor((Date.now() - n) / MS_PER_DAY));
}

function finishesLast12Months(games) {
  const cutoff = Date.now() - 365 * MS_PER_DAY;
  return games.filter(g => {
    if (statusOf(g) !== 'finished') return false;
    const lp = g.last_played;
    if (!lp) return false;
    const t = Date.parse(String(lp));
    return !Number.isNaN(t) && t >= cutoff;
  }).length;
}

function addedThisYearCount(games) {
  const y = String(new Date().getFullYear());
  return games.filter(g => (g.added_at || '').startsWith(y)).length;
}

/** @param {object[]} games @param {object} snap */
export function computeCreativeMetrics(games, snap) {
  const list = games || [];
  const backlog = list.filter(g => statusOf(g) === 'backlog');
  const finished = list.filter(g => statusOf(g) === 'finished');
  const untouchedBacklog = backlog.filter(untouched);
  const now = Date.now();
  const thisYear = new Date().getFullYear();

  const out = {
    diagnosis: null,
    comfortGenre: null,
    blindSpot: null,
    halfLifePill: null,
    halfLifeChip: null,
    lifetime: null,
    shelfWarmer: null,
    shelfTime: null,
    timeCapsule: null,
    dollarsUnplayed: null,
    totalMsrp: null,
    pricedRows: null,
    avgMsrp: null,
    whale: null,
    cheapestThrill: null,
    freePile: null,
    addVelocity: null,
    monogamy: null,
    guiltyPleasure: null,
    tasteEra: null,
    oneHitDev: null,
    azGaps: null,
    workWeeksPill: null,
    workWeeksChip: null,
    patiencePays: null,
    gotAway: null,
    wishlistAge: null,
    psnTenureYears: null,
    sessionHeavy: null,
  };

  if (list.length < 5) return out;

  const hoard = hoardRate(snap);
  const addedYr = addedThisYearCount(list);
  const finishedYr = list.filter(g =>
    statusOf(g) === 'finished' && String(g.last_played || '').startsWith(String(thisYear)),
  ).length;
  const comp = snap.completionRate ?? 0;

  if (hoard != null) {
    let label = 'Balanced curator';
    if (hoard >= 0.65 && comp < 0.12) label = 'Chronic acquirer';
    else if (snap.backlogHrs >= 500 && comp < 0.2) label = 'Terminal collector';
    else if (finishedYr > addedYr && finishedYr >= 3) label = 'Recovering closer';
    else if (hoard >= 0.5 && addedYr > finishedYr * 2) label = 'Magpie mode';
    out.diagnosis = label;
  }

  const genreFinish = {};
  const genreUnplayed = {};
  for (const g of list) {
    const gens = gameGenresCanonical(g);
    const st = statusOf(g);
    for (const genre of gens) {
      if (!genre) continue;
      if (st === 'finished') genreFinish[genre] = (genreFinish[genre] || 0) + 1;
      if (st === 'backlog' && untouched(g)) {
        genreUnplayed[genre] = (genreUnplayed[genre] || 0) + 1;
      }
    }
  }
  const topFinishGenre = Object.entries(genreFinish).sort((a, b) => b[1] - a[1])[0];
  if (topFinishGenre) {
    out.comfortGenre = { genre: topFinishGenre[0], count: topFinishGenre[1] };
  }
  const topBlind = Object.entries(genreUnplayed).sort((a, b) => b[1] - a[1])[0];
  if (topBlind && topBlind[1] > 0) {
    out.blindSpot = { genre: topBlind[0], count: topBlind[1] };
  }

  const finPerYear = Math.max(finishesLast12Months(list), 0.5);
  if (snap.backlogHrs > 0) {
    const years = (snap.backlogHrs / finPerYear).toFixed(1);
    out.halfLifeChip = { years };
    out.halfLifePill = years;
  }

  if (snap.backlogHrs >= 10) {
    const yearsNeeded = snap.backlogHrs / (HOURS_PER_DAY_PACE * 365);
    const finishAge = PLAYFUL_BASE_AGE + Math.round(yearsNeeded);
    out.lifetime = finishAge;
  }

  let maxShelfDays = -1;
  let maxShelfGame = null;
  const shelfSpans = [];
  for (const g of list) {
    const at = firstSeenAt(g);
    if (!at) continue;
    const days = Math.floor((now - at) / MS_PER_DAY);
    if (untouched(g) && days > maxShelfDays) {
      maxShelfDays = days;
      maxShelfGame = g;
    }
    if (combinedPlaytime(g) > 0) {
      shelfSpans.push(days);
    }
  }
  if (maxShelfGame && maxShelfDays >= 0) {
    out.shelfWarmer = { name: maxShelfGame.name, days: maxShelfDays };
  }
  if (shelfSpans.length) {
    const avg = Math.round(shelfSpans.reduce((s, d) => s + d, 0) / shelfSpans.length);
    if (avg > 0) out.shelfTime = avg;
  }

  const capsuleCandidates = untouchedBacklog
    .map(g => ({ g, at: firstSeenAt(g) || (g.added_at ? Date.parse(g.added_at) : 0) }))
    .filter(x => x.at > 0)
    .sort((a, b) => a.at - b.at);
  if (capsuleCandidates[0]) {
    const y = new Date(capsuleCandidates[0].at).getFullYear();
    out.timeCapsule = { year: y, name: capsuleCandidates[0].g.name };
  }

  let msrpSum = 0;
  let whaleGame = null;
  let whalePrice = -1;
  let cheapGame = null;
  let cheapPrice = Infinity;
  let cheapRating = 0;
  let freeCount = 0;

  for (const g of untouchedBacklog) {
    const d = getDealInfo(g);
    const reg = d?.regular;
    if (reg != null && reg > 0) {
      msrpSum += reg;
      if (reg > whalePrice) {
        whalePrice = reg;
        whaleGame = g;
      }
      const r = ratingValue(g);
      if (r >= 75 && reg < cheapPrice) {
        cheapPrice = reg;
        cheapGame = g;
        cheapRating = r;
      }
    } else if (reg == null || reg === 0) {
      freeCount++;
    }
  }
  if (msrpSum > 0) out.dollarsUnplayed = msrpSum;

  // Total library MSRP — sum of every row's regular price (display currency),
  // counting only rows that actually have a comparable price. This iterates the
  // same deduped list the dashboard renders, so it stays accurate to the rows.
  let libraryMsrpSum = 0;
  let pricedRows = 0;
  for (const g of list) {
    const reg = getDealInfo(g)?.regular;
    if (reg != null && reg > 0) {
      libraryMsrpSum += reg;
      pricedRows++;
    }
  }
  if (libraryMsrpSum > 0) out.totalMsrp = libraryMsrpSum;
  if (pricedRows > 0) {
    out.pricedRows = pricedRows;
    out.avgMsrp = libraryMsrpSum / pricedRows;
  }

  if (whaleGame) out.whale = { name: whaleGame.name, price: whalePrice };
  if (cheapGame) out.cheapestThrill = { name: cheapGame.name, price: cheapPrice, rating: cheapRating };
  if (freeCount > 0) out.freePile = freeCount;

  const dated = list.map(g => g.added_at).filter(Boolean).sort();
  if (dated.length >= 2) {
    const first = Date.parse(dated[0]);
    const last = Date.parse(dated[dated.length - 1]);
    const months = Math.max(1, (last - first) / (MS_PER_DAY * 30.44));
    out.addVelocity = (list.filter(g => g.added_at).length / months).toFixed(1);
  } else if (dated.length === 1) {
    out.addVelocity = String(list.length);
  }

  const totalPlay = list.reduce((s, g) => s + combinedPlaytime(g), 0);
  if (totalPlay > 0) {
    const top = [...list].sort((a, b) => combinedPlaytime(b) - combinedPlaytime(a))[0];
    const pct = Math.round((combinedPlaytime(top) / totalPlay) * 100);
    if (pct >= 25) out.monogamy = { pct, name: top.name };
  }

  const ratedFinished = finished.filter(g => ratingValue(g) > 0);
  if (ratedFinished.length) {
    const guilty = [...ratedFinished].sort((a, b) => ratingValue(a) - ratingValue(b))[0];
    out.guiltyPleasure = { name: guilty.name, rating: ratingValue(guilty) };
  }

  const finYears = finished.map(g => parseReleaseYear(g.release_date)).filter(y => y != null);
  const backYears = backlog.map(g => parseReleaseYear(g.release_date)).filter(y => y != null);
  if (finYears.length && backYears.length) {
    const avgFin = Math.round(finYears.reduce((s, y) => s + y, 0) / finYears.length);
    const avgBack = Math.round(backYears.reduce((s, y) => s + y, 0) / backYears.length);
    out.tasteEra = { finished: avgFin, backlog: avgBack };
  }

  const devOwned = {};
  const devFinished = {};
  for (const g of list) {
    const ng = normalizeGame(g);
    const devs = ng.developers || g.developers || [];
    for (const d of devs) {
      if (!d) continue;
      devOwned[d] = (devOwned[d] || 0) + 1;
      if (statusOf(g) === 'finished') devFinished[d] = (devFinished[d] || 0) + 1;
    }
  }
  const oneHit = Object.entries(devOwned)
    .filter(([d, n]) => n >= 2 && !(devFinished[d] > 0))
    .sort((a, b) => b[1] - a[1])[0];
  if (oneHit) out.oneHitDev = { dev: oneHit[0], owned: oneHit[1] };

  const letters = new Set();
  for (const g of list) {
    const norm = normalizeNameForDedup(g.name) || String(g.name || '').trim();
    const ch = norm.charAt(0).toUpperCase();
    if (ch >= 'A' && ch <= 'Z') letters.add(ch);
  }
  const missing = [];
  for (let i = 65; i <= 90; i++) {
    const L = String.fromCharCode(i);
    if (!letters.has(L)) missing.push(L);
  }
  if (list.length > 0) out.azGaps = missing;

  if (snap.backlogHrs > 0) {
    const wks = Math.round(snap.backlogHrs / WORK_WEEK_HRS);
    out.workWeeksChip = wks;
    out.workWeeksPill = wks;
  }

  const wl = state.wishlistGames || [];
  const atLow = wl.filter(g => {
    const d = getDealInfo(g);
    return d && d.isHistoricalLow;
  });
  if (atLow.length) out.patiencePays = atLow.length;

  const onSaleWl = wl.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
  if (onSaleWl.length) {
    const top = [...onSaleWl].sort((a, b) => dealScore(b) - dealScore(a))[0];
    const cut = getDealInfo(top)?.cut || 0;
    out.gotAway = { name: top.name, cut };
  }

  const wlOldest = oldestWishlist(wl);
  if (wlOldest) {
    out.wishlistAge = { name: wlOldest.g.name, days: wlOldest.days };
  }

  if (snap.oldestFirstPlayedMs != null) {
    const yrs = ((now - snap.oldestFirstPlayedMs) / (365.25 * MS_PER_DAY)).toFixed(1);
    out.psnTenureYears = yrs;
  }

  const sessionHeavy = list
    .map(g => ({ g, n: playSessionCount(g), hrs: combinedPlaytime(g) / 60 }))
    .filter(x => x.n != null && x.n >= 10 && x.hrs > 0 && x.n / x.hrs >= 3)
    .sort((a, b) => (b.n / b.hrs) - (a.n / a.hrs))[0];
  if (sessionHeavy) {
    out.sessionHeavy = {
      name: sessionHeavy.g.name,
      sessions: sessionHeavy.n,
      hours: Math.round(sessionHeavy.hrs * 10) / 10,
    };
  }

  return out;
}

const SABER_SPOTLIGHT_SCORE = 92;

/**
 * Single-game creative superlatives for the dashboard spotlight (one game each).
 * @param {object[]} games — typically art-eligible library subset
 * @param {object} snap
 * @returns {{ key: string, eyebrow: string, score: number, metaParts: string[] }[]}
 */
export function computeSpotlightSuperlatives(games, snap) {
  const list = games || [];
  if (list.length < 2) return [];

  const backlog = list.filter(g => statusOf(g) === 'backlog');
  const untouchedBacklog = backlog.filter(untouched);
  const finished = list.filter(g => statusOf(g) === 'finished');
  const now = Date.now();
  const picks = [];

  const push = (g, eyebrow, score, metaParts) => {
    if (!g) return;
    picks.push({ key: gameKey(g), eyebrow, score, metaParts });
  };

  let whaleGame = null;
  let whalePrice = -1;
  for (const g of untouchedBacklog) {
    const reg = getDealInfo(g)?.regular;
    if (reg != null && reg > 0 && reg > whalePrice) {
      whalePrice = reg;
      whaleGame = g;
    }
  }
  if (whaleGame) {
    push(whaleGame, 'Whale', SABER_SPOTLIGHT_SCORE, [
      `<strong>${escapeHtml(formatDollar(whalePrice))}</strong> sunk`,
      'never launched',
    ]);
  }

  let maxShelfDays = -1;
  let maxShelfGame = null;
  for (const g of list) {
    const at = firstSeenAt(g);
    if (!at) continue;
    const days = Math.floor((now - at) / MS_PER_DAY);
    if (untouched(g) && days > maxShelfDays) {
      maxShelfDays = days;
      maxShelfGame = g;
    }
  }
  if (maxShelfGame && maxShelfDays >= 30) {
    const r = ratingValue(maxShelfGame);
    const parts = [`<strong>${formatNum(maxShelfDays)}</strong> days on shelf`];
    if (r > 0) parts.push(`<strong>${r}%</strong> review`);
    push(maxShelfGame, 'Gathering dust', r > 0 ? r + 11 : SABER_SPOTLIGHT_SCORE, parts);
  }

  const capsuleCandidates = untouchedBacklog
    .map(g => ({ g, at: firstSeenAt(g) || (g.added_at ? Date.parse(g.added_at) : 0) }))
    .filter(x => x.at > 0)
    .sort((a, b) => a.at - b.at);
  if (capsuleCandidates[0]) {
    const cap = capsuleCandidates[0];
    const y = new Date(cap.at).getFullYear();
    const capRating = ratingValue(cap.g);
    push(cap.g, 'Time capsule', capRating > 0 ? capRating + 9 : SABER_SPOTLIGHT_SCORE, [
      `since <strong>${y}</strong>`,
      'still sealed',
    ]);
  }

  let cheapGame = null;
  let cheapPrice = Infinity;
  let cheapRating = 0;
  for (const g of untouchedBacklog) {
    const reg = getDealInfo(g)?.regular;
    const r = ratingValue(g);
    if (reg != null && reg > 0 && r >= 75 && reg < cheapPrice) {
      cheapPrice = reg;
      cheapGame = g;
      cheapRating = r;
    }
  }
  if (cheapGame) {
    push(cheapGame, 'Cheap thrill', cheapRating + 10, [
      `<strong>${escapeHtml(formatDollar(cheapPrice))}</strong>`,
      `<strong>${cheapRating}%</strong> review`,
    ]);
  }

  const ratedFinished = finished.filter(g => ratingValue(g) > 0);
  if (ratedFinished.length) {
    const guilty = [...ratedFinished].sort((a, b) => ratingValue(a) - ratingValue(b))[0];
    const gr = ratingValue(guilty);
    // Only spotlight genuinely low-rated finishes (not Replay-worthy titles).
    if (gr > 0 && gr <= 75) {
      push(guilty, 'Guilty pleasure', gr + 5, [
        `<strong>${gr}%</strong> review`,
        'finished anyway',
      ]);
    }
  }

  const platinum = list
    .filter(g => g.trophy_progress != null && g.trophy_progress >= 100)
    .sort((a, b) => ratingValue(b) - ratingValue(a))[0];
  if (platinum) {
    const r = ratingValue(platinum);
    push(platinum, 'Completionist', r > 0 ? r + 8 : SABER_SPOTLIGHT_SCORE, [
      '<strong>100%</strong> complete',
      ...(r > 0 ? [`<strong>${r}%</strong> review`] : []),
    ]);
  }

  return picks;
}

/**
 * @param {{ html: string, weight: number }[]} entries
 * @param {object[]} games
 * @param {object} snap
 * @param {{ friendly?: number, moderate?: number, normal?: number }} W
 */
export function appendCreativeInsights(entries, games, snap, W = {}) {
  const friendly = W.friendly ?? 1;
  const moderate = W.moderate ?? 0.5;
  const m = computeCreativeMetrics(games, snap);
  const add = (html, weight = friendly) => entries.push({ html, weight });

  if (m.diagnosis) {
    add(`Backlog diagnosis: <strong>${escapeHtml(m.diagnosis)}</strong>`, moderate);
  }
  if (m.halfLifePill != null) {
    add(`~<strong>${escapeHtml(String(m.halfLifePill))}</strong> yrs to clear at your pace`, moderate);
  }
  if (m.lifetime != null) {
    add(`Finish backlog by age <strong>${m.lifetime}</strong>?`, moderate);
  }
  if (m.shelfWarmer) {
    add(`Shelf warmer: <strong>${escapeHtml(m.shelfWarmer.name)}</strong> · ${formatNum(m.shelfWarmer.days)}d`, moderate);
  }
  if (m.timeCapsule) {
    add(`Added <strong>${m.timeCapsule.year}</strong>, still untouched: <strong>${escapeHtml(m.timeCapsule.name)}</strong>`, moderate);
  }
  if (m.whale) {
    add(`Whale: <strong>${escapeHtml(m.whale.name)}</strong> · ${escapeHtml(formatDollar(m.whale.price))}`, moderate);
  }
  if (m.guiltyPleasure) {
    add(`Guilty pleasure: <strong>${escapeHtml(m.guiltyPleasure.name)}</strong> · ${m.guiltyPleasure.rating}%`, moderate);
  }
  if (m.oneHitDev) {
    add(`One-hit dev: <strong>${escapeHtml(m.oneHitDev.dev)}</strong> · ${formatNum(m.oneHitDev.owned)} owned, 0 finished`, moderate);
  }
  if (m.gotAway) {
    add(`One that got away: <strong>${escapeHtml(m.gotAway.name)}</strong> · -${m.gotAway.cut}%`, moderate);
  }
  if (m.workWeeksPill != null) {
    add(`Backlog = <strong>${formatNum(m.workWeeksPill)}</strong> work-weeks`, friendly);
  }
  if (m.psnTenureYears != null) {
    add(`PSN tenure: <strong>${escapeHtml(String(m.psnTenureYears))}</strong> yrs since first session`, moderate);
  }
  if (m.sessionHeavy) {
    add(`Session grinder: <strong>${escapeHtml(m.sessionHeavy.name)}</strong> · ${formatNum(m.sessionHeavy.sessions)} sessions / ${m.sessionHeavy.hours}h`, moderate);
  }
}

/**
 * @param {Function} push — marquee push(glyph, iconCls, value, label, valueHtml?, opts?)
 * @param {object[]} games
 * @param {object} snap
 * @param {{ friendly?: number, moderate?: number, normal?: number }} W
 */
export function appendCreativeMarqueeChips(push, games, snap, W = {}) {
  const friendly = W.friendly ?? 1;
  const normal = W.normal ?? 1;
  const m = computeCreativeMetrics(games, snap);

  if (m.comfortGenre) {
    push('*', 'is-emerald', `${m.comfortGenre.genre} · ${formatNum(m.comfortGenre.count)}`, 'comfort genre', null, { weight: friendly });
  }
  if (m.blindSpot) {
    push('^', 'is-rose', `${m.blindSpot.genre} · ${formatNum(m.blindSpot.count)}`, 'blind spot genre', null, { weight: friendly });
  }
  if (m.halfLifeChip) {
    push('~', 'is-amber', `${m.halfLifeChip.years} yrs`, 'to clear at your pace', null, { weight: friendly });
  }
  if (m.shelfTime != null) {
    push('~', 'is-amber', `${formatNum(m.shelfTime)}d`, 'avg shelf time', null, { weight: friendly });
  }
  if (m.dollarsUnplayed != null) {
    push('#', 'is-violet', formatDollar(m.dollarsUnplayed), 'MSRP sitting unplayed', null, { weight: friendly });
  }
  if (m.totalMsrp != null) {
    push('#', 'is-violet', formatDollar(m.totalMsrp), 'total MSRP value', null, { weight: friendly });
  }
  if (m.pricedRows != null) {
    push('#', 'is-violet', formatNum(m.pricedRows), 'priced library rows', null, { weight: friendly });
  }
  if (m.avgMsrp != null) {
    push('#', 'is-violet', formatDollar(m.avgMsrp), 'avg MSRP per game', null, { weight: friendly });
  }
  if (m.cheapestThrill) {
    push('>', '', `${m.cheapestThrill.name} · ${formatDollar(m.cheapestThrill.price)} · ${m.cheapestThrill.rating}%`, 'cheapest thrill', null, { weight: friendly });
  }
  if (m.freePile != null) {
    push('>', '', formatNum(m.freePile), 'free, never launched', null, { weight: friendly });
  }
  if (m.addVelocity != null) {
    push('+', 'is-emerald', `${m.addVelocity}/mo`, 'add velocity', null, { weight: friendly });
  }
  if (m.monogamy) {
    push('~', 'is-amber', `${m.monogamy.pct}%`, `playtime in ${m.monogamy.name}`, null, { weight: friendly });
  }
  if (m.tasteEra) {
    push('~', 'is-amber', `${m.tasteEra.finished} vs ${m.tasteEra.backlog}`, 'finished vs backlog era', null, { weight: normal });
  }
  if (m.azGaps && m.azGaps.length) {
    push('?', 'is-violet', m.azGaps.join(' '), 'missing A–Z letters', null, { weight: friendly });
  }
  if (m.workWeeksChip != null) {
    push('~', 'is-amber', `${formatNum(m.workWeeksChip)} wks`, 'backlog in work-weeks', null, { weight: friendly });
  }
  if (m.patiencePays != null) {
    push('+', 'is-emerald', formatNum(m.patiencePays), 'at historical low now', null, { weight: friendly });
  }
  if (m.wishlistAge) {
    push('*', 'is-violet', `${m.wishlistAge.name} · ${formatNum(m.wishlistAge.days)}d`, 'oldest wishlist', null, { weight: normal });
  }
  if (m.psnTenureYears != null) {
    push('~', 'is-amber', `${m.psnTenureYears} yrs`, 'PSN library tenure', null, { weight: friendly });
  }
  if (m.sessionHeavy) {
    push('*', 'is-violet', `${m.sessionHeavy.name} · ${formatNum(m.sessionHeavy.sessions)}`, 'session grinder', null, { weight: friendly });
  }
}
