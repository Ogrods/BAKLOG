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
  libraryCoverFor,
  earlyAccessRibbonHtml,
} from './game-core.js';
import { storeLogoHtml } from './store-logos.js';
import {
  getDealInfo,
  dealScore,
  dealDroppedBadgeHtml,
  isOwnedByTitle,
} from './deals.js';
import { getPersonal, filterOutHidden } from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { syncCoverFits } from './covers.js';

export function pickCardHtml(g) {
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = libraryCoverFor(g);
  const ratingVal = ratingValue(g);
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : " - ";
  const h = hltbMain(g);
  const store = normalizeGame(g).store;
  return `
    <div class="pick-card relative rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" title="${escapeAttr(g.name)} · ${rating}${h != null ? ` · ${h}h` : ""}">
      <span class="pick-store">${storeLogoHtml(store, { size: 'sm' })}</span>
      <div class="cover-wrap w-full block${window.coverLandscapeAttr(cover)}">
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
        ${earlyAccessRibbonHtml(g)}
      </div>
      <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(g.name)}</div>
      <div class="text-xs text-slate-400 flex justify-between"><span>${rating}</span><span>${h != null ? `${h}h` : ""}</span></div>
    </div>`;
}

export function dealCardHtml(g) {
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = libraryCoverFor(g);
  const d = getDealInfo(g);
  const priceLabel = d && d.price != null ? `$${d.price.toFixed(2)}` : " - ";
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
    <div class="pick-card relative rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" data-pick-context="wishlist" title="${escapeAttr(g.name)}${cutLabel ? ` · ${cutLabel}` : ""}${shop ? ` @ ${shop}` : ""}">
      <span class="pick-store" title="Wishlist · ${wishlistTarget.toUpperCase()}">${storeLogoHtml(wishlistTarget, { size: 'sm' })}</span>
      <div class="cover-wrap w-full block${window.coverLandscapeAttr(cover)}">
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
        ${earlyAccessRibbonHtml(g)}
      </div>
      <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(g.name)}</div>
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
  // #region agent log
  try {
    const _c = !!state.prefs.picksCollapsed;
    const _hidden = document.getElementById('picksContainer')?.classList.contains('hidden');
    const _btn = document.getElementById('togglePicks')?.textContent;
    const _diverged = (_btn === 'Hide' && _hidden === true) || (_btn === 'Show' && _hidden === false) || (_c === true && _hidden === false) || (_c === false && _hidden === true);
    if (_diverged) {
      fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'4b7a6f'},body:JSON.stringify({sessionId:'4b7a6f',hypothesisId:'E',location:'picks-ui.js:renderPicks',message:'DIVERGENCE detected',data:{collapsed:_c,containerHidden:_hidden,btn:_btn,sectionHidden:document.getElementById('picksSection')?.classList.contains('hidden'),initView:document.documentElement.getAttribute('data-init-view'),activeView:state.activeView},timestamp:Date.now()})}).catch(()=>{});
    }
  } catch (_e) {}
  // #endregion
  const tab = effectivePicksTab();
  const pickView = state.activeView === "wishlist" ? "wishlist" : state.activeView === "itch" ? "itch" : "library";
  const visibleLibrary = filterOutHidden(state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))));
  const visibleItch = filterOutHidden(state.itchGames);
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
    ? (state.wishlistGames.length === 0
      ? "No deals on your wishlist yet. Connect a store and run the wishlist and deal price fetchers from Fetcher health."
      : "No wishlist deals on sale right now. Refresh prices from Fetcher health, or check back after the next sale.")
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
