// Dashboard insight ticker / marquee (rotating stat lines + sticky marquee items).
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { gameKey, normalizeGame, hltbMain, ratingValue, hasEnoughReviews, itchIsGame, combinedPlaytime, firstPlayedAt, firstPlayedYear, playSessionCount } from './game-core.js';
import { gameGenresCanonical } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo, dealScore, isStealDeal, cutBucketClass } from './deals.js';
import { formatMoney, displayCurrency } from './currency.js';
import { registerPausable } from './visibility.js';
export { applyMarqueeSpeed, observeMarqueeSpeed, MARQUEE_PX_PER_SEC } from './marquee-speed.js';
import {
  getLibrarySnapshot,
  completionAverage,
  quickWinSpeedIndex,
  backlogOps,
  backlogSlg,
  startRate,
  abandonRate,
  closerPower,
  pythagoreanCompletion,
  barrelRate,
  magicNumber,
  backlogPace,
  hoardRate,
  qualityStartRate,
  topWarGame,
  formatRate,
  formatPct100,
  cleanupCandidateCount,
  hotColdStreak,
  powerSpeedNumber,
  trophyEfficiency,
  gamerscoreEfficiency,
  backlogValuePlus,
  genrePlusMap,
  storePlusMap,
  winSharesByGenre,
  agingCurveBuckets,
  luckAdjustedRating,
  isLeveragePick,
  avgCriticGap,
  peoplesChamp,
  criticsDarling,
  overratedLeader,
  perpetualBetaCount,
  couchReadyRate,
  acquireToPlayDaysAvg,
  dayOnePlayerCount,
  extraInningsAvg,
  gamePassCount,
  doubleDipCount,
  costPerFinish,
  sunkCostUnplayed,
  backlogMortality,
  protonReadyShare,
  protonCount,
  protonTrendingUp,
  protonDeckReadyBacklog,
  psnPlatinumsEarned,
  psnPlatinumHunt,
  psnTrophiesEarned,
  ps5NativeShare,
  ps4Holdouts,
  topTag,
  multiplayerTagShare,
  singleplayerBacklogCount,
  freeItchCount,
  itchSpendTotal,
  installedLocalCount,
  recentlyPlayedCount,
  longestDormant,
  avgMetacritic,
  metacriticClubCount,
  upcomingWishlistCount,
  protonSilverNativeShare,
  protonLowConfidenceCount,
  avgProtonScore,
  boughtOnSaleCount,
  paidItchCount,
  avgOwnedSteamPrice,
  priorityWishlistCount,
  wishlistAddedThisYear,
  wishlistStoreCount,
  lastSeenThisWeek,
  launcherInstallCount,
  hltbLowConfidenceCount,
  coopTaggedOnlyCount,
  partialControllerCount,
  indieTaggedShare,
  avgTrophyCompletion,
  gamerscoreCompletionShare,
  metacritic80UnplayedCount,
  biggestCriticGapGame,
  earlyAccessBacklogCount,
  doubleDipBacklogCount,
  letterCoverageShare,
} from './sabermetrics.js';
import { appendCreativeInsights, appendCreativeMarqueeChips } from './creative-metrics.js';
import { marqueeTip, insightTip, metricKeyForLabel, metricKeyForInsight } from './metric-tips.js';
import { noteMarqueeMetricKeys, noteInsightMetricKeys } from './metrics-rendered.js';
import { familyForInsight, familyForLabel, spreadByFamily } from './stat-families.js';

/** Sabermetric marquee/pill appearance weights (session-stable RNG). */
export const METRIC_WEIGHT = {
  normal: 1,
  friendly: 1,
  moderate: 0.5,
  cryptic: 0.15,
  /** kojima metric — MGSV codec easter egg */
  kojima: 0.03,
};

/** @returns {Set<string>} */
function disabledMetricSet() {
  const arr = state.prefs.metricsDisabled;
  if (!Array.isArray(arr)) return new Set();
  return new Set(arr.filter((k) => typeof k === 'string' && k));
}

/** @param {string} label */
function isMarqueeMetricEnabled(label) {
  const key = metricKeyForLabel(label);
  if (!key) return true;
  return !disabledMetricSet().has(key);
}

/** @param {string} html */
function isInsightMetricEnabled(html) {
  const key = metricKeyForInsight(html);
  if (!key) return true;
  return !disabledMetricSet().has(key);
}

const METRIC_SEED_KEY = '__baklogMetricSeed';

let _insightTimer = null;
let _lastInsights = null;
let _insightFadeTimer = null;
let _insightIndex = 0;

export function stopInsightRotation() {
  if (_insightTimer) clearInterval(_insightTimer);
  if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
  _insightTimer = null;
  _insightFadeTimer = null;
}

