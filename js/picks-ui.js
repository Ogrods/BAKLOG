import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  gameKey,
  normalizeGame,
  ratingValue,
  hltbMain,
  hasEnoughReviews,
  isHiddenGem,
  coverFallbackFor,
  storeLetter,
  earlyAccessRibbonHtml,
} from './game-core.js';
import {
  getDealInfo,
  dealScore,
  dealDroppedBadgeHtml,
  isOwnedByTitle,
} from './deals.js';
import { getPersonal } from './personal-storage.js';
import { passesTagFilterFromPrefs } from './tag-filter.js';
import { savePrefs } from './prefs.js';
import { syncCoverFits } from './covers.js';

export function passesTagFilter(g) {
  return passesTagFilterFromPrefs(state.prefs, getPersonal(g).tags || []);
}

export function pickCardHtml(g) {
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = g.library_image || headerFallback;
  const ratingVal = ratingValue(g);
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : "—";
  const h = hltbMain(g);
  const store = normalizeGame(g).store;
  const badge = store === "gog" ? "G" : store === "psn" ? "P" : store === "epic" ? "E" : store === "amazon" ? "A" : store === "nintendo" ? "N" : store === "xbox" ? "X" : store === "battlenet" ? "B" : store === "ubisoft" ? "U" : store === "other" ? "?" : "S";
  return `
    <div class="pick-card relative bg-slate-700/50 rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" title="${escapeAttr(g.name)} · ${rating}${h != null ? ` · ${h}h` : ""}">
      <span class="pick-store store-badge ${store}">${badge}</span>
      <div class="cover-wrap w-full block${window.coverLandscapeAttr(cover)}">
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
        ${earlyAccessRibbonHtml(g)}
      </div>
      <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(g.name)}</div>
      ${pickTagsHtml(g)}
      <div class="text-xs text-slate-400 flex justify-between"><span>${rating}</span><span>${h != null ? `${h}h` : ""}</span></div>
    </div>`;
}

function pickTagsHtml(g) {
  const tags = getPersonal(g).tags || [];
  if (!tags.length) return "";
  const max = 3;
  const shown = tags.slice(0, max);
  const extra = tags.length - shown.length;
  const chips = shown.map(t => `<span class="pick-tag-chip">${escapeHtml(t)}</span>`).join("");
  const more = extra > 0 ? `<span class="pick-tag-more">+${extra}</span>` : "";
  return `<div class="pick-tag-row">${chips}${more}</div>`;
}

export function dealCardHtml(g) {
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = g.library_image || headerFallback;
  const d = getDealInfo(g);
  const priceLabel = d && d.price != null ? `$${d.price.toFixed(2)}` : "—";
  const cutLabel = d && d.cut ? `-${d.cut}%` : "";
  const cutValue = d && d.cut ? d.cut : 0;
  const cutClass = cutValue >= 75
    ? "deal-flag-cut deal-flag-cut--huge"
    : cutValue >= 50
      ? "deal-flag-cut deal-flag-cut--big"
      : "deal-flag-cut";
  const lowFlag = d && d.isHistoricalLow
    ? `<span class="deal-flag-low" title="${d.lowKind === "year" ? "1-year low" : "All-time low"}">★ ${d.lowKind === "year" ? "1yr" : "low"}</span>`
    : "";
  const dropFlag = dealDroppedBadgeHtml(g);
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : "";
  const ownedTxt = isOwnedByTitle(g.name) ? '<span class="text-amber-400/80 shrink-0">own</span>' : "";
  const shop = d && d.shop ? d.shop : "";
  const wishlistTarget = g.wishlist_store || g.store_target || (g.manual ? "manual" : "steam");
  return `
    <div class="pick-card relative bg-slate-700/50 rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" data-pick-context="wishlist" title="${escapeAttr(g.name)}${cutLabel ? ` · ${cutLabel}` : ""}${shop ? ` @ ${shop}` : ""}">
      <span class="pick-store store-badge ${wishlistTarget}" title="Wishlist · ${wishlistTarget.toUpperCase()}">${storeLetter(wishlistTarget)}</span>
      <div class="cover-wrap w-full block${window.coverLandscapeAttr(cover)}">
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
        ${earlyAccessRibbonHtml(g)}
      </div>
      <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(g.name)}</div>
      ${pickTagsHtml(g)}
      <div class="text-xs text-slate-400 flex justify-between items-center gap-1">
        <span class="text-slate-100">${priceLabel}</span>
        <span class="flex items-center gap-1 shrink-0">
          ${dropFlag}
          ${cutLabel ? `<span class="${cutClass}">${cutLabel}</span>` : ""}
          ${lowFlag}
        </span>
      </div>
      <div class="text-[10px] text-slate-500 flex justify-between gap-1 mt-0.5 min-w-0">
        <span class="truncate">${escapeHtml(shop)}</span>
        <span class="flex items-center gap-1 shrink-0">${rating}${ownedTxt}</span>
      </div>
    </div>`;
}

