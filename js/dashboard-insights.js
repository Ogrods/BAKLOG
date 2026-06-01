// Dashboard insight ticker / marquee (rotating stat lines + sticky marquee items).
// Extracted from dashboard.js as part of the dashboard module split.

import { state } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { gameKey, normalizeGame, hltbMain, ratingValue, hasEnoughReviews, itchIsGame } from './game-core.js';
import { gameGenresCanonical } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { getDealInfo, dealScore, isStealDeal, wishlistGamesWithDeals } from './deals.js';
import { DASH_STORE_LABELS } from './dashboard-shared.js';

let _insightTimer = null;
let _insightFadeTimer = null;
let _insightIndex = 0;

export function stopInsightRotation() {
  if (_insightTimer) clearInterval(_insightTimer);
  if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
  _insightTimer = null;
  _insightFadeTimer = null;
}

export function buildInsightPool(games) {
  const insights = [];
  const backlog = games.filter(g => getPersonal(g).status === 'backlog');

  const genreHrs = {};
  backlog.forEach(g => {
    gameGenresCanonical(g).forEach(gen => {
      genreHrs[gen] = (genreHrs[gen] || 0) + (hltbMain(g) || 0);
    });
  });
  const topGenre = Object.entries(genreHrs).sort((a, b) => b[1] - a[1])[0];
  if (topGenre && topGenre[1] > 0) {
    insights.push(`Biggest backlog: <strong>${escapeHtml(topGenre[0])}</strong> · ${escapeHtml(formatNum(Math.round(topGenre[1])))}h`);
  }

  const byPlay = [...games].filter(g => (g.playtime_minutes || 0) > 0).sort((a, b) => (b.playtime_minutes || 0) - (a.playtime_minutes || 0));
  if (byPlay[0]) {
    const hrs = Math.round((byPlay[0].playtime_minutes || 0) / 60);
    insights.push(`Most played: <strong>${escapeHtml(byPlay[0].name)}</strong> · ${escapeHtml(formatNum(hrs))}h`);
  }

  const hltbVals = backlog.map(g => hltbMain(g)).filter(h => h != null && h > 0);
  if (hltbVals.length) {
    const avg = Math.round(hltbVals.reduce((s, h) => s + h, 0) / hltbVals.length);
    insights.push(`Avg HLTB main: <strong>${escapeHtml(formatNum(avg))}h</strong>`);
  }

  const unplayed = backlog.filter(g => !(g.playtime_minutes || 0)).sort((a, b) => (hltbMain(b) || 0) - (hltbMain(a) || 0));
  if (unplayed[0]) {
    const h = hltbMain(unplayed[0]);
    insights.push(`Longest unplayed: <strong>${escapeHtml(unplayed[0].name)}</strong> · ${h != null ? escapeHtml(formatNum(Math.round(h))) + 'h' : '?'}`);
  }

  const deals = state.wishlistGames.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
  if (deals.length) {
    const top = [...deals].sort((a, b) => dealScore(b) - dealScore(a))[0];
    const cut = getDealInfo(top)?.cut || 0;
    insights.push(`Top deal: <strong>${escapeHtml(top.name)}</strong> · -${cut}%`);
  }

  const rated = games.filter(g => ratingValue(g) > 0);
  if (rated.length) {
    const avg = Math.round(rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length);
    insights.push(`Average review: <strong>${avg}%</strong>`);
  }

  const withDate = games
    .map(g => ({ g, d: g.added_at || '' }))
    .filter(x => x.d)
    .sort((a, b) => b.d.localeCompare(a.d));
  if (withDate[0]) {
    insights.push(`Newest add: <strong>${escapeHtml(withDate[0].g.name)}</strong>`);
  }

  const playedHrs = games.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  if (games.length) {
    const ratio = (playedHrs / games.length).toFixed(1);
    insights.push(`Hours per game: <strong>${ratio}h</strong>`);
  }

  return insights;
}

function formatDollarMarquee(n) {
  if (n == null || Number.isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n);
}

