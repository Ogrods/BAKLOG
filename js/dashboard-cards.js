// Dashboard panel renderers: coop spotlight, picks-versus, wishlist stats, itch recap.
// Extracted from dashboard.js as part of the dashboard module split.

import { state, STATUS_CHIP_DEFS } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { gameKey, normalizeGame, hltbMain, ratingValue, hasEnoughReviews, coverFallbackFor, libraryCoverFor, sanitizeCoverUrl, itchIsGame, chipStatusKey, combinedPlaytime } from './game-core.js';
import { gameGenresCanonical } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { wishlistGamesWithDeals, dealHeroCardHtml, dealHeroEmptyHtml, dealSaleScoreboardCardHtml, dealStealsCardHtml, getDealInfo, dealScore, isStealDeal } from './deals.js';
import { focusGame } from './table-ui.js';
import { DASH_STORE_LABELS, DASH_STORE_COLORS, ITCH_CLASS_LABELS } from './dashboard-shared.js';
// Itch click routing uses dashDrillItchGenre from the drilldown module.
// dashboard-drilldown does NOT import this module; the cycle stays one-way.
import { dashDrillItchGenre } from './dashboard-drilldown.js';
import { dashboardCharts } from './dashboard-charts.js';

let itchHeroIndex = Math.floor(Math.random() * 10);

export function renderDashboardCoopSpotlight(games) {
  const el = document.getElementById("dashboardCoopSpotlight");
  if (!el) return;
  const coopGames = games.filter(g => g.coop_online || g.coop_local);
  const onlineGames = games.filter(g => g.coop_online);
  const localGames = games.filter(g => g.coop_local);
  const bothGames = games.filter(g => g.coop_online && g.coop_local);

  if (coopGames.length === 0) {
    el.innerHTML = `
      <div class="coop-spotlight-header">
        <div class="coop-spotlight-title">Co-op spotlight</div>
      </div>
      <div class="coop-empty">
        No co-op games detected yet. Connect Steam and run the games fetcher (Fetcher health) — co-op flags come from Steam store categories, or wait until you own a title tagged <em>Online Co-op</em> or <em>Shared/Split Screen Co-op</em>.
      </div>`;
    return;
  }

  const sideHtml = (list, { sideClass, title, drillArgs }) => {
    const backlog = list.filter(g => getPersonal(g).status === "backlog").length;
    const finished = list.filter(g => getPersonal(g).status === "finished").length;
    const hltbValues = list.map(g => hltbMain(g)).filter(h => h != null && h > 0);
    const avgHltb = hltbValues.length
      ? Math.round(hltbValues.reduce((s, h) => s + h, 0) / hltbValues.length)
      : null;
    const failedCoop = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
    const picks = list
      .filter(g => getPersonal(g).status !== "finished" && combinedPlaytime(g) === 0)
      .filter(g => ratingValue(g) > 0 && hasEnoughReviews(g))
      .filter(g => !!(g.library_image || g.header_image) && !failedCoop.has(gameKey(g)))
      .sort((a, b) => ratingValue(b) - ratingValue(a))
      .slice(0, 3);
    const picksHtml = picks.length
      ? picks.map(g => {
          const cover = libraryCoverFor(g);
          const key = gameKey(g);
          return `<button type="button" class="coop-pick-row" data-action="coop-pick-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library">
            <img class="coop-pick-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
            <span class="coop-pick-name">${escapeHtml(g.name)}</span>
            <span class="coop-pick-rating">${ratingValue(g)}%</span>
          </button>`;
        }).join("")
      : '<div class="coop-picks-empty">All started or finished — nothing unplayed.</div>';
    const drillJson = escapeAttr(JSON.stringify(drillArgs));
    return `
      <div class="coop-side ${sideClass}" role="button" tabindex="0" data-action="coop-drill" data-drill="${drillJson}" title="Filter the library by ${escapeAttr(title)}">
        <div class="coop-side-header">
          <div class="coop-side-title-row">
            <span class="coop-side-title">${escapeHtml(title)}</span>
          </div>
          <span class="coop-side-count">${list.length}</span>
        </div>
        <div class="coop-side-stats">
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Backlog</div>
            <div class="coop-side-stat-value ${backlog ? "" : "coop-side-stat-muted"}">${backlog}</div>
          </div>
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Finished</div>
            <div class="coop-side-stat-value ${finished ? "" : "coop-side-stat-muted"}">${finished}</div>
          </div>
          <div class="coop-side-stat">
            <div class="coop-side-stat-label">Avg HLTB</div>
            <div class="coop-side-stat-value ${avgHltb != null ? "" : "coop-side-stat-muted"}">${avgHltb != null ? avgHltb + "h" : "—"}</div>
          </div>
        </div>
        <div>
          <div class="coop-side-picks-label">Top unplayed picks</div>
          <div class="coop-side-picks-list">${picksHtml}</div>
        </div>
      </div>`;
  };

  const anyDrill = escapeAttr(JSON.stringify({ any: true }));
  const bothDrill = escapeAttr(JSON.stringify({ online: true, local: true }));
  const connector = `
    <div class="coop-connector">
      <button type="button" class="coop-connector-stat" data-action="coop-drill" data-drill="${anyDrill}" title="Filter the library by any game with an online or couch co-op flag">
        <div class="coop-connector-label">Total co-op</div>
        <div class="coop-connector-value">${coopGames.length}</div>
        <div class="coop-connector-sub">of ${games.length} games</div>
      </button>
      <div class="coop-connector-divider" aria-hidden="true"></div>
      <button type="button" class="coop-connector-stat" data-action="coop-drill" data-drill="${bothDrill}" title="Filter the library by games that support both online and couch co-op">
        <div class="coop-connector-label">Both flavors</div>
        <div class="coop-connector-value">${bothGames.length}</div>
        <div class="coop-connector-sub">online + couch</div>
      </button>
    </div>`;

  el.innerHTML = `
    <div class="coop-spotlight-header">
      <div class="coop-spotlight-title">Co-op spotlight</div>
      <div class="coop-spotlight-sub">Steam co-op signal · click a side to filter the library</div>
    </div>
    <div class="coop-versus">
      ${sideHtml(onlineGames, { sideClass: "coop-side-online", title: "Online co-op", drillArgs: { online: true, local: false } })}
      ${connector}
      ${sideHtml(localGames, { sideClass: "coop-side-local", title: "Couch co-op", drillArgs: { online: false, local: true } })}
    </div>
  `;
}