export function normalizePicksLimit() {
  const validLimits = [16, 24, 48, 96];
  const n = Number(state.prefs.picksLimit);
  if (!validLimits.includes(n)) {
    state.prefs.picksLimit = 16;
    savePrefs();
  }
  return state.prefs.picksLimit;
}

export function renderPicksLimitButtons() {
  const limit = normalizePicksLimit();
  document.querySelectorAll(".picks-limit-btn").forEach(btn => {
    btn.classList.toggle("active", +btn.dataset.limit === limit);
  });
}

export function updatePicksChrome() {
  // Quick-Wins slider only makes sense alongside the Quick Wins picks tab,
  // which is library-only. Hide the wrapper on wishlist/itch so the picks
  // bar stays tidy.
  const hideQuick = state.activeView === "wishlist" || state.activeView === "itch";
  document.getElementById("quickWinMaxWrap")?.classList.toggle("hidden", hideQuick);
}

/** Picks tab for the active view — never show library tabs on wishlist. */
export function effectivePicksTab() {
  const view = state.activeView;
  if (view === "wishlist") return "wishlistDeals";
  if (view === "itch") {
    const t = state.prefs.itchPicksTab || state.prefs.picksTab;
    return t === "wishlistDeals" ? "topRated" : (t || "topRated");
  }
  const t = state.prefs.picksTab;
  if (t === "wishlistDeals") return state.prefs.libraryPicksTab || "topRated";
  return t || "topRated";
}

