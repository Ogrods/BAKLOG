import { state, CLEANUP_MAX_RATING, CLEANUP_MIN_AGE_MS } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  gameKey,
  normalizeGame,
  normalizeNameForDedup,
  ratingValue,
  hltbMain,
  coverFallbackFor,
  libraryCoverFor,
  formatDollar,
  wishlistBadgeHtml,
  earlyAccessRibbonHtml,
  parseReleaseForSort,
  combinedPlaytime,
} from './game-core.js';
import { isPlatformToken } from './genres.js';
import { getPersonal } from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { refreshFilterUI, switchView } from './filters-ui.js';

/** Cut-depth modifier class — emerald default, big-gradient for 50%+,
 *  amber→red→pink gradient for 75%+. Matches the pre-CSS-extract project. */
export function cutBucketClass(cut) {
  if (!Number.isFinite(cut) || cut <= 0) return "";
  if (cut >= 75) return "deal-cut-huge";
  if (cut >= 50) return "deal-cut-big";
  return "";
}

export function isStealDeal(g) {
  const d = getDealInfo(g);
  if (!d) return false;
  const cut = d.cut || 0;
  if (cut <= 0) return false;
  const rating = ratingValue(g);
  if (rating < 80) return false;
  return cut >= 50 || d.isHistoricalLow;
}

export function wishlistGamesWithDeals(wl) {
  return wl.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
}

export function syncDealFilterControls() {
  const onSaleEl = document.getElementById("dealOnSaleOnly");
  if (onSaleEl) onSaleEl.checked = !!state.prefs.dealOnSaleOnly;
  const lowEl = document.getElementById("dealHistoricalLowOnly");
  if (lowEl) lowEl.checked = !!state.prefs.dealHistoricalLowOnly;
  const hideOwnedEl = document.getElementById("dealHideOwned");
  if (hideOwnedEl) hideOwnedEl.checked = !!state.prefs.dealHideOwned;
  const minEl = document.getElementById("dealMinDiscount");
  const minVal = document.getElementById("dealMinDiscountVal");
  if (minEl) minEl.value = String(state.prefs.dealMinDiscount || 0);
  if (minVal) minVal.textContent = String(state.prefs.dealMinDiscount || 0);
}

export function drillWishlistDealFilter({ onSaleOnly, minDiscount }) {
  if (onSaleOnly) state.prefs.dealOnSaleOnly = true;
  if (minDiscount != null) state.prefs.dealMinDiscount = minDiscount;
  syncDealFilterControls();
  savePrefs();
  if (state.activeView !== "wishlist") switchView("wishlist");
  else refreshFilterUI();
}