export function applyItchVisibility() {
  const row = document.getElementById("dashboardPicksRow");
  const card = document.getElementById("dashItchCard");
  const has = (state.itchGames || []).length > 0;
  row?.classList.toggle("no-itch", !has);
  card?.classList.toggle("hidden", !has);
}

export function renderDashboardPicksVersus(games) {
  const failed = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const hasCover = g => !!(g.library_image || g.header_image) && !failed.has(gameKey(g));

  const ratedAll = games
    .filter(g => getPersonal(g).status === "backlog"
      && ratingValue(g) > 0
      && hasEnoughReviews(g)
      && hasCover(g))
    .sort((a, b) => ratingValue(b) - ratingValue(a));

  const fastMax = state.prefs.quickWinMaxHours || 15;
  const fastAll = games
    .filter(g => getPersonal(g).status === "backlog"
      && (hltbMain(g) || 999) <= fastMax
      && ratingValue(g) >= 80
      && hasCover(g))
    .sort((a, b) => {
      const ha = hltbMain(a) || 999;
      const hb = hltbMain(b) || 999;
      if (ha !== hb) return ha - hb;
      return ratingValue(b) - ratingValue(a);
    });

  const balanced = Math.min(ratedAll.length, fastAll.length, 10);
  const sliceCount = balanced > 0 ? balanced : Math.min(Math.max(ratedAll.length, fastAll.length), 10);
  const rated = ratedAll.slice(0, sliceCount);
  const fast = fastAll.slice(0, sliceCount);

  const ratedKeys = new Set(rated.map(g => gameKey(g)));
  const fastKeys = new Set(fast.map(g => gameKey(g)));
  const crossKeys = new Set([...ratedKeys].filter(k => fastKeys.has(k)));

  const row = (g, scoreFn, accentCls) => {
    const cover = libraryCoverFor(g);
    const key = gameKey(g);
    const isCross = crossKeys.has(key);
    const star = isCross ? ' <span class="dash-versus-star" title="Also in the other list">*</span>' : "";
    return `<button type="button" class="dash-list-row dash-versus-row ${accentCls}${isCross ? " is-cross" : ""}" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library"><img class="dash-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" /><span class="truncate flex-1">${escapeHtml(g.name)}${star}</span><span class="text-slate-400">${escapeHtml(scoreFn(g))}</span></button>`;
  };

  const empty = '<p class="text-xs text-slate-400 italic">No matches yet.</p>';
  const ratedEl = document.getElementById("dashVersusRated");
  const fastEl = document.getElementById("dashVersusFast");
  if (ratedEl) {
    ratedEl.innerHTML = rated.length
      ? rated.map(g => row(g, gg => `${ratingValue(gg)}%`, "dash-versus-row--rated")).join("")
      : empty;
  }
  if (fastEl) {
    fastEl.innerHTML = fast.length
      ? fast.map(g => row(g, gg => `${hltbMain(gg) || "?"}h`, "dash-versus-row--fast")).join("")
      : empty;
  }

  const badge = document.getElementById("dashVersusBadge");
  if (badge) {
    if (crossKeys.size) {
      const names = [...crossKeys]
        .map(k => (rated.find(g => gameKey(g) === k) || fast.find(g => gameKey(g) === k))?.name || "")
        .filter(Boolean)
        .join(", ");
      badge.textContent = `${crossKeys.size} cross-list pick${crossKeys.size === 1 ? "" : "s"}`;
      badge.title = names;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
      badge.textContent = "";
      badge.removeAttribute("title");
    }
  }

  applyItchVisibility();
}

