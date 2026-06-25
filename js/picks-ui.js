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
  parseLastPlayedMs,
} from './game-core.js';
import { safeCoverAttrUrl } from './covers.js';
import { storeLogoHtml } from './store-logos.js';
import {
  getDealInfo,
  dealScore,
  dealDroppedBadgeHtml,
  isOwnedByTitle,
} from './deals.js';
import { getPersonal, filterOutHidden } from './personal-storage.js';
import { getPicksLimitForView, setPicksLimitForView } from './prefs.js';
import { syncCoverFits } from './covers.js';
import { sponsoredPickSlotHtml, sponsoredDealPickSlotHtml, pickLocationForView, houseLocationForView, renderHouseLocationSlot } from './sponsored-deals.js';

export function pickCardHtml(g) {
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = libraryCoverFor(g);
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : " - ";
  const h = hltbMain(g);
  const store = normalizeGame(g).store;
  return `
    <div class="pick-card relative rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" title="${escapeAttr(g.name)} · ${rating}${h != null ? ` · ${h}h` : ""}">
      <span class="pick-store">${storeLogoHtml(store, { size: 'sm' })}</span>
      <div class="cover-wrap w-full block${window.coverLandscapeAttr(cover)}">
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${safeCoverAttrUrl(cover)}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
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
        <img class="pick-cover${window.coverLandscapeAttr(cover)}" src="${safeCoverAttrUrl(cover)}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
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

export function picksViewKey() {
  const v = state.activeView;
  return v === "wishlist" ? "wishlist" : v === "itch" ? "itch" : "library";
}

export function normalizePicksLimit() {
  const view = picksViewKey();
  const limit = getPicksLimitForView(view);
  const stored = Number(state.prefs.viewPicksLimits?.[view]);
  if (stored !== limit) setPicksLimitForView(view, limit);
  return limit;
}

export function renderPicksLimitButtons() {
  const limit = normalizePicksLimit();
  document.querySelectorAll(".picks-limit-btn").forEach(btn => {
    btn.classList.toggle("active", +btn.dataset.limit === limit);
  });
}

export function updatePicksChrome() {
  // The Quick-Wins slider only makes sense on the Quick Wins picks tab,
  // so only reveal it when that tab is active.
  const showQuick = effectivePicksTab() === "quickWins";
  document.getElementById("quickWinMaxWrap")?.classList.toggle("hidden", !showQuick);
}

/** Sync #picksContainer visibility and #togglePicks label to picksCollapsed. */
export function applyPicksCollapsedState() {
  const collapsed = state.prefs.picksCollapsed === true;
  state.prefs.picksCollapsed = collapsed;
  const container = document.getElementById("picksContainer");
  const toggle = document.getElementById("togglePicks");
  if (container) container.classList.toggle("hidden", collapsed);
  if (toggle) {
    toggle.textContent = collapsed ? "Show" : "Hide";
    toggle.title = collapsed ? "Show the Picks panel" : "Hide the Picks panel";
  }
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
      const la = parseLastPlayedMs(a);
      const lb = parseLastPlayedMs(b);
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
  const limit = getPicksLimitForView(pickView);
  const pickLoc = tab === 'wishlistDeals'
    ? pickLocationForView(pickView === 'wishlist' ? 'wishlist' : 'deals', 'pick')
    : pickLocationForView(pickView, 'pick');
  const sponsoredHtml = tab === 'wishlistDeals'
    ? sponsoredDealPickSlotHtml(pickLoc)
    : sponsoredPickSlotHtml(pickLoc);
  const sponsorSlot = !!sponsoredHtml;
  // The sponsored slot occupies one grid cell, so drop one real card to keep the
  // grid at exactly `limit` tiles — otherwise the extra card wraps to a new row.
  const cardBudget = sponsorSlot ? Math.max(1, limit - 1) : limit;
  const shownDeals = Math.min(data.length, cardBudget);
  const shownTiles = Math.min(limit, shownDeals + (sponsorSlot ? 1 : 0));
  const countLabel = `${shownTiles} of ${data.length}`;
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
    const slice = data.slice(0, cardBudget);
    const newKeys = slice.map(g => gameKey(g));
    const existingCards = Array.from(
      picksGrid.querySelectorAll(".pick-card:not(.sponsored-pick-card)"),
    );
    const existingKeys = existingCards.map(c => c.dataset.gameKey || "");
    const sameRenderer = picksGrid.dataset.renderer === rendererTag;
    const hasSponsorNode = !!picksGrid.querySelector(".sponsored-pick-card");
    let handled = false;
    // Sponsor was dismissed: drop the ad tile and append the pick that was
    // budgeted out — without rebuilding the whole grid (avoids cover re-fetch flash).
    if (sameRenderer && !sponsorSlot && hasSponsorNode && existingKeys.length === limit - 1) {
      const expectedKeys = data.slice(0, limit - 1).map(g => gameKey(g));
      const keysMatch = expectedKeys.every((k, i) => existingKeys[i] === k);
      if (keysMatch && data.length >= limit) {
        picksGrid.querySelector(".sponsored-pick-card")?.remove();
        picksGrid.insertAdjacentHTML("beforeend", renderCard(data[limit - 1]));
        document.getElementById("pickMeta").textContent = `${limit} of ${data.length}`;
        syncCoverFits(picksGrid);
        handled = true;
      }
    }
    let canIncremental = !handled && sameRenderer && existingKeys.length > 0 && !sponsorSlot && !hasSponsorNode;
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
    } else if (!handled) {
      const parts = slice.map(renderCard);
      if (sponsoredHtml) parts.splice(Math.min(1, parts.length), 0, sponsoredHtml);
      picksGrid.innerHTML = parts.join("");
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
  renderViewHouseSlot();
}

/** Single house promo below picks / deal radar (library stripe, itch stripe, wishlist banner). */
export function renderViewHouseSlot() {
  const slot = document.getElementById('viewHouseSlot');
  if (!slot) return;
  const view = state.activeView;
  const location = houseLocationForView(view);
  if (view === 'dashboard' || view === 'connections' || view === 'pro') {
    slot.classList.add('hidden');
    slot.innerHTML = '';
    return;
  }
  slot.classList.remove('hidden');
  renderHouseLocationSlot(location, 'viewHouseSlot');
}