export function dealHeroCardHtml(g) {
  const d = getDealInfo(g);
  const key = gameKey(g);
  const cover = libraryCoverFor(g);
  const headerFallback = coverFallbackFor(g);
  const cut = d?.cut || 0;
  const price = d?.price;
  const regular = d?.regular;
  const shop = d?.shop ? `@ ${escapeHtml(d.shop)}` : "";
  const lowPin = dealLowBadgeHtml(d);
  const droppedPin = dealDroppedBadgeHtml(g);
  const ownedPin = ownedElsewhereBadgeHtml(g);
  const priceHtml = price != null
    ? `<span class="deal-hero-price">${formatDollar(price)}</span>${regular != null && regular > price ? `<span class="deal-hero-regular">${formatDollar(regular)}</span>` : ""}`
    : `<span class="deal-hero-price">${cut > 0 ? `${cut}% off` : "On sale"}</span>`;
  const reviewPct = g.steam_review_percent != null ? `${g.steam_review_percent}%` : null;
  const hltb = hltbMain(g);
  const hltbLabel = hltb != null ? `${hltb}h` : null;
  const genres = (g.genres || []).filter(x => !isPlatformToken(x) && !/^early access$/i.test(x)).slice(0, 2);
  const statPills = [];
  if (reviewPct) statPills.push(`<span class="deal-hero-stat" title="Steam review score"><span class="deal-hero-stat-dot deal-hero-stat-dot-review"></span>${reviewPct}</span>`);
  if (hltbLabel) statPills.push(`<span class="deal-hero-stat" title="HLTB main story"><span class="deal-hero-stat-dot deal-hero-stat-dot-hltb"></span>${hltbLabel}</span>`);
  const genreLine = genres.length
    ? `<span class="deal-hero-genres">${genres.map(escapeHtml).join(" · ")}</span>`
    : "";
  const statStrip = (statPills.length || genreLine)
    ? `<div class="deal-hero-stats">
        <div class="deal-hero-stats-row">${statPills.join("")}${genreLine}</div>
      </div>`
    : "";
  const heroBadges = [];
  if (cut > 0) heroBadges.push(`<span class="deal-cut-badge ${cutBucketClass(cut)}">-${cut}%</span>`);
  if (lowPin) heroBadges.push(lowPin);
  if (droppedPin) heroBadges.push(droppedPin);
  const wlBadge = wishlistBadgeHtml(g);
  if (wlBadge) heroBadges.push(wlBadge);
  if (ownedPin) heroBadges.push(ownedPin);
  const heroBadgesHtml = heroBadges.slice(0, 4).join("");
  // On the wishlist view the row is right there in the table below — wire the
  // card to jump to the actual sale page (deal URL) instead of re-focusing the
  // same row. The bind-events click handler picks up data-deal-url on wishlist.
  const dealUrl = d?.url ? ` data-deal-url="${escapeAttr(d.url)}"` : "";
  return `<button type="button" class="deal-card-clickable deal-hero dash-card text-left w-full" data-action="deal-hero" data-key="${escapeAttr(key)}"${dealUrl} title="Jump to ${escapeAttr(g.name)} on wishlist">
    <div class="dash-kpi-label">Today&apos;s top deal</div>
    <div class="deal-hero-body mt-2">
      <span class="cover-wrap deal-hero-cover-wrap${window.coverLandscapeAttr(cover)}">
        <img class="deal-hero-cover${window.coverLandscapeAttr(cover)}" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
        ${earlyAccessRibbonHtml(g)}
      </span>
      <div class="deal-hero-meta min-w-0 flex-1">
        <div class="deal-hero-top">
          <div class="deal-hero-name font-medium text-slate-100">${escapeHtml(g.name)}</div>
          <div class="deal-hero-prices mt-1">${priceHtml}${shop ? `<span class="text-xs text-slate-400 ml-1">${shop}</span>` : ""}</div>
        </div>
        <div class="deal-hero-badges flex flex-wrap items-center gap-1.5">
          ${heroBadgesHtml}
        </div>
        ${statStrip}
      </div>
    </div>
  </button>`;
}

export function dealHeroEmptyHtml(opts = {}) {
  const hint = opts.noWishlist
    ? "Connect a store and run its wishlist fetcher to start tracking deals."
    : "No active deals right now — check back after the next price refresh.";
  return `<div class="dash-card deal-hero-empty">
    <div class="dash-kpi-label">Today&apos;s top deal</div>
    <div class="text-sm text-slate-400 mt-3">${hint}</div>
  </div>`;
}

const CUT_BUCKETS = [
  { id: "light", label: "Light", short: "<25%", min: 1, max: 24, cls: "sale-bucket-light" },
  { id: "medium", label: "Medium", short: "25–49%", min: 25, max: 49, cls: "sale-bucket-medium" },
  { id: "deep", label: "Deep", short: "50–74%", min: 50, max: 74, cls: "sale-bucket-deep" },
  { id: "huge", label: "Huge", short: "75%+", min: 75, max: 100, cls: "sale-bucket-huge" },
];

function bucketCuts(cuts) {
  const counts = CUT_BUCKETS.map(b => ({ ...b, count: 0 }));
  for (const c of cuts) {
    if (!Number.isFinite(c) || c <= 0) continue;
    for (const bucket of counts) {
      if (c >= bucket.min && c <= bucket.max) { bucket.count++; break; }
    }
  }
  return counts;
}