export function buildWishlistStatsHtml() {
  const wl = state.wishlistGames;
  if (!wl.length) {
    return [
      dealHeroEmptyHtml({ noWishlist: true }),
      dealSaleScoreboardCardHtml({
        onSaleCount: 0,
        totalCount: 0,
        avgCut: 0,
        bestCut: 0,
        bestCutGame: "",
        hasPricing: false,
        cuts: [],
      }),
      dealStealsCardHtml([]),
    ].join("");
  }

  const onSale = wl.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
  const withDeals = wishlistGamesWithDeals(wl);
  const topDeal = withDeals.length
    ? [...withDeals].sort((a, b) => dealScore(b) - dealScore(a))[0]
    : null;

  let hasPricing = false;
  let bestCut = 0;
  let bestCutGame = "";
  let cutSum = 0;
  const cuts = [];
  for (const g of wl) {
    const d = getDealInfo(g);
    if (!d) continue;
    if (d.price != null || d.regular != null || d.cut) hasPricing = true;
    const cut = d.cut || 0;
    if (cut > 0) {
      cutSum += cut;
      cuts.push(cut);
      if (cut > bestCut) {
        bestCut = cut;
        bestCutGame = g.name || "";
      }
    }
  }
  const avgCut = onSale.length ? Math.round(cutSum / onSale.length) : 0;
  const steals = wl.filter(isStealDeal);

  return [
    topDeal ? dealHeroCardHtml(topDeal) : dealHeroEmptyHtml(),
    dealSaleScoreboardCardHtml({
      onSaleCount: onSale.length,
      totalCount: wl.length,
      avgCut,
      bestCut,
      bestCutGame,
      hasPricing,
      cuts,
    }),
    dealStealsCardHtml(steals),
  ].join("");
}

export function renderDashboardWishlistStats() {
  // Re-used by both the dashboard mega-grid and the standalone wishlist deal
  // radar shown above the table on the Wishlist view. Iterating over all
  // matching targets keeps a single source of truth for the markup + math.
  const targets = document.querySelectorAll(".dash-wishlist-stats-target");
  if (!targets.length) return;
  const html = buildWishlistStatsHtml();
  for (const el of targets) el.innerHTML = html;
}

