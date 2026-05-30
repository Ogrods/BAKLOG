import { state, STATUS_CHIP_DEFS, QUICK_WIN_MIN_RATING } from './state.js';
import { escapeAttr, escapeHtml, formatNum } from './dom-util.js';
import { renderDashboardFetcherHealth } from './fetcher-health.js';

let ctx = {};

export function initDashboard(appContext) {
  ctx = appContext;
}

function c(name) {
  const fn = ctx[name];
  if (!fn) throw new Error(`dashboard context missing: ${name}`);
  return fn;
}

const dashboardCharts = {};
let _dashboardRenderTimer = null;
let itchHeroIndex = Math.floor(Math.random() * 10);

const ITCH_CLASS_LABELS = {
  game: "Games",
  tool: "Tools",
  assets: "Assets",
  comic: "Comics",
  book: "Books",
  soundtrack: "Soundtracks",
  physical_game: "Physical games",
  other: "Other",
};
const DASH_STORE_COLORS = {
  steam: "#ea580c", gog: "#6d28d9", psn: "#003791", epic: "#64748b",
  amazon: "#c2410c", xbox: "#107C10", battlenet: "#148EFF", ubisoft: "#FFD200",
  nintendo: "#E60012", itch: "#fa5c5c", other: "#94a3b8", manual: "#64748b",
};
const DASH_STATUS_COLORS = {
  backlog: "#ef4444", next: "#38bdf8", playing: "#facc15", unfinished: "#f97316",
  live: "#ec4899", finished: "#22c55e", skip: "#475569", __none__: "#334155",
};
const DASH_REVIEW_COLORS = {
  "Overwhelmingly Positive": "#22c55e",
  "Very Positive": "#34d399",
  "Mostly Positive": "#86efac",
  "Mixed": "#fbbf24",
  "Mostly Negative": "#f97316",
  "Negative": "#ef4444",
  "Unreviewed": "#475569",
};
const DASH_STORE_LABELS = {
  steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic", amazon: "Amazon",
  xbox: "Xbox", battlenet: "Battle.net", ubisoft: "Ubisoft", nintendo: "Nintendo",
  itch: "itch.io", other: "Other", manual: "Manual",
};

export function destroyDashboardCharts() {
  Object.values(dashboardCharts).forEach(c => { try { c.destroy(); } catch (_) {} });
  Object.keys(dashboardCharts).forEach(k => delete dashboardCharts[k]);
}

export function dashboardLibraryGames() {
  return state.allGames.filter(g => !state.crossStoreHiddenKeys.has(c('gameKey')(g)));
}

function dashChartOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { labels: { color: "#ffffff", boxWidth: 12 } } },
    ...extra,
  };
}

function setDashboardChart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas || typeof Chart === "undefined") return;
  if (dashboardCharts[id]) {
    dashboardCharts[id].destroy();
    delete dashboardCharts[id];
  }
  dashboardCharts[id] = new Chart(canvas, config);
}

const ERA_BANDS = [
  { start: 1990, end: 1999, label: "'90s", fill: "rgba(251, 191, 36, 0.06)", textColor: "rgba(251, 191, 36, 0.55)" },
  { start: 2000, end: 2009, label: "'00s", fill: "rgba(52, 211, 153, 0.06)", textColor: "rgba(52, 211, 153, 0.55)" },
  { start: 2010, end: 2019, label: "'10s", fill: "rgba(56, 189, 248, 0.07)", textColor: "rgba(56, 189, 248, 0.6)" },
  { start: 2020, end: 2099, label: "'20s", fill: "rgba(168, 85, 247, 0.08)", textColor: "rgba(168, 85, 247, 0.65)" },
];