export function dealSaleScoreboardCardHtml({ onSaleCount, totalCount, avgCut, bestCut, bestCutGame, hasPricing, cuts }) {
  if (!hasPricing) {
    return `<button type="button" class="deal-card-clickable dash-card text-left w-full" data-action="deal-on-sale" title="Show wishlist items on sale">
      <div class="dash-kpi-label">Sale scoreboard</div>
      <div class="text-xs text-slate-400 mt-2">Run the deal price fetcher (Fetcher health) to see cross-store sale stats.</div>
    </button>`;
  }
  const noSale = onSaleCount === 0;
  const bestLabel = bestCutGame ? `<div class="sale-stat-caption truncate" title="${escapeAttr(bestCutGame)}">${escapeHtml(bestCutGame)}</div>` : "";
  const buckets = bucketCuts(cuts || []);
  const total = buckets.reduce((a, b) => a + b.count, 0);
  const distHtml = total
    ? `<div class="sale-distribution">
        <div class="sale-distribution-label">Cut distribution</div>
        <div class="sale-distribution-bar" role="img" aria-label="Cut depth distribution">
          ${buckets.map(b => b.count
            ? `<span class="sale-distribution-seg ${b.cls}" style="flex: ${b.count};" title="${b.label} (${b.short}): ${b.count}"></span>`
            : ""
          ).join("")}
        </div>
        <div class="sale-distribution-legend">
          ${buckets.map(b => `<span class="sale-distribution-tick ${b.count ? "" : "sale-distribution-tick-empty"}" title="${b.label} (${b.short})">
            <span class="sale-distribution-swatch ${b.cls}"></span>
            <span class="sale-distribution-tick-label">${b.label}</span>
            <span class="sale-distribution-tick-count">${b.count}</span>
          </span>`).join("")}
        </div>
      </div>`
    : "";
  return `<button type="button" class="deal-card-clickable dash-card text-left w-full" data-action="deal-on-sale" title="Show wishlist items on sale">
    <div class="dash-kpi-label">Sale scoreboard</div>
    <div class="sale-scoreboard mt-2">
      <div class="sale-stat">
        <div class="sale-stat-label">On sale</div>
        <div class="sale-stat-value">${onSaleCount}<span class="sale-stat-suffix"> / ${totalCount}</span></div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Avg cut</div>
        <div class="sale-stat-value sale-stat-cut ${noSale ? "sale-stat-muted" : cutBucketClass(avgCut)}">${noSale ? "—" : `-${avgCut}%`}</div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Best cut</div>
        <div class="sale-stat-value sale-stat-cut ${noSale ? "sale-stat-muted" : `sale-stat-best ${cutBucketClass(bestCut)}`}">${noSale ? "—" : `-${bestCut}%`}</div>
        ${noSale ? "" : bestLabel}
      </div>
    </div>
    ${distHtml}
  </button>`;
}