function itchBreakdownRows(entries, fillClass, action) {
  const max = Math.max(...entries.map(([, n]) => n), 1);
  return entries.map(([value, count, label]) => {
    const pct = Math.round((count / max) * 100);
    const display = label || value;
    const tag = action ? "button" : "div";
    const attrs = action
      ? ` type="button" data-action="${escapeAttr(action)}" data-value="${escapeAttr(value)}"`
      : "";
    return `<${tag} class="itch-breakdown-row${action ? "" : " itch-breakdown-row-static"}"${attrs} title="${escapeAttr(display)}: ${formatNum(count)}">
      <span class="itch-breakdown-name">${escapeHtml(display)}</span>
      <span class="itch-breakdown-bar" aria-hidden="true"><span class="itch-breakdown-fill ${fillClass}" style="width:${pct}%"></span></span>
      <span class="itch-breakdown-count">${formatNum(count)}</span>
    </${tag}>`;
  }).join("");
}

function renderItchHeroHtml(candidates) {
  if (!candidates.length) {
    return `<div class="itch-hero">
      <div class="itch-hero-label"><span>Featured unplayed pick</span></div>
      <div class="itch-hero-empty">No rated picks yet — run the itch ratings fetcher to backfill scores.</div>
    </div>`;
  }
  const idx = ((itchHeroIndex % candidates.length) + candidates.length) % candidates.length;
  const g = candidates[idx];
  const cover = libraryCoverFor(g);
  const fb = coverFallbackFor(g);
  const key = gameKey(g);
  const rating = ratingValue(g);
  const hltb = hltbMain(g);
  const metaParts = [];
  if (g.publisher) metaParts.push(`by ${escapeHtml(g.publisher)}`);
  if (hltb) metaParts.push(`~${hltb}h`);
  const metaHtml = metaParts.length ? `<div class="itch-hero-meta">${metaParts.join(" · ")}</div>` : "";
  const desc = g.short_text ? `<p class="itch-hero-desc">${escapeHtml(g.short_text)}</p>` : "";
  const tags = gameGenresCanonical(g).slice(0, 3);
  const tagsHtml = tags.length
    ? `<div class="itch-hero-tags">${tags.map(t => `<span class="itch-hero-tag">${escapeHtml(t)}</span>`).join("")}</div>`
    : "";
  const shuffleBtn = candidates.length > 1
    ? `<button type="button" class="itch-hero-shuffle" data-action="itch-hero-shuffle" title="Cycle picks">↻</button>`
    : "";
  return `<div class="itch-hero">
    <div class="itch-hero-label">
      <span>Featured unplayed pick</span>
      ${shuffleBtn}
    </div>
    <button type="button" class="itch-hero-card" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} on itch.io">
      <img class="itch-hero-cover" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(fb)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
      <div class="itch-hero-body">
        <div class="itch-hero-head">
          <span class="itch-hero-name">${escapeHtml(g.name)}</span>
          <span class="itch-hero-rating">${rating}%</span>
        </div>
        ${metaHtml}
        ${desc}
        ${tagsHtml}
      </div>
    </button>
  </div>`;
}

function bindItchRecapClick() {
  const el = document.getElementById("dashItchRecap");
  if (!el || el.dataset.itchBound) return;
  el.dataset.itchBound = "1";
  el.addEventListener("click", e => {
    const shuffle = e.target.closest('[data-action="itch-hero-shuffle"]');
    if (shuffle) {
      e.preventDefault();
      e.stopPropagation();
      itchHeroIndex += 1;
      renderDashboardItchRecap();
      return;
    }
    const genreRow = e.target.closest('[data-action="itch-drill-genre"]');
    if (genreRow?.dataset.value) {
      e.preventDefault();
      e.stopPropagation();
      dashDrillItchGenre(genreRow.dataset.value);
    }
  });
}