export function buildMarqueeItems(games) {
  const maxHrs = state.prefs.quickWinMaxHours || 15;
  const status = (g) => getPersonal(g).status || 'backlog';
  const playMin = (g) => g.playtime_minutes || 0;
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

  const items = [];
  const push = (glyph, iconCls, value, label) => {
    items.push({ glyph, iconCls, valueHtml: escapeHtml(String(value)), label });
  };

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

  if (total > 0) {
    const completionPct = Math.round((finished.length / total) * 100);
    push('+', 'is-emerald', `${completionPct}%`, 'library completion');
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

  const top90 = backlog.filter(g => rating(g) >= 90 && hasEnoughReviews(g)).length;
  if (top90) push('*', 'is-amber', formatNum(top90), '90%+ unplayed');
  const top80 = backlog.filter(g => rating(g) >= 80 && hasEnoughReviews(g)).length;
  if (top80) push('*', 'is-amber', formatNum(top80), '80%+ unplayed');
  const quickWins = backlog.filter(g => rating(g) >= 75 && (hltb(g) || 999) <= maxHrs).length;
  if (quickWins) push('>', '', formatNum(quickWins), 'quick wins ready');
  const hiddenGems = backlog.filter(g => rating(g) >= 90 && hasEnoughReviews(g) && !playMin(g)).length;
  if (hiddenGems) push('*', 'is-amber', formatNum(hiddenGems), 'hidden gems');

  const topRated = [...backlog].filter(g => rating(g) > 0 && hasEnoughReviews(g))
    .sort((a, b) => rating(b) - rating(a))[0];
  if (topRated) push('*', 'is-amber', `${topRated.name} · ${rating(topRated)}%`, 'top-rated unplayed');

  const stealsCount = wl.filter(isStealDeal).length;
  if (stealsCount) push('+', 'is-emerald', formatNum(stealsCount), 'steal-tier deals');
  if (onSale.length) push('+', 'is-emerald', formatNum(onSale.length), 'on sale now');
  if (onSale.length) {
    const top = [...onSale].sort((a, b) => dealScore(b) - dealScore(a))[0];
    const cut = getDealInfo(top)?.cut || 0;
    push('+', 'is-emerald', `${top.name} -${cut}%`, 'top deal');
    const cuts = onSale.map(g => getDealInfo(g)?.cut || 0).filter(x => x > 0);
    if (cuts.length) {
      const avgCut = Math.round(cuts.reduce((s, c2) => s + c2, 0) / cuts.length);
      push('+', 'is-emerald', `${avgCut}%`, 'avg discount');
      const steepest = Math.max(...cuts);
      push('+', 'is-emerald', `-${steepest}%`, 'steepest cut');
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

  let libraryMsrp = 0;
  for (const g of games) {
    const d = getDealInfo(g);
    if (d?.regular != null) libraryMsrp += d.regular;
  }
  if (libraryMsrp > 0) push('#', 'is-violet', formatDollarMarquee(libraryMsrp), 'library at MSRP');

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

  if (stores > 0 && total > 0) {
    const avgPerStore = Math.round(total / stores);
    push('~', 'is-amber', formatNum(avgPerStore), 'games per store avg');
  }

  return items;
}

export function renderMarqueeHtml(items) {
  if (!items.length) return '';
  const itemHtml = items.map(it => `
    <span class="dash-marquee-item">
      <span class="dash-marquee-icon ${escapeAttr(it.iconCls || '')}">${escapeHtml(it.glyph)}</span>
      <strong>${it.valueHtml}</strong>
      <span class="dash-marquee-label">${escapeHtml(it.label)}</span>
    </span>`).join('');
  return `
    <div class="dash-marquee" id="dashboardMarquee" aria-hidden="true">
      <div class="dash-marquee-track">${itemHtml}${itemHtml}</div>
    </div>`;
}

export function startInsightRotation(insights) {
  stopInsightRotation();
  const el = document.getElementById('dashboardInsight');
  if (!el || !insights.length) {
    if (el) {
      el.innerHTML = '';
      el.classList.remove('is-visible');
    }
    return;
  }
  _insightIndex = 0;
  const show = (i) => {
    el.classList.remove('is-visible');
    if (_insightFadeTimer) clearTimeout(_insightFadeTimer);
    _insightFadeTimer = setTimeout(() => {
      el.innerHTML = insights[i % insights.length];
      el.classList.add('is-visible');
    }, 250);
  };
  show(0);
  _insightTimer = setInterval(() => {
    _insightIndex += 1;
    show(_insightIndex);
  }, 6000);
}