export function dealStealsCardHtml(steals) {
  if (!steals.length) {
    return `<button type="button" class="deal-card-clickable dash-card text-left w-full" data-action="deal-steals" title="Show wishlist steals (50%+ off, 80%+ rated)">
      <div class="dash-kpi-label">Steals waiting</div>
      <div class="text-xs text-slate-400 mt-1">50%+ off or historical low · 80%+ rated</div>
      <div class="text-xs text-slate-400 mt-3">No steals match right now.</div>
    </button>`;
  }
  const ranked = [...steals].sort((a, b) => dealScore(b) - dealScore(a));
  const shown = ranked.slice(0, 6);
  const remaining = ranked.length - shown.length;
  const rows = shown.map(g => {
    const cover = libraryCoverFor(g);
    const fb = coverFallbackFor(g);
    const d = getDealInfo(g) || {};
    const cut = d.cut || 0;
    const cutLabel = cut > 0 ? `-${cut}%` : "★";
    const cutCls = cut > 0 ? cutBucketClass(cut) : "";
    const low = d.isHistoricalLow ? `<span class="steal-row-low" title="${d.lowKind === "year" ? "1-year low" : "All-time low"}">★</span>` : "";
    const dropped = itadPriceDropped(g) ? '<span class="deal-badge-drop" title="Price dropped">↓</span>' : "";
    const owned = isOwnedByTitle(g.name) ? '<span class="owned-elsewhere-pill">own</span>' : "";
    const price = d.price != null ? `<span class="steal-row-price">${formatDollar(d.price)}</span>` : "";
    const shopFull = d.shop || "";
    const shopShort = dealShopShort(shopFull);
    const shopCls = `steal-row-shop steal-row-shop-${shopSlug(shopFull)}`;
    const shop = shopShort ? `<span class="${shopCls}" title="Deal on ${escapeAttr(shopFull)}">${escapeHtml(shopShort)}</span>` : "";
    const key = gameKey(g);
    return `<button type="button" class="steal-row" data-action="deal-steal-jump" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} on wishlist${shopFull ? ` (deal on ${escapeAttr(shopFull)})` : ""}">
      <img class="steal-row-cover" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(fb)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onerror="window.coverFallback(this)" />
      <span class="steal-row-name truncate">${escapeHtml(g.name)}</span>
      ${shop}
      ${dropped}
      ${low}
      ${owned}
      <span class="steal-row-cut ${cutCls}">${cutLabel}</span>
      ${price}
    </button>`;
  }).join("");
  // The "view on wishlist" passive footer is useful on the dashboard but
  // redundant when the user is already on the wishlist view — hidden via CSS
  // (html[data-init-view="wishlist"] .steal-list-footer-passive).
  const footer = remaining > 0
    ? `<div class="steal-list-footer" data-action="deal-steals" title="Show all steals">+${remaining} more · view all →</div>`
    : `<div class="steal-list-footer steal-list-footer-passive" data-action="deal-steals" title="Show all steals on wishlist">View on wishlist →</div>`;
  return `<div class="dash-card steal-card" title="50%+ off or historical low · 80%+ rated">
    <div class="flex items-baseline justify-between gap-2">
      <div>
        <div class="dash-kpi-label">Steals waiting</div>
        <div class="text-[10px] text-slate-400 mt-0.5">50%+ off or historical low · 80%+ rated</div>
      </div>
      <div class="text-sm font-semibold text-slate-300">${steals.length}</div>
    </div>
    <div class="steal-list mt-2">${rows}</div>
    ${footer}
  </div>`;
}

export function buildOwnedNormNames() {
  state.ownedNormNames = new Set();
  for (const g of state.allGames) {
    if (state.crossStoreHiddenKeys.has(gameKey(g))) continue;
    const n = normalizeNameForDedup(g.name);
    if (n) state.ownedNormNames.add(n);
  }
}

export function isOwnedByTitle(name) {
  const n = normalizeNameForDedup(name);
  return n && state.ownedNormNames.has(n);
}

export function isCleanupCandidate(g) {
  const p = getPersonal(g);
  if (p.status !== "backlog") return false;
  if (combinedPlaytime(g) > 0) return false;
  const rating = ratingValue(g);
  if (rating > 0 && rating >= CLEANUP_MAX_RATING) return false;
  const released = parseReleaseForSort(g.release_date);
  if (!released) return true;
  return Date.now() - released >= CLEANUP_MIN_AGE_MS;
}

export function getItadForGame(g) {
  const key = gameKey(g);
  if (state.itadByKey[key]) return state.itadByKey[key];
  const ng = normalizeGame(g);
  if (ng.store === "steam" || ng.store === "wishlist") {
    const alt = state.itadByKey[`steam:${ng.id}`] || state.itadByKey[`wishlist:${ng.id}`];
    if (alt) return alt;
  }
  return null;
}