function makeEraBandsPlugin(yearLabels) {
  return {
    id: "eraBands",
    beforeDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const xs = scales.x;
      if (!xs || yearLabels.length === 0) return;
      const labelToIdx = new Map(yearLabels.map((y, i) => [y, i]));
      const halfBar = yearLabels.length > 1
        ? Math.abs(xs.getPixelForTick(1) - xs.getPixelForTick(0)) / 2
        : (chartArea.right - chartArea.left) / 2;
      ctx.save();
      ERA_BANDS.forEach(era => {
        let firstIdx = -1, lastIdx = -1;
        for (let i = 0; i < yearLabels.length; i++) {
          const y = +yearLabels[i];
          if (y >= era.start && y <= era.end) {
            if (firstIdx === -1) firstIdx = i;
            lastIdx = i;
          }
        }
        if (firstIdx === -1) return;
        const left = Math.max(chartArea.left, xs.getPixelForTick(firstIdx) - halfBar);
        const right = Math.min(chartArea.right, xs.getPixelForTick(lastIdx) + halfBar);
        if (right <= left) return;
        ctx.fillStyle = era.fill;
        ctx.fillRect(left, chartArea.top, right - left, chartArea.bottom - chartArea.top);
        if (right - left > 36) {
          ctx.fillStyle = era.textColor;
          ctx.font = "600 10px system-ui, sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillText(era.label, (left + right) / 2, chartArea.top + 4);
        }
      });
      ctx.restore();
    },
  };
}

function makeBarEndLabelsPlugin(getLabelForBarIndex) {
  return {
    id: "barEndLabels",
    afterDatasetsDraw(chart) {
      const { ctx, data } = chart;
      const lastIdx = data.datasets.length - 1;
      const meta = chart.getDatasetMeta(lastIdx);
      if (!meta || !meta.data) return;
      ctx.save();
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "600 11px system-ui, sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      meta.data.forEach((bar, i) => {
        const text = getLabelForBarIndex(i);
        if (text == null || text === "") return;
        ctx.fillText(String(text), bar.x + 6, bar.y);
      });
      ctx.restore();
    },
  };
}

function dashDrillStore(store) {
  state.prefs.storeFilter = store || "";
  c('savePrefs')();
  document.getElementById("statusFilter").value = "";
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillStatus(status) {
  document.getElementById("statusFilter").value = status || "";
  state.prefs.storeFilter = "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillStoreStatus(store, status) {
  state.prefs.storeFilter = store || "";
  document.getElementById("statusFilter").value = status || "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillGenre(genre) {
  if (!state.prefs.genreFilters.includes(genre)) state.prefs.genreFilters.push(genre);
  c('savePrefs')();
  c('switchView')("library");
  c('renderGenreChips')();
  c('refreshFilterUI')();
}

function dashDrillItchGenre(genre) {
  if (!state.prefs.genreFilters.includes(genre)) state.prefs.genreFilters.push(genre);
  c('savePrefs')();
  c('switchView')("itch");
  c('renderGenreChips')();
  c('refreshFilterUI')();
}

function dashDrillItchClass(cls) {
  state.prefs.itchClassification = cls || "";
  c('savePrefs')();
  c('switchView')("itch");
  c('refreshFilterUI')();
}

function dashDrillHltbBucket(bucketIndex) {
  const maxByBucket = [2, 5, 10, 20, 40, 200];
  const maxH = maxByBucket[bucketIndex] ?? 200;
  const maxEl = document.getElementById("maxHours");
  const maxVal = document.getElementById("maxHoursVal");
  if (maxEl) maxEl.value = String(maxH);
  if (maxVal) maxVal.textContent = maxH >= 200 ? "200+" : String(maxH);
  document.getElementById("statusFilter").value = "backlog";
  state.prefs.storeFilter = "";
  c('savePrefs')();
  c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
}

function dashDrillReleaseYear(year) {
  state.prefs.releaseYearFilter = year || "";
  c('savePrefs')();
  c('switchView')("library");
  c('refreshFilterUI')();
}

function dashDrillReviewTier(tier) {
  state.prefs.reviewTierFilter = tier || "";
  c('savePrefs')();
  c('switchView')("library");
  c('refreshFilterUI')();
}

export function pickPlayTonight(games) {
  const pool = games.filter(g => {
    if (c('getPersonal')(g).status !== "backlog") return false;
    if ((g.playtime_minutes || 0) > 0) return false;
    return true;
  });
  if (!pool.length) return null;
  const moods = [
    () => pool.filter(g => (c('hltbMain')(g) || 999) <= (state.prefs.quickWinMaxHours || 15) && c('ratingValue')(g) >= QUICK_WIN_MIN_RATING),
    () => pool.filter(g => g.coop_online || g.coop_local),
    () => pool.filter(g => c('ratingValue')(g) > 0 && c('ratingValue')(g) < 75 && c('hasEnoughReviews')(g)),
    () => pool.filter(g => (c('hltbMain')(g) || 0) >= 20),
  ];
  const mood = moods[Math.floor(Math.random() * moods.length)]();
  const candidates = mood.length ? mood : pool;
  return candidates[Math.floor(Math.random() * candidates.length)];
}

function itchBreakdownRows(entries, fillClass, action) {
  const max = Math.max(...entries.map(([, n]) => n), 1);
  return entries.map(([value, count, label]) => {
    const pct = Math.round((count / max) * 100);
    const display = label || value;
    return `<button type="button" class="itch-breakdown-row" data-action="${escapeAttr(action)}" data-value="${escapeAttr(value)}" title="${escapeAttr(display)}: ${formatNum(count)}">
      <span class="itch-breakdown-name">${escapeHtml(display)}</span>
      <span class="itch-breakdown-bar" aria-hidden="true"><span class="itch-breakdown-fill ${fillClass}" style="width:${pct}%"></span></span>
      <span class="itch-breakdown-count">${formatNum(count)}</span>
    </button>`;
  }).join("");
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
      return;
    }
    const classRow = e.target.closest('[data-action="itch-drill-class"]');
    if (classRow?.dataset.value) {
      e.preventDefault();
      e.stopPropagation();
      dashDrillItchClass(classRow.dataset.value);
    }
  });
}