export function renderDashboardItchRecap() {
  const el = document.getElementById("dashItchRecap");
  if (!el) return;
  bindItchRecapClick();
  if (dashboardCharts.chartItchStatus) {
    dashboardCharts.chartItchStatus.destroy();
    delete dashboardCharts.chartItchStatus;
  }

  const total = state.itchGames.length;
  applyItchVisibility();
  if (!total) {
    el.innerHTML = `<p class="text-sm text-slate-400">No itch.io data yet — add your itch.io key on Connections and run the itch fetcher.</p>`;
    return;
  }

  const gamesOnly = state.itchGames.filter(itchIsGame);
  const videogames = gamesOnly.length;
  const rated = gamesOnly.filter(g => ratingValue(g) > 0).length;
  const unrated = videogames - rated;
  const nonGames = total - videogames;
  const backlogged = gamesOnly.filter(g => getPersonal(g).status === "backlog").length;

  const segments = [
    { id: "rated", label: "Rated", count: rated },
    { id: "unrated", label: "Unrated", count: unrated },
    { id: "non", label: "Non-game", count: nonGames },
  ];
  const segSum = segments.reduce((a, s) => a + s.count, 0);
  const segHtml = segSum
    ? `<div class="itch-distribution">
        <div class="itch-distribution-label">Library composition</div>
        <div class="sale-distribution-bar" role="img" aria-label="itch.io library composition">
          ${segments.map(s => s.count
            ? `<span class="sale-distribution-seg itch-seg-${s.id}" style="flex: ${s.count};" title="${s.label}: ${formatNum(s.count)}"></span>`
            : ""
          ).join("")}
        </div>
        <div class="sale-distribution-legend">
          ${segments.map(s => `<span class="sale-distribution-tick ${s.count ? "" : "sale-distribution-tick-empty"}" title="${s.label}: ${formatNum(s.count)}">
            <span class="sale-distribution-swatch itch-seg-${s.id}"></span>
            <span class="sale-distribution-tick-label">${s.label}</span>
            <span class="sale-distribution-tick-count">${formatNum(s.count)}</span>
          </span>`).join("")}
        </div>
      </div>`
    : "";

  const failedItch = (typeof window !== 'undefined' && window.__dashFailedCovers) || new Set();
  const heroCandidates = gamesOnly
    .filter(g => getPersonal(g).status !== "finished" && combinedPlaytime(g) === 0)
    .filter(g => ratingValue(g) >= 90 && hasEnoughReviews(g))
    .filter(g => !!(g.library_image || g.header_image) && !failedItch.has(gameKey(g)))
    .sort((a, b) => ratingValue(b) - ratingValue(a))
    .slice(0, 10);
  if (heroCandidates.length) itchHeroIndex %= heroCandidates.length;
  else itchHeroIndex = 0;
  const heroHtml = videogames ? renderItchHeroHtml(heroCandidates) : "";

  const classCounts = {};
  state.itchGames.forEach(g => {
    const cls = g.classification || "game";
    classCounts[cls] = (classCounts[cls] || 0) + 1;
  });
  const classEntries = Object.entries(classCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([cls, count]) => [cls, count, ITCH_CLASS_LABELS[cls] || cls]);
  const classHtml = classEntries.length
    ? `<div class="itch-breakdown">
        <div class="itch-distribution-label">What's in your library</div>
        <div class="itch-breakdown-list">${itchBreakdownRows(classEntries, "itch-bar-class", null)}</div>
      </div>`
    : "";

  const genreCounts = {};
  gamesOnly.forEach(g => {
    gameGenresCanonical(g).forEach(genre => {
      genreCounts[genre] = (genreCounts[genre] || 0) + 1;
    });
  });
  const genreEntries = Object.entries(genreCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([genre, count]) => [genre, count, genre]);
  const genreHtml = genreEntries.length
    ? `<div class="itch-breakdown">
        <div class="itch-distribution-label">Top itch genres</div>
        <div class="itch-breakdown-list">${itchBreakdownRows(genreEntries, "itch-bar-genre", "itch-drill-genre")}</div>
      </div>`
    : "";

  el.innerHTML = `
    <div class="sale-scoreboard">
      <div class="sale-stat">
        <div class="sale-stat-label">Videogames</div>
        <div class="sale-stat-value">${formatNum(videogames)}<span class="sale-stat-suffix"> / ${formatNum(total)}</span></div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Backlog</div>
        <div class="sale-stat-value ${backlogged ? "" : "sale-stat-muted"}">${backlogged ? formatNum(backlogged) : "—"}</div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Rated</div>
        <div class="sale-stat-value ${rated ? "" : "sale-stat-muted"}">${rated ? formatNum(rated) : "—"}</div>
      </div>
    </div>
    ${segHtml}
    ${heroHtml}
    ${classHtml}
    ${genreHtml}
    <div class="itch-footer">
      <button type="button" class="summary-jump-chip px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs border border-slate-600 cursor-pointer" data-jump-view="itch">Open itch.io tab →</button>
    </div>`;
}