function itadKeysForGame(g) {
  const keys = [gameKey(g)];
  const ng = normalizeGame(g);
  if (ng.store === "steam" || ng.store === "wishlist") {
    keys.push(`steam:${ng.id}`, `wishlist:${ng.id}`);
  }
  return keys;
}

export function itadPriceDropped(g) {
  for (const k of itadKeysForGame(g)) {
    if (state.itadPriceDroppedKeys.has(k)) return true;
  }
  return false;
}

export function dealDroppedBadgeHtml(g) {
  return itadPriceDropped(g)
    ? '<span class="deal-badge-drop" title="Price dropped since your last ITAD refresh">↓ dropped</span>'
    : "";
}

export function ownedElsewhereBadgeHtml(g) {
  return isOwnedByTitle(g.name)
    ? '<span class="owned-elsewhere-pill" title="You already own this (matched by title in your library)">owned</span>'
    : "";
}

export function dealLowBadgeHtml(d) {
  if (!d) return "";
  if (d.lowKind === "all" || (d.isHistoricalLow && !d.isHistoricalLowYear)) {
    return '<span class="deal-badge-low" title="Lowest recorded price (all-time)">★ all-time</span>';
  }
  if (d.lowKind === "year" || d.isHistoricalLowYear) {
    return '<span class="deal-badge-low deal-badge-low-year" title="Lowest price in the past year">★ 1yr low</span>';
  }
  if (d.isHistoricalLow) {
    return '<span class="deal-badge-low" title="Historical low">★ low</span>';
  }
  return "";
}

/** Compact star-only variant for the library/wishlist price column. Mirrors
 *  the dashboard steals-row visual (small amber star, tooltip carries the
 *  meaning) so the cell stays narrow. */
export function priceLowStarHtml(d) {
  if (!d) return "";
  const allTime = d.lowKind === "all" || (d.isHistoricalLow && !d.isHistoricalLowYear);
  const yearLow = d.lowKind === "year" || d.isHistoricalLowYear;
  if (allTime) return '<span class="price-low-star" title="Lowest recorded price (all-time)">★</span>';
  if (yearLow) return '<span class="price-low-star price-low-star-year" title="Lowest price in the past year">★</span>';
  if (d.isHistoricalLow) return '<span class="price-low-star" title="Historical low">★</span>';
  return "";
}

export function applyItadPriceSnapshot(prevByKey, nextByKey) {
  state.itadPriceDroppedKeys = new Set();
  for (const [key, n] of Object.entries(nextByKey || {})) {
    const p = prevByKey?.[key];
    if (!p || n?.price == null || p.price == null) continue;
    if (n.price < p.price - 0.009) state.itadPriceDroppedKeys.add(key);
  }
}

export function slimItadSnapshot(byKey) {
  const slim = {};
  for (const [k, v] of Object.entries(byKey || {})) {
    if (v?.price != null) slim[k] = { price: v.price, cut: v.cut || 0 };
  }
  return slim;
}