export function dashDrillCoop({ online = false, local = false } = {}) {
  const onlineEl = document.getElementById("coopOnlineOnly");
  const localEl = document.getElementById("coopLocalOnly");
  if (onlineEl) onlineEl.checked = !!online;
  if (localEl) localEl.checked = !!local;
  document.getElementById("statusFilter").value = "";
  state.prefs.storeFilter = "";
  c('savePrefs')();
  c('invalidateTableCache')();
  if (state.activeView !== "library") c('switchView')("library");
  c('renderStoreChips')();
  c('refreshFilterUI')();
  c('renderTable')();
}

function renderDashboardCoopSpotlight(games) {
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
        No co-op games detected yet. Co-op flags come from Steam store categories — run <code>fetch_games.py</code> to refresh, or wait until you own a Steam title tagged <em>Online Co-op</em> or <em>Shared/Split Screen Co-op</em>.
      </div>`;
    return;
  }

  const sideHtml = (list, { sideClass, title, drillArgs }) => {
    const backlog = list.filter(g => c('getPersonal')(g).status === "backlog").length;
    const finished = list.filter(g => c('getPersonal')(g).status === "finished").length;
    const hltbValues = list.map(g => c('hltbMain')(g)).filter(h => h != null && h > 0);
    const avgHltb = hltbValues.length
      ? Math.round(hltbValues.reduce((s, h) => s + h, 0) / hltbValues.length)
      : null;
    const picks = list
      .filter(g => c('getPersonal')(g).status !== "finished" && (g.playtime_minutes || 0) === 0)
      .filter(g => c('ratingValue')(g) > 0 && c('hasEnoughReviews')(g))
      .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
      .slice(0, 3);
    const picksHtml = picks.length
      ? picks.map(g => {
          const cover = g.library_image || c('coverFallbackFor')(g);
          const key = c('gameKey')(g);
          return `<button type="button" class="coop-pick-row" data-action="coop-pick-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library">
            <img class="coop-pick-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
            <span class="coop-pick-name">${escapeHtml(g.name)}</span>
            <span class="coop-pick-rating">${c('ratingValue')(g)}%</span>
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

  const bothDrill = escapeAttr(JSON.stringify({ online: true, local: true }));
  const connector = `
    <div class="coop-connector">
      <div class="coop-connector-stat" title="Total games with any co-op flag">
        <div class="coop-connector-label">Total co-op</div>
        <div class="coop-connector-value">${coopGames.length}</div>
        <div class="coop-connector-sub">of ${games.length} games</div>
      </div>
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
function renderDashboardKPIs(games) {
  const backlog = games.filter(g => c('getPersonal')(g).status === "backlog");
  const backlogHrs = backlog.reduce((s, g) => s + (c('hltbMain')(g) || 0), 0);
  const playedHrs = games.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  const nonSkip = games.filter(g => c('getPersonal')(g).status !== "skip");
  const finished = games.filter(g => c('getPersonal')(g).status === "finished").length;
  const completion = nonSkip.length ? Math.round((finished / nonSkip.length) * 100) : 0;
  const rated = games.filter(g => c('ratingValue')(g) > 0);
  const avgRating = rated.length ? Math.round(rated.reduce((s, g) => s + c('ratingValue')(g), 0) / rated.length) : "—";
  const wlDeals = state.wishlistGames.filter(g => { const d = c('getDealInfo')(g); return d && (d.cut || 0) > 0; }).length;
  const itchGameCount = state.itchGames.filter(c('itchIsGame')).length;
  const stores = new Set(games.map(g => c('normalizeGame')(g).store)).size;
  const wishlistCount = state.wishlistGames.length;
  const kpis = [
    { label: "Library games", value: formatNum(games.length) },
    { label: "Backlog hours", value: `${formatNum(Math.round(backlogHrs))}h` },
    { label: "Played hours", value: `${formatNum(Math.round(playedHrs))}h` },
    { label: "Completion", value: `${completion}%` },
    { label: "Avg review", value: avgRating === "—" ? "—" : `${avgRating}%` },
    { label: "Wishlist deals", value: formatNum(wlDeals) },
    { label: "Itch games", value: formatNum(itchGameCount) },
    { label: "Stores", value: stores },
    { label: "Wishlist", value: formatNum(wishlistCount) },
  ];
  document.getElementById("dashboardKpis").innerHTML = kpis.map(k => `
    <div class="dash-kpi">
      <div class="dash-kpi-label">${escapeHtml(k.label)}</div>
      <div class="dash-kpi-value">${escapeHtml(String(k.value))}</div>
    </div>`).join("");
  const pt = document.getElementById("dashboardPlayTonight");
  if (pt) {
    pt.innerHTML = `<button type="button" id="playTonightBtn" class="px-3 py-1.5 rounded bg-sky-700 hover:bg-sky-600 text-xs font-medium text-slate-100 border border-sky-500/50 cursor-pointer" title="Random backlog pick (quick, co-op, hidden gem, or long)">What to play tonight?</button>`;
  }
}

function bindPlayTonightButton() {
  const wrap = document.getElementById("dashboardPlayTonight");
  if (!wrap || wrap.dataset.playTonightBound) return;
  wrap.dataset.playTonightBound = "1";
  wrap.addEventListener("click", e => {
    if (!e.target.closest("#playTonightBtn")) return;
    const pick = pickPlayTonight(dashboardLibraryGames());
    if (!pick) {
      alert("No backlog games match — add some titles to your backlog first.");
      return;
    }
    c('switchView')("library");
    c('focusGame')(c('gameKey')(pick));
  });
}

function renderDashboardLists(games) {
  const topRated = games
    .filter(g => c('getPersonal')(g).status === "backlog" && c('ratingValue')(g) > 0 && c('hasEnoughReviews')(g))
    .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
    .slice(0, 10);
  const quickWins = games
    .filter(g => c('getPersonal')(g).status === "backlog" && (c('hltbMain')(g) || 999) <= (state.prefs.quickWinMaxHours || 15) && c('ratingValue')(g) >= QUICK_WIN_MIN_RATING)
    .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
    .slice(0, 10);
  const listHtml = (items, scoreFn) => items.length
    ? items.map(g => {
      const cover = g.library_image || c('coverFallbackFor')(g);
      const score = scoreFn(g);
      const key = c('gameKey')(g);
      return `<button type="button" class="dash-list-row" data-action="dash-list-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} in the library"><img class="dash-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" /><span class="truncate flex-1">${escapeHtml(g.name)}</span><span class="text-slate-400">${score}</span></button>`;
    }).join("")
    : '<p class="text-xs text-slate-500 italic">No matches yet.</p>';
  document.getElementById("dashTopRated").innerHTML = listHtml(topRated, g => `${c('ratingValue')(g)}%`);
  document.getElementById("dashQuickWins").innerHTML = listHtml(quickWins, g => `${c('hltbMain')(g) || "?"}h`);
}

function renderDashboardWishlistStats() {
  const el = document.getElementById("dashboardWishlistStats");
  if (!el) return;
  const wl = state.wishlistGames;
  if (!wl.length) {
    el.innerHTML = `<div class="dash-card sm:col-span-3"><div class="text-sm text-slate-400">No wishlist data — run <code class="text-slate-200">fetch_wishlist.py</code>, then reload.</div></div>`;
    return;
  }

  const onSale = wl.filter(g => { const d = c('getDealInfo')(g); return d && (d.cut || 0) > 0; });
  const withDeals = c('wishlistGamesWithDeals')(wl);
  const topDeal = withDeals.length
    ? [...withDeals].sort((a, b) => c('dealScore')(b) - c('dealScore')(a))[0]
    : null;

  let hasPricing = false;
  let bestCut = 0;
  let bestCutGame = "";
  let cutSum = 0;
  const cuts = [];
  for (const g of wl) {
    const d = c('getDealInfo')(g);
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

  const steals = wl.filter(c('isStealDeal'));

  el.innerHTML = [
    topDeal ? c('dealHeroCardHtml')(topDeal) : c('dealHeroEmptyHtml')(),
    c('dealSaleScoreboardCardHtml')({
      onSaleCount: onSale.length,
      totalCount: wl.length,
      avgCut,
      bestCut,
      bestCutGame,
      hasPricing,
      cuts,
    }),
    c('dealStealsCardHtml')(steals),
  ].join("");
}

function renderItchHeroHtml(candidates) {
  if (!candidates.length) {
    return `<div class="itch-hero">
      <div class="itch-hero-label"><span>Featured unplayed pick</span></div>
      <div class="itch-hero-empty">No rated picks yet — run <code class="text-slate-200">enrich_steam_reviews.py --stores itch</code> to backfill ratings.</div>
    </div>`;
  }
  const idx = itchHeroIndex % candidates.length;
  const g = candidates[idx];
  const cover = g.library_image || c('coverFallbackFor')(g);
  const fb = c('coverFallbackFor')(g);
  const key = c('gameKey')(g);
  const rating = c('ratingValue')(g);
  const hltb = c('hltbMain')(g);
  const metaParts = [];
  if (g.publisher) metaParts.push(`by ${escapeHtml(g.publisher)}`);
  if (hltb) metaParts.push(`~${hltb}h`);
  const metaHtml = metaParts.length ? `<div class="itch-hero-meta">${metaParts.join(" · ")}</div>` : "";
  const desc = g.short_text
    ? `<p class="itch-hero-desc">${escapeHtml(g.short_text)}</p>`
    : "";
  const tags = c('gameGenresCanonical')(g).slice(0, 3);
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

function renderDashboardItchRecap() {
  const el = document.getElementById("dashItchRecap");
  if (!el) return;
  bindItchRecapClick();
  if (dashboardCharts.chartItchStatus) {
    dashboardCharts.chartItchStatus.destroy();
    delete dashboardCharts.chartItchStatus;
  }

  const total = state.itchGames.length;
  if (!total) {
    el.innerHTML = `<p class="text-sm text-slate-400">No itch.io data loaded. Run <code class="text-slate-200">fetch_itch.py</code>, then reload.</p>`;
    return;
  }

  const gamesOnly = state.itchGames.filter(c('itchIsGame'));
  const videogames = gamesOnly.length;
  const rated = gamesOnly.filter(g => c('ratingValue')(g) > 0).length;
  const unrated = videogames - rated;
  const nonGames = total - videogames;
  const backlogged = gamesOnly.filter(g => c('getPersonal')(g).status === "backlog").length;

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

  const heroCandidates = gamesOnly
    .filter(g => c('getPersonal')(g).status !== "finished" && (g.playtime_minutes || 0) === 0)
    .filter(g => c('ratingValue')(g) > 0 && c('hasEnoughReviews')(g))
    .sort((a, b) => c('ratingValue')(b) - c('ratingValue')(a))
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
        <div class="itch-breakdown-list">${itchBreakdownRows(classEntries, "itch-bar-class", "itch-drill-class")}</div>
      </div>`
    : "";

  const genreCounts = {};
  gamesOnly.forEach(g => {
    c('gameGenresCanonical')(g).forEach(genre => {
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

function renderDashboardCharts(games) {
  const storeCounts = {};
  games.forEach(g => {
    const s = c('normalizeGame')(g).store;
    storeCounts[s] = (storeCounts[s] || 0) + 1;
  });
  const storeEntries = Object.entries(storeCounts).sort((a, b) => b[1] - a[1]);
  setDashboardChart("chartStoreDonut", {
    type: "doughnut",
    data: {
      labels: storeEntries.map(([k]) => DASH_STORE_LABELS[k] || k),
      datasets: [{ data: storeEntries.map(([, v]) => v), backgroundColor: storeEntries.map(([k]) => DASH_STORE_COLORS[k] || "#64748b"), borderWidth: 0 }],
    },
    options: dashChartOptions({
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillStore(storeEntries[elements[0].index][0]);
      },
    }),
  });

  const statusCounts = {};
  STATUS_CHIP_DEFS.forEach(d => { statusCounts[d.key] = 0; });
  games.forEach(g => { statusCounts[c('chipStatusKey')(g)]++; });
  const statusEntries = STATUS_CHIP_DEFS.filter(d => statusCounts[d.key] > 0 && (d.key !== "__none__" || statusCounts[d.key] > 0));
  setDashboardChart("chartStatusDonut", {
    type: "doughnut",
    data: {
      labels: statusEntries.map(d => d.label),
      datasets: [{ data: statusEntries.map(d => statusCounts[d.key]), backgroundColor: statusEntries.map(d => DASH_STATUS_COLORS[d.key]), borderWidth: 0 }],
    },
    options: dashChartOptions({
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillStatus(statusEntries[elements[0].index].key);
      },
    }),
  });

  const genreCounts = {};
  games.forEach(g => c('gameGenresCanonical')(g).forEach(c => {
    genreCounts[c] = (genreCounts[c] || 0) + 1;
  }));
  const topGenres = Object.entries(genreCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  setDashboardChart("chartGenresBar", {
    type: "bar",
    data: {
      labels: topGenres.map(([g]) => g),
      datasets: [{
        label: "Games",
        data: topGenres.map(([, n]) => n),
        backgroundColor: "#38bdf8",
      }],
    },
    options: dashChartOptions({
      indexAxis: "y",
      layout: { padding: { right: 30 } },
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onClick(_evt, elements) { if (elements.length) dashDrillGenre(topGenres[elements[0].index][0]); },
    }),
    plugins: [makeBarEndLabelsPlugin(i => topGenres[i]?.[1])],
  });

  const stores = [...new Set(games.map(g => c('normalizeGame')(g).store))];
  const backlogByStore = { backlog: {}, finished: {} };
  stores.forEach(s => { backlogByStore.backlog[s] = 0; backlogByStore.finished[s] = 0; });
  games.forEach(g => {
    const st = c('getPersonal')(g).status;
    const store = c('normalizeGame')(g).store;
    const hrs = c('hltbMain')(g) || 0;
    if (st === "backlog") backlogByStore.backlog[store] += hrs;
    else if (st === "finished") backlogByStore.finished[store] += hrs;
  });
  const sortedStores = stores.sort((a, b) => {
    const totalA = (backlogByStore.backlog[a] || 0) + (backlogByStore.finished[a] || 0);
    const totalB = (backlogByStore.backlog[b] || 0) + (backlogByStore.finished[b] || 0);
    return totalB - totalA;
  });
  const storeBrandColors = sortedStores.map(s => DASH_STORE_COLORS[s] || "#64748b");
  setDashboardChart("chartBacklogStore", {
    type: "bar",
    data: {
      labels: sortedStores.map(s => DASH_STORE_LABELS[s] || s),
      datasets: [
        {
          label: "Backlog",
          data: sortedStores.map(s => backlogByStore.backlog[s]),
          backgroundColor: storeBrandColors.map(c => c + "FF"),
        },
        {
          label: "Finished",
          data: sortedStores.map(s => backlogByStore.finished[s]),
          backgroundColor: storeBrandColors.map(c => c + "55"),
        },
      ],
    },
    options: dashChartOptions({
      indexAxis: "y",
      layout: { padding: { right: 60 } },
      plugins: { legend: { display: false } },
      scales: { x: { stacked: true, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { stacked: true, ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onHover(evt, elements) {
        const canvas = evt.native?.target;
        if (canvas) canvas.style.cursor = elements.length ? "pointer" : "default";
      },
      onClick(_evt, elements) {
        if (!elements.length) return;
        const el = elements[0];
        const store = sortedStores[el.index];
        const status = el.datasetIndex === 0 ? "backlog" : "finished";
        dashDrillStoreStatus(store, status);
      },
    }),
    plugins: [makeBarEndLabelsPlugin(i => {
      const s = sortedStores[i];
      const total = Math.round((backlogByStore.backlog[s] || 0) + (backlogByStore.finished[s] || 0));
      return total > 0 ? formatNum(total) : "";
    })],
  });

  const buckets = ["0–2h", "2–5h", "5–10h", "10–20h", "20–40h", "40h+"];
  const bucketCounts = [0, 0, 0, 0, 0, 0];
  games.filter(g => c('getPersonal')(g).status === "backlog").forEach(g => {
    const h = c('hltbMain')(g);
    if (h == null) return;
    if (h <= 2) bucketCounts[0]++;
    else if (h <= 5) bucketCounts[1]++;
    else if (h <= 10) bucketCounts[2]++;
    else if (h <= 20) bucketCounts[3]++;
    else if (h <= 40) bucketCounts[4]++;
    else bucketCounts[5]++;
  });
  const hltbBucketColors = ["#22c55e", "#84cc16", "#eab308", "#f59e0b", "#ef4444", "#b91c1c"];
  setDashboardChart("chartHltbHist", {
    type: "bar",
    data: { labels: buckets, datasets: [{ label: "Backlog games", data: bucketCounts, backgroundColor: hltbBucketColors, borderColor: hltbBucketColors, borderWidth: 1 }] },
    options: dashChartOptions({
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } } },
      onClick(_evt, elements) { if (elements.length) dashDrillHltbBucket(elements[0].index); },
    }),
  });

  const reviewBuckets = {
    "Overwhelmingly Positive": 0, "Very Positive": 0, "Mostly Positive": 0,
    "Mixed": 0, "Mostly Negative": 0, "Negative": 0, "Unreviewed": 0,
  };
  games.forEach(g => {
    const d = g.steam_review_desc;
    if (d && reviewBuckets[d] !== undefined) reviewBuckets[d]++;
    else if (c('ratingValue')(g) > 0) reviewBuckets.Mixed++;
    else reviewBuckets.Unreviewed++;
  });
  const revEntries = Object.entries(reviewBuckets).filter(([, n]) => n > 0);
  setDashboardChart("chartReviewDonut", {
    type: "doughnut",
    data: {
      labels: revEntries.map(([k]) => k),
      datasets: [{ data: revEntries.map(([, n]) => n), backgroundColor: revEntries.map(([k]) => DASH_REVIEW_COLORS[k] || "#475569"), borderWidth: 0 }],
    },
    options: dashChartOptions({
      plugins: { legend: { position: "right" } },
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillReviewTier(revEntries[elements[0].index][0]);
      },
    }),
  });

  const yearCounts = {};
  games.forEach(g => {
    const y = (g.release_date || "").slice(0, 4);
    if (y && /^\d{4}$/.test(y) && +y >= 1990) yearCounts[y] = (yearCounts[y] || 0) + 1;
  });
  const years = Object.keys(yearCounts).sort();
  const trendData = years.map(y => yearCounts[y]);
  const rolling = years.map((_, i) => {
    const lo = Math.max(0, i - 1);
    const hi = Math.min(years.length - 1, i + 1);
    let sum = 0, n = 0;
    for (let j = lo; j <= hi; j++) { sum += trendData[j]; n++; }
    return n > 0 ? sum / n : 0;
  });
  setDashboardChart("chartReleases", {
    type: "line",
    data: {
      labels: years,
      datasets: [
        {
          label: "Games / year",
          data: trendData,
          borderColor: "rgba(56, 189, 248, 0.95)",
          backgroundColor: "rgba(56, 189, 248, 0.18)",
          borderWidth: 1.5,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.25,
          fill: true,
        },
        {
          label: "3-yr rolling avg",
          data: rolling,
          borderColor: "rgba(52, 211, 153, 0.95)",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.4,
          borderDash: [4, 3],
          fill: false,
        },
      ],
    },
    options: dashChartOptions({
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: { color: "#cbd5e1", boxWidth: 12, font: { size: 11 } },
        },
        tooltip: { mode: "index", intersect: false },
      },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { ticks: { color: "#94a3b8", maxRotation: 45 }, grid: { display: false } },
        y: { beginAtZero: true, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } },
      },
      onClick(_evt, elements) {
        if (!elements.length) return;
        dashDrillReleaseYear(years[elements[0].index]);
      },
    }),
    plugins: [makeEraBandsPlugin(years)],
  });

  const scatterGames = games.filter(g => c('ratingValue')(g) > 0 && c('hltbMain')(g) != null && c('hltbMain')(g) > 0);
  const scatterPts = scatterGames.map(g => ({
    x: c('hltbMain')(g),
    y: c('ratingValue')(g),
    label: g.name,
  }));
  const ratingGradient = (rating, alpha) => {
    const t = Math.max(0, Math.min(1, rating / 100));
    const r = Math.round(245 + (16 - 245) * t);
    const g = Math.round(158 + (185 - 158) * t);
    const b = Math.round(11 + (129 - 11) * t);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  };
  setDashboardChart("chartScatter", {
    type: "scatter",
    data: {
      datasets: [{
        label: "Games",
        data: scatterPts.map(p => ({ x: p.x, y: p.y })),
        backgroundColor: scatterPts.map(p => ratingGradient(p.y, 0.55)),
        borderColor: scatterPts.map(p => ratingGradient(p.y, 0.95)),
        borderWidth: 0.6,
        pointRadius: 4,
        pointHoverRadius: 7,
      }],
    },
    options: dashChartOptions({
      scales: {
        x: {
          type: "logarithmic",
          title: { display: true, text: "HLTB main (hours, log scale)", color: "#94a3b8" },
          min: 0.5,
          ticks: {
            color: "#94a3b8",
            autoSkip: false,
            callback(v) {
              const allowed = new Set([1, 2, 5, 10, 25, 50, 100, 250, 500, 1000, 2000]);
              return allowed.has(Number(v)) ? `${v}h` : "";
            },
          },
          grid: { color: "#334155" },
        },
        y: { title: { display: true, text: "Steam review %", color: "#94a3b8" }, min: 0, max: 100, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label(ctx) {
              const pt = scatterPts[ctx.dataIndex];
              return pt ? `${pt.label}: ${pt.x}h · ${pt.y}%` : "";
            },
          },
        },
      },
      onClick(_evt, elements) {
        if (!elements.length) return;
        const g = scatterGames[elements[0].index];
        if (!g) return;
        c('switchView')("library");
        c('focusGame')(c('gameKey')(g));
      },
    }),
  });

}