export function renderPicks() {
  const tab = effectivePicksTab();
  const pickView = state.activeView === "wishlist" ? "wishlist" : state.activeView === "itch" ? "itch" : "library";
  const visibleLibrary = state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)) && passesTagFilter(g));
  const visibleItch = state.itchGames.filter(g => passesTagFilter(g));
  const visible = pickView === "itch" ? visibleItch : visibleLibrary;
  const backlogRated = visible
    .filter(g => getPersonal(g).status === "backlog" && ratingValue(g) > 0 && (pickView === "itch" || hasEnoughReviews(g)))
    .sort((a, b) => ratingValue(b) - ratingValue(a));
  const nextUp = visible.filter(g => getPersonal(g).status === "next")
    .sort((a, b) => ratingValue(b) - ratingValue(a));
  const quickWins = visible
    .filter(g => getPersonal(g).status === "backlog" && ratingValue(g) >= 75 && hasEnoughReviews(g) && (hltbMain(g) || 999) <= state.prefs.quickWinMaxHours)
    .sort((a, b) => ratingValue(b) - ratingValue(a));
  const hidden = visible.filter(g => isHiddenGem(g) && hasEnoughReviews(g)).sort((a, b) => ratingValue(b) - ratingValue(a));
  const returnTo = visible
    .filter(g => getPersonal(g).status === "unfinished")
    .sort((a, b) => {
      const la = a.last_played ? Date.parse(a.last_played) : 0;
      const lb = b.last_played ? Date.parse(b.last_played) : 0;
      if (lb !== la) return lb - la;
      return ratingValue(b) - ratingValue(a);
    });
  const wishlistDeals = state.wishlistGames
    .filter(g => !state.wishlistCrossStoreHiddenKeys.has(gameKey(g)))
    .filter(g => passesTagFilter(g))
    .filter(g => {
      const d = getDealInfo(g);
      if (!d) return false;
      return (d.cut || 0) > 0 || d.isHistoricalLow;
    })
    .sort((a, b) => {
      const pa = getDealInfo(a)?.price;
      const pb = getDealInfo(b)?.price;
      const va = pa == null ? Infinity : pa;
      const vb = pb == null ? Infinity : pb;
      if (va !== vb) return va - vb;
      return dealScore(b) - dealScore(a);
    });
  let data;
  switch (tab) {
    case "nextUp": data = pickView === "library" ? nextUp : []; break;
    case "quickWins": data = pickView === "library" ? quickWins : []; break;
    case "hiddenGems": data = pickView === "library" ? hidden : []; break;
    case "returnTo": data = pickView === "library" ? returnTo : []; break;
    case "wishlistDeals": data = wishlistDeals; break;
    default: data = pickView === "wishlist" ? wishlistDeals : backlogRated;
  }
  if (pickView === "itch" && tab !== "topRated") data = backlogRated;
  const limit = state.prefs.picksLimit || 16;
  const countLabel = `${Math.min(data.length, limit)} of ${data.length}`;
  document.getElementById("pickMeta").textContent = countLabel;
  const renderCard = tab === "wishlistDeals" ? dealCardHtml : pickCardHtml;
  const emptyMsg = tab === "wishlistDeals"
    ? 'No deals on your wishlist right now. Run <code class="bg-slate-700 px-1 rounded">fetch_itad.py</code> for cross-store prices.'
    : pickView === "itch"
      ? "No rated itch.io backlog games yet. Most indie titles won't have Steam review scores."
      : "No games match this tab yet.";
  const picksGrid = document.getElementById("picksGrid");
  const rendererTag = tab === "wishlistDeals" ? "deal" : "pick";
  if (data.length) {
    const slice = data.slice(0, limit);
    const newKeys = slice.map(g => gameKey(g));
    const existingCards = Array.from(picksGrid.querySelectorAll(".pick-card"));
    const existingKeys = existingCards.map(c => c.dataset.gameKey || "");
    const sameRenderer = picksGrid.dataset.renderer === rendererTag;
    let canIncremental = sameRenderer && existingKeys.length > 0;
    if (canIncremental) {
      const overlap = Math.min(existingKeys.length, newKeys.length);
      for (let i = 0; i < overlap; i++) {
        if (existingKeys[i] !== newKeys[i]) { canIncremental = false; break; }
      }
    }
    if (canIncremental) {
      if (newKeys.length < existingKeys.length) {
        for (let i = newKeys.length; i < existingKeys.length; i++) existingCards[i].remove();
      } else if (newKeys.length > existingKeys.length) {
        const tail = slice.slice(existingKeys.length).map(renderCard).join("");
        picksGrid.insertAdjacentHTML("beforeend", tail);
        syncCoverFits(picksGrid);
      }
    } else {
      picksGrid.innerHTML = slice.map(renderCard).join("");
      picksGrid.dataset.renderer = rendererTag;
      syncCoverFits(picksGrid);
    }
  } else {
    picksGrid.innerHTML = `<div class="col-span-full text-sm text-slate-400 italic">${emptyMsg}</div>`;
    picksGrid.dataset.renderer = "";
  }
  document.querySelectorAll(".pick-tab").forEach(el => {
    const owner = el.dataset.pickView;
    const visibleHere = !owner || owner === pickView;
    el.classList.toggle("active", visibleHere && el.dataset.tab === tab);
  });
  updatePicksChrome();
  renderPicksLimitButtons();
}