export function parsePriceLike(v) {
  if (v == null) return null;
  if (typeof v === "number") return v;
  const m = String(v).match(/-?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

/** Numeric store price for sort/filter — prefers FX-converted price_amount from fetch. */
export function gameComparablePrice(g) {
  if (g?.price_amount != null) {
    const n = Number(g.price_amount);
    if (Number.isFinite(n)) return n;
  }
  return parsePriceLike(g.price);
}

function gameComparableRegularPrice(g) {
  if (g?.price_amount_initial != null) {
    const n = Number(g.price_amount_initial);
    if (Number.isFinite(n)) return n;
  }
  return parsePriceLike(g.price_initial);
}

// Returns unified deal info for a game. ITAD is preferred (cross-store best price);
// Steam discount is the fallback. Manual wishlist entries can supply price/discount.
export function getDealInfo(g) {
  const itad = getItadForGame(g);
  if (itad && itad.price != null) {
    const isAllTime = !!itad.is_historical_low;
    const isYear = !!itad.is_historical_low_year;
    return {
      source: "itad",
      price: itad.price,
      regular: itad.regular,
      cut: itad.cut || 0,
      isHistoricalLow: isAllTime || isYear,
      isHistoricalLowYear: isYear,
      lowKind: isAllTime ? "all" : isYear ? "year" : null,
      shop: itad.shop,
      url: itad.url,
    };
  }
  const steamPrice = gameComparablePrice(g);
  const steamRegular = gameComparableRegularPrice(g);
  const cut = g.discount_percent || 0;
  if (steamPrice != null || cut) {
    return {
      source: "steam",
      price: steamPrice,
      regular: steamRegular,
      cut,
      isHistoricalLow: false,
      shop: "Steam",
      url: g.store_url || null,
    };
  }
  return null;
}

const DEAL_SHOP_SHORT = {
  "steam": "Steam",
  "gog": "GOG",
  "humble store": "Humble",
  "humble": "Humble",
  "fanatical": "Fanatical",
  "greenmangaming": "GMG",
  "green man gaming": "GMG",
  "indiegala": "IndieGala",
  "indie gala": "IndieGala",
  "microsoft store": "Microsoft",
  "epic games store": "Epic",
  "epic": "Epic",
  "ubisoft store": "Ubisoft",
  "ubisoft connect": "Ubisoft",
  "ea app": "EA",
  "origin": "Origin",
  "gamersgate": "GamersGate",
  "gamesplanet": "GamesPlanet",
  "battle.net": "Battle.net",
  "nintendo eshop": "Nintendo",
  "playstation store": "PSN",
  "wingamestore": "WGS",
  "dlgamer": "DLGamer",
};

export function dealShopShort(shop) {
  if (!shop) return "";
  const k = String(shop).trim().toLowerCase();
  if (DEAL_SHOP_SHORT[k]) return DEAL_SHOP_SHORT[k];
  return shop.length > 10 ? shop.slice(0, 10) + "…" : shop;
}

export function shopSlug(shop) {
  const short = dealShopShort(shop);
  return String(short || shop || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
}

export function effectiveDiscountPercent(g) {
  const d = getDealInfo(g);
  if (d) return d.cut || 0;
  return g.discount_percent || 0;
}

export function effectiveSortPrice(g) {
  const d = getDealInfo(g);
  if (d && d.price != null) return d.price;
  return gameComparablePrice(g);
}

export function dealScore(g) {
  const d = getDealInfo(g);
  if (!d) return -Infinity;
  const cut = d.cut || 0;
  const lowBonus = d.isHistoricalLow ? 25 : 0;
  const rating = ratingValue(g);
  const ratingBonus = rating >= 90 ? 15 : rating >= 80 ? 10 : rating >= 70 ? 5 : 0;
  const ownedPenalty = isOwnedByTitle(g.name) ? 1000 : 0;
  const pricePenalty = d.price != null ? Math.max(0, d.price - 30) * 0.5 : 0;
  return cut + lowBonus + ratingBonus - ownedPenalty - pricePenalty;
}

export function passesDealFilters(g) {
  if (state.prefs.dealHideOwned && isOwnedByTitle(g.name)) return false;
  const d = getDealInfo(g);
  const onSale = state.prefs.dealOnSaleOnly;
  const lowOnly = state.prefs.dealHistoricalLowOnly;
  const minCut = +(state.prefs.dealMinDiscount || 0);
  const maxPrice = +(state.prefs.dealMaxPrice ?? 100);
  if (onSale && (!d || (d.cut || 0) <= 0)) return false;
  if (lowOnly && !(d && d.isHistoricalLow)) return false;
  if (minCut > 0 && (!d || (d.cut || 0) < minCut)) return false;
  if (maxPrice < 100) {
    if (!d) return false;
    if (d.price == null) {
      // Manual wishlist with a discount but no price still passes max-price filter.
      if (g.manual && (d.cut || 0) > 0) return true;
      return false;
    }
    if (d.price > maxPrice) return false;
  }
  return true;
}