export function renderDashboard() {
  if (state.activeView !== "dashboard") return;
  const loading = document.getElementById("dashboardLoading");
  const content = document.getElementById("dashboardContent");
  if (typeof Chart === "undefined") {
    loading?.classList.remove("hidden");
    content?.classList.add("hidden");
    if (loading) loading.textContent = "Loading charts…";
    return;
  }
  loading?.classList.add("hidden");
  content?.classList.remove("hidden");
  destroyDashboardCharts();
  Chart.defaults.color = "#94a3b8";
  Chart.defaults.borderColor = "#334155";
  const games = dashboardLibraryGames();
  renderDashboardFetcherHealth();
  bindPlayTonightButton();
  renderDashboardKPIs(games);
  renderDashboardItchRecap();
  try {
    renderDashboardCharts(games);
  } catch (err) {
    console.error("Dashboard charts error:", err);
  }
  renderDashboardWishlistStats();
  try {
    renderDashboardCoopSpotlight(games);
  } catch (err) {
    console.error("Dashboard co-op spotlight error:", err);
  }
  try {
    renderDashboardLists(games);
  } catch (err) {
    console.error("Dashboard lists error:", err);
  }
}

export function cancelScheduledDashboardRender() {
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = null;
}

export function scheduleDashboardRender() {
  if (state.activeView !== "dashboard") return;
  cancelScheduledDashboardRender();
  _dashboardRenderTimer = setTimeout(renderDashboard, 80);
}