function metricRng() {
  let seed;
  try {
    const raw = sessionStorage.getItem(METRIC_SEED_KEY);
    seed = raw != null ? Number(raw) : NaN;
    if (!Number.isFinite(seed)) {
      seed = (Date.now() ^ (Math.random() * 0xffffffff)) >>> 0;
      sessionStorage.setItem(METRIC_SEED_KEY, String(seed));
    }
  } catch {
    seed = (Date.now() ^ (Math.random() * 0xffffffff)) >>> 0;
  }
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** @param {{ w?: number }[]} items */
export function applyMetricWeights(items) {
  const rng = metricRng();
  return items.filter(it => {
    const w = it.w ?? METRIC_WEIGHT.normal;
    return w >= 1 || rng() < w;
  });
}

function normalizeInsightEntries(insights) {
  if (!insights?.length) return [];
  if (typeof insights[0] === 'string') {
    return insights.map(html => ({ html, weight: METRIC_WEIGHT.friendly }));
  }
  return insights;
}

function filterInsightsByWeight(entries) {
  const rng = metricRng();
  return entries.filter(e => {
    const w = e.weight ?? METRIC_WEIGHT.friendly;
    return w >= 1 || rng() < w;
  });
}

function filterInsightsOneLine(el, htmlList) {
  if (!el || !htmlList.length) return htmlList;
  const maxW = el.clientWidth - 24;
  if (maxW <= 0) return htmlList;
  const measurer = document.createElement('span');
  const cs = getComputedStyle(el);
  measurer.style.cssText = [
    'position:absolute',
    'visibility:hidden',
    'white-space:nowrap',
    `font:${cs.font}`,
    `font-size:${cs.fontSize}`,
    `letter-spacing:${cs.letterSpacing}`,
  ].join(';');
  document.body.appendChild(measurer);
  const out = htmlList.filter((html) => {
    measurer.innerHTML = html;
    return measurer.offsetWidth <= maxW;
  });
  measurer.remove();
  return out.length ? out : htmlList;
}

function median(nums) {
  if (!nums.length) return null;
  const s = [...nums].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

/** @returns {{ html: string, weight: number }[]} */
export function buildInsightPool(games, snapIn) {
  const entries = [];
  const add = (html, weight = METRIC_WEIGHT.friendly) => entries.push({ html, weight });
  const backlog = games.filter(g => getPersonal(g).status === 'backlog');
  const maxHrs = state.prefs.quickWinMaxHours || 15;

  const genreHrs = {};
  backlog.forEach(g => {
    gameGenresCanonical(g).forEach(gen => {
      genreHrs[gen] = (genreHrs[gen] || 0) + (hltbMain(g) || 0);
    });
  });
  const topGenre = Object.entries(genreHrs).sort((a, b) => b[1] - a[1])[0];
  if (topGenre && topGenre[1] > 0) {
    add(`Biggest backlog: <strong>${escapeHtml(topGenre[0])}</strong> · ${escapeHtml(formatNum(Math.round(topGenre[1])))}h`);
  }

  const byPlay = [...games].filter(g => combinedPlaytime(g) > 0).sort((a, b) => combinedPlaytime(b) - combinedPlaytime(a));
  if (byPlay[0]) {
    const hrs = Math.round(combinedPlaytime(byPlay[0]) / 60);
    add(`Most played: <strong>${escapeHtml(byPlay[0].name)}</strong> · ${escapeHtml(formatNum(hrs))}h`);
  }

  const hltbVals = backlog.map(g => hltbMain(g)).filter(h => h != null && h > 0);
  if (hltbVals.length) {
    const avg = Math.round(hltbVals.reduce((s, h) => s + h, 0) / hltbVals.length);
    add(`Avg HLTB main: <strong>${escapeHtml(formatNum(avg))}h</strong>`);
  }

  const unplayed = backlog.filter(g => !combinedPlaytime(g)).sort((a, b) => (hltbMain(b) || 0) - (hltbMain(a) || 0));
  if (unplayed[0]) {
    const h = hltbMain(unplayed[0]);
    add(`Longest unplayed: <strong>${escapeHtml(unplayed[0].name)}</strong> · ${h != null ? escapeHtml(formatNum(Math.round(h))) + 'h' : '?'}`);
  }

  const deals = state.wishlistGames.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
  if (deals.length) {
    const top = [...deals].sort((a, b) => dealScore(b) - dealScore(a))[0];
    const cut = getDealInfo(top)?.cut || 0;
    add(`Top deal: <strong>${escapeHtml(top.name)}</strong> · ${coloredCutHtml(cut)}`);
  }

  const rated = games.filter(g => ratingValue(g) > 0);
  if (rated.length) {
    const avg = Math.round(rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length);
    add(`Average review: <strong>${avg}%</strong>`);
  }

  const withDate = games
    .map(g => ({ g, d: g.added_at || '' }))
    .filter(x => x.d)
    .sort((a, b) => b.d.localeCompare(a.d));
  if (withDate[0]) {
    add(`Newest add: <strong>${escapeHtml(withDate[0].g.name)}</strong>`);
  }

  const playedHrs = games.reduce((s, g) => s + combinedPlaytime(g), 0) / 60;
  if (games.length) {
    const ratio = (playedHrs / games.length).toFixed(1);
    add(`Hours per game: <strong>${ratio}h</strong>`);
  }

  const quickWins = backlog.filter(g => ratingValue(g) >= 75 && (hltbMain(g) || 999) <= maxHrs).length;
  if (quickWins) add(`Quick wins ready: <strong>${formatNum(quickWins)}</strong>`);

  const hiddenGems = backlog.filter(g => ratingValue(g) >= 90 && hasEnoughReviews(g) && !combinedPlaytime(g)).length;
  if (hiddenGems) add(`Hidden gems: <strong>${formatNum(hiddenGems)}</strong>`);

  const clutch = backlog.filter(g => isLeveragePick(g));
  if (clutch[0]) add(`Clutch pick: <strong>${escapeHtml(clutch[0].name)}</strong>`);

  const snap = snapIn || getLibrarySnapshot(games);
  const mendoza = Math.round(snap.mendozaLine);
  add(`Mendoza line: <strong>${mendoza}%</strong>`, METRIC_WEIGHT.moderate);

  const tracked = games.filter(g => g.trophy_progress != null);
  const closest = tracked.length
    ? [...tracked].sort((a, b) => b.trophy_progress - a.trophy_progress)[0]
    : null;
  if (closest && closest.trophy_progress < 100) {
    add(`Closest to 100%: <strong>${escapeHtml(closest.name)}</strong> · ${Math.round(closest.trophy_progress)}%`);
  }

  const withFirstPlayed = games
    .map(g => ({ g, t: firstPlayedAt(g) }))
    .filter(x => x.t != null)
    .sort((a, b) => a.t - b.t);
  if (withFirstPlayed[0]) {
    const yr = firstPlayedYear(withFirstPlayed[0].g);
    add(`Playing since <strong>${yr ?? '?'}</strong>: <strong>${escapeHtml(withFirstPlayed[0].g.name)}</strong>`, METRIC_WEIGHT.moderate);
  }

  const sessionGames = games
    .map(g => ({ g, n: playSessionCount(g) }))
    .filter(x => x.n != null)
    .sort((a, b) => b.n - a.n);
  if (sessionGames[0]) {
    add(`Most sessions: <strong>${escapeHtml(sessionGames[0].g.name)}</strong> · ${formatNum(sessionGames[0].n)}`, METRIC_WEIGHT.moderate);
  }
  if (snap.psnSessionTotal > 0) {
    add(`PSN sessions: <strong>${formatNum(snap.psnSessionTotal)}</strong> total`, METRIC_WEIGHT.moderate);
  }

  const avg = completionAverage(snap);
  if (avg != null) {
    add(`Finish rate: <strong>${formatRate(avg)}</strong>`, METRIC_WEIGHT.moderate);
  }
  const warTop = topWarGame(snap);
  if (warTop) {
    add(`Top WAR pick: <strong>${escapeHtml(warTop.g.name)}</strong> · ${warTop.war}`, METRIC_WEIGHT.cryptic);
  }
  const pyth = pythagoreanCompletion(snap);
  if (pyth != null && Math.abs(pyth.delta) >= 0.02) {
    const label = pyth.delta >= 0 ? 'overperforming' : 'underperforming';
    add(`Pythagorean: <strong>${label}</strong>`, METRIC_WEIGHT.cryptic);
  }

  const champ = peoplesChamp(games);
  if (champ) {
    add(`People's champ: <strong>${escapeHtml(champ.g.name)}</strong> · +${champ.gap} vs critics`, METRIC_WEIGHT.moderate);
  }
  const extraInn = extraInningsAvg(snap);
  if (extraInn != null) {
    add(`Extra innings: <strong>${formatNum(extraInn)}h</strong> avg beyond main`, METRIC_WEIGHT.moderate);
  }
  const dDips = doubleDipCount();
  if (dDips != null) {
    add(`Double dips: <strong>${formatNum(dDips)}</strong> titles on 2+ stores`, METRIC_WEIGHT.moderate);
  }
  const mortality = backlogMortality(snap);
  if (mortality) {
    const who = mortality.verdict === 'backlog' ? 'Backlog wins' : 'You might make it';
    add(`Will you die first? <strong>${who}</strong> · finish by age ${mortality.finishByAge}`, METRIC_WEIGHT.cryptic);
  }
  const criticGapAvg = avgCriticGap(games);
  if (criticGapAvg != null) {
    add(`Critic gap: <strong>${criticGapAvg} pts</strong> avg |Steam − Metacritic|`, METRIC_WEIGHT.moderate);
  }

  const avgMc = avgMetacritic(games);
  if (avgMc != null) {
    add(`Avg Metacritic: <strong>${avgMc}</strong>`, METRIC_WEIGHT.normal);
  }
  const dormant = longestDormant(games);
  if (dormant) {
    add(`Longest dormant: <strong>${escapeHtml(dormant.g.name)}</strong>`, METRIC_WEIGHT.moderate);
  }
  const gapLeader = biggestCriticGapGame(games);
  if (gapLeader) {
    add(`Biggest critic gap: <strong>${escapeHtml(gapLeader.g.name)}</strong> · ${gapLeader.gap} pts`, METRIC_WEIGHT.moderate);
  }

  appendCreativeInsights(entries, games, snap, METRIC_WEIGHT);

  noteInsightMetricKeys(entries.map((e) => metricKeyForInsight(e.html)));
  return entries.filter((e) => isInsightMetricEnabled(e.html));
}

function formatDollarMarquee(n) {
  if (n == null || Number.isNaN(n)) return ' - ';
  return formatMoney(n, displayCurrency(), { maximumFractionDigits: 0, minimumFractionDigits: 0 });
}

/** Colored cut % for marquee / insight pills (deal cut-depth scale). */
function coloredCutHtml(cut, { signed = true, className = 'dash-insight-cut' } = {}) {
  const label = signed ? `-${cut}%` : `${cut}%`;
  return `<strong class="${className} ${cutBucketClass(cut)}">${escapeHtml(label)}</strong>`;
}

export function buildMarqueeItems(games, snapIn) {
  const maxHrs = state.prefs.quickWinMaxHours || 15;
  const status = (g) => getPersonal(g).status || 'backlog';
  const playMin = (g) => combinedPlaytime(g);
  const rating = (g) => ratingValue(g);
  const hltb = (g) => hltbMain(g);

  const total = games.length;
  const backlog = games.filter(g => status(g) === 'backlog');
  const playing = games.filter(g => status(g) === 'playing');
  const unfinished = games.filter(g => status(g) === 'unfinished');
  const next = games.filter(g => status(g) === 'next');
  const finished = games.filter(g => status(g) === 'finished');
  const touched = games.filter(g => playMin(g) > 0);
  const playedHrs = games.reduce((s, g) => s + playMin(g), 0) / 60;
  const backlogHrs = backlog.reduce((s, g) => s + (hltb(g) || 0), 0);
  const ratedGames = games.filter(g => rating(g) > 0);

  const wl = state.wishlistGames || [];
  const onSale = wl.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
  const wlSources = new Set(
    wl.map(g => g.wishlist_store || g.store_target || (g.manual ? 'manual' : 'steam')).filter(Boolean)
  ).size;
  const itchGameCount = (state.itchGames || []).filter(itchIsGame).length;
  const snap = snapIn || getLibrarySnapshot(games);

  const items = [];
  const push = (glyph, iconCls, value, label, valueHtml, opts = {}) => {
    items.push({
      glyph,
      iconCls,
      valueHtml: valueHtml ?? escapeHtml(String(value)),
      label,
      family: familyForLabel(label),
      w: opts.weight ?? METRIC_WEIGHT.normal,
      iconTitle: opts.iconTitle,
    });
  };
  const W = METRIC_WEIGHT;

  if (total > 0) push('>', '', formatNum(total), 'games owned');
  const stores = new Set(games.map(g => normalizeGame(g).store)).size;
  if (stores > 0) push('>', '', String(stores), 'stores');
  if (wlSources > 0) push('*', 'is-violet', String(wlSources), 'wishlists tracked');
  if (itchGameCount > 0) push('>', '', formatNum(itchGameCount), 'itch games');
  if (backlog.length) push('~', 'is-amber', formatNum(backlog.length), 'in backlog');
  if (finished.length) push('+', 'is-emerald', formatNum(finished.length), 'completed');
  if (touched.length) push('>', '', formatNum(touched.length), 'games touched');
  if (playing.length) push('*', 'is-violet', formatNum(playing.length), 'in progress');
  if (next.length) push('*', 'is-amber', formatNum(next.length), 'queued next');
  if (unfinished.length) push('^', 'is-rose', formatNum(unfinished.length), 'left unfinished');

  if (total > 0 && snap.nonSkip) {
    const completionPct = Math.round(snap.completionRate * 100);
    push('+', 'is-emerald', `${completionPct}%`, 'completion (excl. skip)');
    const touchedPct = Math.round((touched.length / total) * 100);
    push('~', 'is-amber', `${touchedPct}%`, 'ever touched');
  }

  if (playedHrs > 0) push('~', 'is-amber', `${formatNum(Math.round(playedHrs))}h`, 'all-time played');
  if (touched.length) {
    const avgSession = Math.round(playedHrs / touched.length);
    if (avgSession > 0) push('~', 'is-amber', `${avgSession}h`, 'avg time per played game');
  }
  const mostPlayed = [...games].sort((a, b) => playMin(b) - playMin(a))[0];
  if (mostPlayed && playMin(mostPlayed) > 0) {
    push('^', 'is-rose', `${mostPlayed.name} · ${formatNum(Math.round(playMin(mostPlayed) / 60))}h`, 'most-played');
  }

  const hltbVals = backlog.map(hltb).filter(h => h != null && h > 0);
  if (hltbVals.length) {
    const avg = Math.round(hltbVals.reduce((s, h) => s + h, 0) / hltbVals.length);
    push('~', 'is-amber', `${formatNum(avg)}h`, 'avg backlog main');
    const med = [...hltbVals].sort((a, b) => a - b)[Math.floor(hltbVals.length / 2)];
    push('~', 'is-amber', `${formatNum(Math.round(med))}h`, 'median backlog main');
  }

  const longest = [...backlog].sort((a, b) => (hltb(b) || 0) - (hltb(a) || 0))[0];
  if (longest && hltb(longest)) {
    push('^', 'is-rose', `${longest.name} · ${formatNum(Math.round(hltb(longest)))}h`, 'longest backlog');
  }
  const shortest = [...backlog].filter(g => hltb(g) > 0).sort((a, b) => hltb(a) - hltb(b))[0];
  if (shortest) {
    push('>', '', `${shortest.name} · ${(hltb(shortest)).toFixed(1)}h`, 'shortest backlog');
  }

  const underTwo = backlog.filter(g => hltb(g) && hltb(g) <= 2).length;
  if (underTwo) push('>', '', formatNum(underTwo), 'under 2h to beat');
  const underFive = backlog.filter(g => hltb(g) && hltb(g) <= 5).length;
  if (underFive) push('>', '', formatNum(underFive), 'under 5h to beat');
  const marathons = backlog.filter(g => hltb(g) && hltb(g) >= 50).length;
  if (marathons) push('^', 'is-rose', formatNum(marathons), '50h+ marathons');
  const epics = backlog.filter(g => hltb(g) && hltb(g) >= 100).length;
  if (epics) push('^', 'is-rose', formatNum(epics), '100h+ epics');

  if (backlogHrs > 0) {
    const years2h = (backlogHrs / (2 * 365)).toFixed(1);
    push('~', 'is-amber', `${years2h} yrs`, 'to clear at 2h/day');
    const years4h = (backlogHrs / (4 * 365)).toFixed(1);
    push('~', 'is-amber', `${years4h} yrs`, 'to clear at 4h/day');
    const days8h = Math.round(backlogHrs / 8);
    push('~', 'is-amber', `${formatNum(days8h)} d`, 'non-stop at 8h/day');
  }

  if (ratedGames.length) {
    const avgRating = Math.round(ratedGames.reduce((s, g) => s + rating(g), 0) / ratedGames.length);
    push('+', 'is-emerald', `${avgRating}%`, 'avg review score');
    const backlogRated = backlog.filter(g => rating(g) > 0);
    if (backlogRated.length) {
      const avgBacklogRating = Math.round(backlogRated.reduce((s, g) => s + rating(g), 0) / backlogRated.length);
      push('+', 'is-emerald', `${avgBacklogRating}%`, 'avg backlog review');
    }
    const ratedPct = Math.round((ratedGames.length / total) * 100);
    push('~', 'is-amber', `${ratedPct}%`, 'of library rated');
  }

  const tracked = games.filter(g => g.trophy_progress != null);
  if (tracked.length) {
    const avgTrophy = Math.round(tracked.reduce((s, g) => s + g.trophy_progress, 0) / tracked.length);
    push('~', 'is-amber', `${avgTrophy}%`, 'avg achievement completion');
    const perfect = tracked.filter(g => g.trophy_progress >= 100).length;
    if (perfect) push('+', 'is-emerald', formatNum(perfect), 'fully completed (100%)');
    const nearComplete = tracked.filter(g => g.trophy_progress >= 90 && g.trophy_progress < 100).length;
    if (nearComplete) push('*', 'is-amber', formatNum(nearComplete), 'one push from 100%');
    const closest = [...tracked].sort((a, b) => b.trophy_progress - a.trophy_progress)[0];
    if (closest && closest.trophy_progress < 100) {
      push('^', 'is-rose', `${closest.name} · ${Math.round(closest.trophy_progress)}%`, 'closest to 100%');
    }
    const platReady = tracked.filter(g => {
      const h = hltbMain(g);
      return g.trophy_progress >= 80 && g.trophy_progress < 100 && h != null && h <= 12;
    });
    if (platReady.length) {
      push('*', 'is-violet', formatNum(platReady.length), 'platinum potential', null, { weight: W.friendly });
      const best = [...platReady].sort((a, b) => b.trophy_progress - a.trophy_progress)[0];
      push('^', 'is-rose', `${best.name} · ${Math.round(best.trophy_progress)}%`, 'closest platinum', null, { weight: W.friendly });
    }
  }

  const xboxScored = games.filter(g => (g.xbox_gamerscore_current || 0) > 0);
  if (xboxScored.length) {
    const sumCurrent = xboxScored.reduce((s, g) => s + (g.xbox_gamerscore_current || 0), 0);
    push('*', 'is-amber', formatNum(sumCurrent), 'gamerscore earned');
    const sumTotal = xboxScored.reduce((s, g) => s + (g.xbox_gamerscore_total || 0), 0);
    if (sumTotal > 0) {
      const pct = Math.round((sumCurrent / sumTotal) * 100);
      push('~', 'is-amber', `${pct}%`, 'of available gamerscore');
    }
  }

  const top90 = backlog.filter(g => rating(g) >= 90 && hasEnoughReviews(g)).length;
  if (top90) push('*', 'is-amber', formatNum(top90), '90%+ unplayed');
  const top80 = backlog.filter(g => rating(g) >= 80 && hasEnoughReviews(g)).length;
  if (top80) push('*', 'is-amber', formatNum(top80), '80%+ unplayed');
  const qwIdx = quickWinSpeedIndex(snap, maxHrs);
  if (qwIdx) push('>', '', formatNum(qwIdx), 'quick-win speed index', null, { weight: W.friendly });
  const hiddenGems = backlog.filter(g => rating(g) >= 90 && hasEnoughReviews(g) && !playMin(g)).length;
  if (hiddenGems) push('*', 'is-amber', formatNum(hiddenGems), 'hidden gems', null, { weight: W.friendly });

  const topRated = [...backlog].filter(g => rating(g) > 0 && hasEnoughReviews(g))
    .sort((a, b) => rating(b) - rating(a))[0];
  if (topRated) push('*', 'is-amber', `${topRated.name} · ${rating(topRated)}%`, 'top-rated unplayed');

  const compAvg = completionAverage(snap);
  if (compAvg != null) push('+', 'is-emerald', formatRate(compAvg), 'completion AVG', null, { weight: W.moderate });
  const ops = backlogOps(snap);
  if (ops != null) push('+', 'is-emerald', formatRate(ops), 'backlog OPS', null, { weight: W.cryptic });
  const obp = startRate(snap);
  if (obp != null) push('~', 'is-amber', formatPct100(obp), 'start rate (OBP)', null, { weight: W.cryptic });
  const kRate = abandonRate(snap);
  if (kRate != null) push('^', 'is-rose', formatPct100(kRate), 'abandon rate (K%)', null, { weight: W.cryptic });
  const iso = closerPower(snap);
  if (iso != null && iso > 0) push('*', 'is-amber', formatRate(iso, 2), 'closer power (ISO)', null, { weight: W.cryptic });
  const slg = backlogSlg(snap);
  if (slg != null) push('+', 'is-emerald', formatRate(slg), 'slugging (SLG)', null, { weight: W.cryptic });
  const barrels = barrelRate(snap);
  if (barrels != null && barrels > 0) push('+', 'is-emerald', formatPct100(barrels), 'barrel rate', null, { weight: W.moderate });
  const magic = magicNumber(snap, 0.5);
  if (magic != null && magic > 0) push('>', '', formatNum(magic), 'magic # to 50%', null, { weight: W.friendly });
  const pace = backlogPace(snap);
  if (pace != null) push('~', 'is-amber', `${formatNum(Math.round(pace))}h`, 'backlog pace (median HLTB)', null, { weight: W.moderate });
  const hoard = hoardRate(snap);
  if (hoard != null) push('^', 'is-rose', formatPct100(hoard), 'hoard rate (never touched)', null, { weight: W.moderate });
  const qs = qualityStartRate(snap);
  if (qs != null) push('+', 'is-emerald', formatPct100(qs), 'quality start rate', null, { weight: W.moderate });
  const warTop = topWarGame(snap);
  if (warTop) push('*', 'is-violet', `${warTop.g.name} · ${warTop.war}`, 'top WAR', null, { weight: W.cryptic });
  const cleanup = cleanupCandidateCount(snap);
  if (cleanup) push('^', 'is-rose', formatNum(cleanup), 'cleanup candidates', null, { weight: W.friendly });
  const clutchCount = backlog.filter(g => isLeveragePick(g)).length;
  if (clutchCount) push('*', 'is-violet', formatNum(clutchCount), 'clutch picks', null, { weight: W.friendly });
  const streak = hotColdStreak(snap);
  if (streak) {
    const streakGlyph = streak === 'hot' ? '+' : streak === 'cold' ? '^' : '~';
    const streakCls = streak === 'hot' ? 'is-emerald' : streak === 'cold' ? 'is-rose' : 'is-amber';
    push(streakGlyph, streakCls, streak, 'finish streak');
  }
  const psn = powerSpeedNumber(snap);
  if (psn != null) push('*', 'is-violet', String(psn), 'power-speed #', null, { weight: W.cryptic });
  const tro = trophyEfficiency(snap);
  if (tro != null) push('~', 'is-amber', `${tro}%`, 'trophy efficiency', null, { weight: W.friendly });
  const gs = gamerscoreEfficiency(snap);
  if (gs != null) push('~', 'is-amber', `${gs}%`, 'gamerscore efficiency', null, { weight: W.friendly });
  const pyth = pythagoreanCompletion(snap);
  if (pyth != null) {
    const sign = pyth.delta >= 0 ? '+' : '';
    push('~', pyth.delta >= 0 ? 'is-emerald' : 'is-rose', `${sign}${formatPct100(Math.abs(pyth.delta), 0)}`, 'vs pythagorean', null, { weight: W.cryptic });
  }

  if (snap.rBar > 0) {
    push('~', 'is-amber', `${Math.round(snap.rBar)}%`, 'league avg rating', null, { weight: W.friendly });
  }
  const belowMendoza = backlog.filter(g => rating(g) > 0 && rating(g) < snap.mendozaLine).length;
  if (belowMendoza) {
    push('^', 'is-rose', formatNum(belowMendoza), `below Mendoza (${Math.round(snap.mendozaLine)}%)`, null, { weight: W.moderate });
  }

  let topBv = null;
  let topBvVal = -Infinity;
  let bvSum = 0;
  let bvN = 0;
  for (const g of backlog) {
    const bv = backlogValuePlus(g, snap);
    if (bv == null) continue;
    bvSum += bv;
    bvN++;
    if (bv > topBvVal) {
      topBvVal = bv;
      topBv = g;
    }
  }
  if (topBv) {
    push('*', 'is-violet', `${topBv.name} · ${topBvVal}`, 'BV+ leader', null, { weight: W.cryptic });
  }
  if (bvN) {
    push('~', 'is-amber', String(Math.round(bvSum / bvN)), 'avg BV+ (100 = avg)', null, { weight: W.cryptic });
  }

  const genrePlus = genrePlusMap(snap);
  const genreEntries = Object.entries(genrePlus).sort((a, b) => b[1] - a[1]);
  if (genreEntries[0]) {
    push('*', 'is-amber', `${genreEntries[0][0]} · ${genreEntries[0][1]}`, 'Genre+', null, { weight: W.moderate });
  }
  if (genreEntries.length > 1) {
    const weak = genreEntries[genreEntries.length - 1];
    push('^', 'is-rose', `${weak[0]} · ${weak[1]}`, 'weakest Genre+', null, { weight: W.moderate });
  }
  const storePlus = storePlusMap(snap);
  const storeEntries = Object.entries(storePlus).sort((a, b) => b[1] - a[1]);
  if (storeEntries[0]) {
    push('>', '', `${storeEntries[0][0]} · ${storeEntries[0][1]}`, 'Store+', null, { weight: W.moderate });
  }

  const winShares = winSharesByGenre(snap);
  if (winShares[0]) {
    push('+', 'is-emerald', `${winShares[0][0]} · ${formatNum(winShares[0][1])}`, 'win shares leader', null, { weight: W.moderate });
  }

  const aging = agingCurveBuckets(snap);
  const rookie = aging.find(b => b.label === '<30d');
  const veteran = aging.find(b => b.label === '1y+');
  if (rookie?.total) {
    push('~', 'is-amber', `${rookie.finishRate}%`, 'rookie finish rate (<30d)', null, { weight: W.moderate });
  }
  if (veteran?.total) {
    push('^', 'is-rose', `${veteran.finishRate}%`, 'veteran finish rate (1y+)', null, { weight: W.moderate });
  }

  let luckSwing = null;
  let luckDelta = 0;
  for (const g of games) {
    if (rating(g) <= 0) continue;
    const adj = luckAdjustedRating(g, snap.rBar);
    const d = Math.abs(adj - rating(g));
    if (d > luckDelta) {
      luckDelta = d;
      luckSwing = g;
    }
  }
  if (luckSwing && luckDelta >= 3) {
    push('~', 'is-amber', `${luckSwing.name} · ${luckAdjustedRating(luckSwing, snap.rBar)}%`, 'luck-adjusted', null, { weight: W.cryptic });
  }

  const stealsCount = wl.filter(isStealDeal).length;
  if (stealsCount) push('+', 'is-emerald', formatNum(stealsCount), 'steal-tier deals');
  if (onSale.length) push('+', 'is-emerald', formatNum(onSale.length), 'on sale now');
  if (onSale.length) {
    const top = [...onSale].sort((a, b) => dealScore(b) - dealScore(a))[0];
    const cut = getDealInfo(top)?.cut || 0;
    push(
      '+',
      'is-emerald',
      '',
      'top deal',
      `${escapeHtml(top.name)} ${coloredCutHtml(cut, { className: 'dash-marquee-cut' })}`,
    );
    const cuts = onSale.map(g => getDealInfo(g)?.cut || 0).filter(x => x > 0);
    if (cuts.length) {
      const avgCut = Math.round(cuts.reduce((s, c2) => s + c2, 0) / cuts.length);
      push('+', 'is-emerald', '', 'avg discount', coloredCutHtml(avgCut, { signed: false, className: 'dash-marquee-cut' }));
      const steepest = Math.max(...cuts);
      push('+', 'is-emerald', '', 'steepest cut', coloredCutHtml(steepest, { className: 'dash-marquee-cut' }));
    }
  }

  let wishlistValue = 0;
  let wishlistSaleNow = 0;
  for (const g of wl) {
    const d = getDealInfo(g);
    if (d?.regular != null) wishlistValue += d.regular;
    if (d?.price != null) wishlistSaleNow += d.price;
  }
  if (wishlistValue > 0) push('#', 'is-violet', formatDollarMarquee(wishlistValue), 'wishlist value');
  if (wishlistSaleNow > 0 && wishlistSaleNow < wishlistValue) {
    push('#', 'is-violet', formatDollarMarquee(wishlistValue - wishlistSaleNow), 'savings if bought now');
  }

  const parseReleaseYear = (d) => {
    if (!d) return null;
    const s = String(d);
    const m = s.match(/\b(19\d{2}|20\d{2}|21\d{2})\b/);
    if (m) return parseInt(m[1], 10);
    const t = Date.parse(s);
    if (!isNaN(t)) return new Date(t).getUTCFullYear();
    return null;
  };
  const withReleaseYear = games
    .map(g => {
      const y = parseReleaseYear(g.release_date);
      return y != null ? { g, y } : null;
    })
    .filter(Boolean);
  if (withReleaseYear.length) {
    const oldest = withReleaseYear.reduce((a, b) => a.y < b.y ? a : b);
    push('^', 'is-rose', `${oldest.g.name} · ${oldest.y}`, 'oldest in library');
    const newest = withReleaseYear.reduce((a, b) => a.y > b.y ? a : b);
    push('*', 'is-violet', `${newest.g.name} · ${newest.y}`, 'newest release owned');
    const decadeCounts = {};
    for (const { y } of withReleaseYear) {
      const dec = Math.floor(y / 10) * 10;
      decadeCounts[dec] = (decadeCounts[dec] || 0) + 1;
    }
    const topDec = Object.entries(decadeCounts).sort((a, b) => b[1] - a[1])[0];
    if (topDec) push('>', '', `${topDec[0]}s · ${formatNum(topDec[1])}`, 'top decade');
    const oldUnplayed = backlog
      .map(g => ({ g, y: parseReleaseYear(g.release_date) }))
      .filter(x => x.y != null)
      .reduce((a, b) => (!a || a.y > b.y) ? b : a, null);
    if (oldUnplayed) push('^', 'is-rose', `${oldUnplayed.g.name} · ${oldUnplayed.y}`, 'oldest unplayed');
  }

  const withAddDate = games
    .map(g => ({ g, d: g.added_at || '' }))
    .filter(x => x.d)
    .sort((a, b) => b.d.localeCompare(a.d));
  if (withAddDate[0]) push('*', 'is-violet', withAddDate[0].g.name, 'newest add');

  const thisYear = new Date().getFullYear();
  const addedThisYear = games.filter(g => (g.added_at || '').startsWith(String(thisYear))).length;
  if (addedThisYear) push('+', 'is-emerald', formatNum(addedThisYear), `added in ${thisYear}`);

  const devCounts = {};
  const pubCounts = {};
  for (const g of games) {
    const ng = normalizeGame(g);
    (ng.developers || g.developers || []).forEach(d => { if (d) devCounts[d] = (devCounts[d] || 0) + 1; });
    (ng.publishers || g.publishers || []).forEach(p => { if (p) pubCounts[p] = (pubCounts[p] || 0) + 1; });
  }
  const topDev = Object.entries(devCounts).sort((a, b) => b[1] - a[1])[0];
  if (topDev && topDev[1] > 1) push('*', 'is-violet', `${topDev[0]} · ${formatNum(topDev[1])}`, 'top developer');
  const topPub = Object.entries(pubCounts).sort((a, b) => b[1] - a[1])[0];
  if (topPub && topPub[1] > 1) push('*', 'is-violet', `${topPub[0]} · ${formatNum(topPub[1])}`, 'top publisher');
  const uniqueDevs = Object.keys(devCounts).length;
  if (uniqueDevs > 1) push('>', '', formatNum(uniqueDevs), 'unique developers');

  const genreCounts = {};
  for (const g of games) {
    const gens = gameGenresCanonical(g);
    gens.forEach(genre => { if (genre) genreCounts[genre] = (genreCounts[genre] || 0) + 1; });
  }
  const topGenre = Object.entries(genreCounts).sort((a, b) => b[1] - a[1])[0];
  if (topGenre) push('*', 'is-amber', `${topGenre[0]} · ${formatNum(topGenre[1])}`, 'top genre');
  const uniqueGenres = Object.keys(genreCounts).length;
  if (uniqueGenres > 1) push('>', '', formatNum(uniqueGenres), 'unique genres');

  const storeCounts = {};
  for (const g of games) {
    const s = normalizeGame(g).store;
    if (s) storeCounts[s] = (storeCounts[s] || 0) + 1;
  }
  const topStore = Object.entries(storeCounts).sort((a, b) => b[1] - a[1])[0];
  if (topStore) push('>', '', `${topStore[0]} · ${formatNum(topStore[1])}`, 'biggest store');

  const catGames = games.filter(g => String(g.name || '').toLowerCase().includes('cat')).length;
  if (catGames) push('=^..^=', 'is-violet', formatNum(catGames), 'cat games', null, { weight: W.friendly });

  if (stores > 0 && total > 0) {
    const avgPerStore = Math.round(total / stores);
    push('~', 'is-amber', formatNum(avgPerStore), 'games per store avg');
  }

  const longestBeat = [...finished]
    .filter(g => hltb(g) > 0)
    .sort((a, b) => hltb(b) - hltb(a))[0];
  if (longestBeat) {
    push('^', 'is-rose', `${longestBeat.name} · ${formatNum(Math.round(hltb(longestBeat)))}h`, 'longest game beaten');
  }
  const finishedHrs = finished.reduce((s, g) => s + (hltb(g) || 0), 0);
  if (finishedHrs > 0) {
    push('+', 'is-emerald', `${formatNum(Math.round(finishedHrs))}h`, 'total hours finished', null, { weight: W.friendly });
  }
  const compHrs = games.map(g => g.hltb_completionist_hours).filter(h => h != null && h > 0);
  if (compHrs.length) {
    const compSum = compHrs.reduce((s, h) => s + h, 0);
    push('~', 'is-amber', `${formatNum(Math.round(compSum))}h`, 'completionist hours total');
    const compAvg = Math.round(compSum / compHrs.length);
    push('~', 'is-amber', `${formatNum(compAvg)}h`, 'avg completionist run');
  }

  const coopGames = games.filter(g => g.coop_online || g.coop_local);
  if (coopGames.length) {
    const pct = Math.round((coopGames.length / total) * 100);
    push('>', '', `${formatNum(coopGames.length)} · ${pct}%`, 'co-op ready', null, { weight: W.friendly });
  }

  const finishedThisYear = games.filter(g =>
    status(g) === 'finished' && String(g.last_played || '').startsWith(String(thisYear)),
  ).length;
  const netAdded = addedThisYear - finishedThisYear;
  if (addedThisYear || finishedThisYear) {
    const sign = netAdded >= 0 ? '+' : '';
    push(netAdded >= 0 ? '+' : '^', netAdded >= 0 ? 'is-emerald' : 'is-rose', `${sign}${formatNum(netAdded)}`, `net adds in ${thisYear}`);
  }

  const ratingVals = ratedGames.map(g => rating(g));
  const medRating = median(ratingVals);
  if (medRating != null) push('~', 'is-amber', `${medRating}%`, 'median review score');

  const priorityCount = games.filter(g => (getPersonal(g).priority || 0) > 0).length;
  if (priorityCount) push('*', 'is-violet', formatNum(priorityCount), 'priority flagged');

  const oldestPlayed = games
    .map(g => ({ g, t: firstPlayedAt(g) }))
    .filter(x => x.t != null)
    .sort((a, b) => a.t - b.t)[0];
  if (oldestPlayed) {
    const yr = firstPlayedYear(oldestPlayed.g);
    push('^', 'is-rose', `${oldestPlayed.g.name} · ${yr ?? '?'}`, 'first PSN session');
  }
  const topSessions = games
    .map(g => ({ g, n: playSessionCount(g) }))
    .filter(x => x.n != null)
    .sort((a, b) => b.n - a.n)[0];
  if (topSessions) {
    push('*', 'is-violet', `${topSessions.g.name} · ${formatNum(topSessions.n)}`, 'most PSN sessions');
  }
  if (snap.psnSessionTotal > 0) {
    push('>', '', formatNum(snap.psnSessionTotal), 'PSN sessions total');
  }

  const criticGapAvg = avgCriticGap(games);
  if (criticGapAvg != null) {
    push('~', 'is-amber', `${criticGapAvg} pts`, 'critic gap (avg)', null, { weight: W.moderate });
  }
  const champ = peoplesChamp(games);
  if (champ) {
    push('*', 'is-violet', `${champ.g.name} · +${champ.gap}`, "people's champ", null, { weight: W.moderate });
  }
  const darling = criticsDarling(games);
  if (darling) {
    push('*', 'is-amber', `${darling.g.name} · ${darling.score}`, "critics' darling", null, { weight: W.moderate });
  }
  const overrated = overratedLeader(games);
  if (overrated) {
    push('^', 'is-rose', `${overrated.g.name} · ${overrated.gap}`, 'overrated index', null, { weight: W.cryptic });
  }
  const betaCount = perpetualBetaCount(snap);
  if (betaCount != null) {
    push('^', 'is-rose', formatNum(betaCount), 'perpetual beta', null, { weight: W.moderate });
  }
  const couch = couchReadyRate(snap);
  if (couch != null) {
    push('>', '', formatPct100(couch), 'couch-ready %', null, { weight: W.friendly });
  }
  const agingDays = acquireToPlayDaysAvg(snap);
  if (agingDays != null) {
    push('~', 'is-amber', `${formatNum(agingDays)}d`, 'aging curve', null, { weight: W.moderate });
  }
  const dayOne = dayOnePlayerCount(snap);
  if (dayOne != null) {
    push('+', 'is-emerald', formatNum(dayOne), 'day-one player', null, { weight: W.friendly });
  }
  const extraInn = extraInningsAvg(snap);
  if (extraInn != null) {
    push('~', 'is-amber', `${formatNum(extraInn)}h`, 'extra innings', null, { weight: W.moderate });
  }
  const gpCount = gamePassCount(snap);
  if (gpCount != null) {
    push('*', 'is-violet', formatNum(gpCount), "subscriber's dividend", null, { weight: W.friendly });
  }
  const dDips = doubleDipCount();
  if (dDips != null) {
    push('>', '', formatNum(dDips), 'double dips', null, { weight: W.moderate });
  }
  const cpf = costPerFinish(snap);
  if (cpf != null) {
    push('#', 'is-violet', formatDollarMarquee(cpf), 'cost per finish', null, { weight: W.moderate });
  }
  const sunk = sunkCostUnplayed(snap);
  if (sunk != null) {
    push('#', 'is-violet', formatDollarMarquee(sunk), 'sunk cost', null, { weight: W.moderate });
  }
  const mortality = backlogMortality(snap);
  if (mortality) {
    const who = mortality.verdict === 'backlog' ? 'Backlog wins' : 'You might';
    push('^', mortality.verdict === 'backlog' ? 'is-rose' : 'is-emerald', `${who} · age ${mortality.finishByAge}`, 'will you die first?', null, { weight: W.cryptic });
  }

  const deckReady = protonReadyShare(games);
  if (deckReady != null) {
    push('>', '', `${Math.round(deckReady * 100)}%`, 'Deck-ready %', null, { weight: W.normal });
  }
  const protonPlat = protonCount(games, 'platinum');
  if (protonPlat != null) {
    push('+', 'is-emerald', formatNum(protonPlat), 'Proton platinum', null, { weight: W.normal });
  }
  const borked = protonCount(games, 'borked');
  if (borked != null) {
    push('^', 'is-rose', formatNum(borked), 'borked on Linux', null, { weight: W.moderate });
  }
  const trendingUp = protonTrendingUp(games);
  if (trendingUp != null) {
    push('*', 'is-violet', formatNum(trendingUp), 'Proton trending up', null, { weight: W.cryptic });
  }
  const deckBacklog = protonDeckReadyBacklog(games, status);
  if (deckBacklog != null) {
    push('~', 'is-amber', formatNum(deckBacklog), 'Deck-ready backlog', null, { weight: W.moderate });
  }

  const platEarned = psnPlatinumsEarned(games);
  if (platEarned != null) {
    push('+', 'is-emerald', formatNum(platEarned), 'platinums earned', null, { weight: W.normal });
  }
  const platHunt = psnPlatinumHunt(games);
  if (platHunt != null) {
    push('*', 'is-amber', formatNum(platHunt), 'platinum hunt', null, { weight: W.moderate });
  }
  const troEarned = psnTrophiesEarned(games);
  if (troEarned != null) {
    push('>', '', formatNum(troEarned), 'trophies earned', null, { weight: W.normal });
  }

  const ps5Share = ps5NativeShare(games);
  if (ps5Share != null) {
    push('>', '', `${Math.round(ps5Share * 100)}%`, 'PS5-native %', null, { weight: W.moderate });
  }
  const ps4Only = ps4Holdouts(games);
  if (ps4Only != null) {
    push('^', 'is-rose', formatNum(ps4Only), 'PS4 holdouts', null, { weight: W.cryptic });
  }

  const tagTop = topTag(games);
  if (tagTop) {
    push('>', '', `${tagTop.tag} · ${formatNum(tagTop.count)}`, 'top tag', null, { weight: W.normal });
  }
  const mpShare = multiplayerTagShare(games);
  if (mpShare != null) {
    push('>', '', `${Math.round(mpShare * 100)}%`, 'multiplayer share', null, { weight: W.normal });
  }
  const spBacklog = singleplayerBacklogCount(games, status);
  if (spBacklog != null) {
    push('~', 'is-amber', formatNum(spBacklog), 'singleplayer backlog', null, { weight: W.moderate });
  }

  const freeItch = freeItchCount(games);
  if (freeItch != null) {
    push('+', 'is-emerald', formatNum(freeItch), 'free itch games', null, { weight: W.normal });
  }
  const itchSpend = itchSpendTotal(games);
  if (itchSpend != null) {
    push('#', 'is-violet', formatDollarMarquee(itchSpend), 'itch spend', null, { weight: W.moderate });
  }

  const installed = installedLocalCount(games);
  if (installed != null) {
    push('>', '', formatNum(installed), 'installed locally', null, { weight: W.normal });
  }
  const recent30 = recentlyPlayedCount(games);
  if (recent30 != null) {
    push('*', 'is-violet', formatNum(recent30), 'played in last 30d', null, { weight: W.normal });
  }

  const mcClub = metacriticClubCount(games);
  if (mcClub != null) {
    push('+', 'is-emerald', formatNum(mcClub), 'Metacritic 90+ club', null, { weight: W.moderate });
  }

  const upcomingWl = upcomingWishlistCount(wl);
  if (upcomingWl != null) {
    push('*', 'is-amber', formatNum(upcomingWl), 'upcoming wishlist', null, { weight: W.moderate });
  }

  const silverNative = protonSilverNativeShare(games);
  if (silverNative != null) {
    push('>', '', `${Math.round(silverNative * 100)}%`, 'silver or native %', null, { weight: W.moderate });
  }
  const protonLowConf = protonLowConfidenceCount(games);
  if (protonLowConf != null) {
    push('^', 'is-rose', formatNum(protonLowConf), 'Proton low confidence', null, { weight: W.moderate });
  }
  const avgProton = avgProtonScore(games);
  if (avgProton != null) {
    push('~', 'is-amber', String(avgProton), 'avg Proton score', null, { weight: W.cryptic });
  }

  const onSaleOwned = boughtOnSaleCount(games);
  if (onSaleOwned != null) {
    push('#', 'is-violet', formatNum(onSaleOwned), 'bought on sale', null, { weight: W.moderate });
  }
  const paidItch = paidItchCount(games);
  if (paidItch != null) {
    push('#', 'is-violet', formatNum(paidItch), 'paid itch games', null, { weight: W.normal });
  }
  const avgSteamPrice = avgOwnedSteamPrice(games);
  if (avgSteamPrice != null) {
    push('#', 'is-violet', formatDollarMarquee(avgSteamPrice), 'avg owned Steam price', null, { weight: W.moderate });
  }

  const prioWl = priorityWishlistCount(wl);
  if (prioWl != null) {
    push('*', 'is-violet', formatNum(prioWl), 'priority wishlist', null, { weight: W.moderate });
  }
  const wlThisYear = wishlistAddedThisYear(wl);
  if (wlThisYear != null) {
    push('+', 'is-emerald', formatNum(wlThisYear), 'wishlist added this year', null, { weight: W.normal });
  }
  const wlStores = wishlistStoreCount(wl);
  if (wlStores != null) {
    push('>', '', formatNum(wlStores), 'wishlist stores', null, { weight: W.normal });
  }

  const seenWeek = lastSeenThisWeek(games);
  if (seenWeek != null) {
    push('*', 'is-violet', formatNum(seenWeek), 'last seen this week', null, { weight: W.normal });
  }
  const launcher = launcherInstallCount(games);
  if (launcher != null) {
    push('>', '', formatNum(launcher), 'launcher installs', null, { weight: W.normal });
  }
  const hltbLo = hltbLowConfidenceCount(games);
  if (hltbLo != null) {
    push('^', 'is-rose', formatNum(hltbLo), 'HLTB low confidence', null, { weight: W.moderate });
  }

  const coopTagOnly = coopTaggedOnlyCount(games);
  if (coopTagOnly != null) {
    push('~', 'is-amber', formatNum(coopTagOnly), 'co-op tagged only', null, { weight: W.cryptic });
  }
  const partialPad = partialControllerCount(games);
  if (partialPad != null) {
    push('>', '', formatNum(partialPad), 'partial controller', null, { weight: W.moderate });
  }
  const indieShare = indieTaggedShare(games);
  if (indieShare != null) {
    push('>', '', `${Math.round(indieShare * 100)}%`, 'indie-tagged %', null, { weight: W.normal });
  }

  const troComp = avgTrophyCompletion(games);
  if (troComp != null) {
    push('~', 'is-amber', `${Math.round(troComp * 100)}%`, 'avg trophy completion', null, { weight: W.normal });
  }
  const gsComp = gamerscoreCompletionShare(games);
  if (gsComp != null) {
    push('~', 'is-amber', `${Math.round(gsComp * 100)}%`, 'gamerscore completion %', null, { weight: W.normal });
  }

  const mc80Unplayed = metacritic80UnplayedCount(games);
  if (mc80Unplayed != null) {
    push('*', 'is-amber', formatNum(mc80Unplayed), 'Metacritic 80+ unplayed', null, { weight: W.moderate });
  }
  const gapGame = biggestCriticGapGame(games);
  if (gapGame) {
    push('^', 'is-rose', `${gapGame.g.name} · ${gapGame.gap} pts`, 'biggest critic gap', null, { weight: W.moderate });
  }

  const eaBacklog = earlyAccessBacklogCount(games, status);
  if (eaBacklog != null) {
    push('^', 'is-rose', formatNum(eaBacklog), 'early access backlog', null, { weight: W.moderate });
  }
  const dipBacklog = doubleDipBacklogCount(games, status);
  if (dipBacklog != null) {
    push('>', '', formatNum(dipBacklog), 'double-dip backlog', null, { weight: W.moderate });
  }
  const letterCov = letterCoverageShare(games);
  if (letterCov != null) {
    push('?', 'is-violet', `${Math.round(letterCov * 100)}%`, 'letter coverage %', null, { weight: W.friendly });
  }

  appendCreativeMarqueeChips(push, games, snap, METRIC_WEIGHT);

  // kojima metric — super-rare MGSV codec easter egg
  push('*', 'is-violet', '1', 'gay character: you, the player.', null, {
    weight: W.kojima,
    iconTitle: 'kojima',
  });

  noteMarqueeMetricKeys(items.map((it) => metricKeyForLabel(it.label)));
  const enabledItems = items.filter((it) => isMarqueeMetricEnabled(it.label));
  return spreadByFamily(applyMetricWeights(enabledItems), it => it.family, { wrap: true });
}

export function renderMarqueeHtml(items) {
  if (!items.length) return '';
  const itemHtml = items.map(it => {
    const chipTip = marqueeTip(it.label);
    const chipTitle = chipTip ? ` title="${escapeAttr(chipTip)}"` : '';
    const iconTip = it.iconTitle && !chipTip ? ` title="${escapeAttr(it.iconTitle)}"` : '';
    return `
    <span class="dash-marquee-item"${chipTitle}>
      <span class="dash-marquee-icon ${escapeAttr(it.iconCls || '')}"${iconTip}>${escapeHtml(it.glyph)}</span>
      <strong>${it.valueHtml}</strong>
      <span class="dash-marquee-label">${escapeHtml(it.label)}</span>
    </span>`;
  }).join('');
  return `
    <div class="dash-marquee" id="dashboardMarquee" aria-hidden="true">
      <div class="dash-marquee-track">${itemHtml}${itemHtml}</div>
    </div>`;
}

export function startInsightRotation(insights) {
  stopInsightRotation();
  const el = document.getElementById('dashboardInsight');
  const entries = normalizeInsightEntries(insights);
  if (!el || !entries.length) {
    if (el) {
      el.innerHTML = '';
      el.classList.remove('is-visible');
    }
    _lastInsights = [];
    return;
  }
  const weighted = filterInsightsByWeight(entries);
  let htmlList = weighted.map(e => e.html);
  htmlList = filterInsightsOneLine(el, htmlList);
  htmlList = spreadByFamily(htmlList, familyForInsight, { wrap: true });
  _lastInsights = htmlList;
  if (!htmlList.length) {
    el.innerHTML = '';
    el.classList.remove('is-visible');
    return;
  }
  _insightIndex = 0;
  const show = (i) => {
    el.classList.remove('is-visible');
    if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
    _insightFadeTimer = setTimeout(() => {
      const html = htmlList[i % htmlList.length];
      el.innerHTML = html;
      const tip = insightTip(html);
      el.title = tip || '';
      el.classList.add('is-visible');
    }, 250);
  };
  show(0);
  _insightTimer = setInterval(() => {
    _insightIndex += 1;
    show(_insightIndex);
  }, 6000);
}

if (typeof document !== 'undefined') {
  registerPausable({
    pause: stopInsightRotation,
    resume() {
      if (_lastInsights?.length) startInsightRotation(_lastInsights);
    },
  });
}
