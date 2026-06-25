/**
 * Active filter pill descriptors — DOM-free so table-ui and debug-overlay
 * can read filter state without importing filters-ui (breaks circular imports).
 */

import { state, STATUS_FILTER_LABELS } from './state.js';
import { WISHLIST_STATUS_LABELS } from './row-templates.js';
import { getCoopFilterMode, COOP_FILTER_LABELS } from './prefs.js';
import { formatMoney, displayCurrency } from './currency.js';

export function collectActiveFilters() {
  const pills = [];
  const sp = state.sessionPrefs || {};
  const q = String(sp.search || "").trim();
  if (q) pills.push({ kind: "search", value: q, label: `Search: ${q}` });
  if (state.activeView === "library" || state.activeView === "itch") {
    const status = sp.statusFilter || "";
    if (status) pills.push({ kind: "status", value: status, label: `Status: ${STATUS_FILTER_LABELS[status] || status}` });
  } else if (state.activeView === "wishlist") {
    const status = sp.statusFilter || "";
    if (status) {
      const label = WISHLIST_STATUS_LABELS[status] || STATUS_FILTER_LABELS[status] || status;
      pills.push({ kind: "status", value: status, label: `Status: ${label}` });
    }
  }
  if (state.prefs.storeFilter) pills.push({ kind: "store", value: state.prefs.storeFilter, label: `Store: ${state.prefs.storeFilter}` });
  if (state.activeView === "library" && state.prefs.releaseYearFilter) {
    pills.push({ kind: "releaseYear", value: state.prefs.releaseYearFilter, label: `Released: ${state.prefs.releaseYearFilter}` });
  }
  if (state.activeView === "library" && state.prefs.customListFilter != null) {
    const lists = state.prefs.customLists || [];
    const idx = Number(state.prefs.customListFilter);
    const name = lists[idx]?.name || `List ${idx + 1}`;
    pills.push({ kind: "customList", value: String(idx), label: `List: ${name}` });
  }
  if (state.activeView === "wishlist" && state.prefs.wishlistStoreFilter) {
    const labelMap = { steam: "Steam", gog: "GOG", epic: "Epic", psn: "PlayStation", ubisoft: "Ubisoft" };
    const v = state.prefs.wishlistStoreFilter;
    pills.push({ kind: "wishlistStore", value: v, label: `Wishlist source: ${labelMap[v] || v}` });
  }
  for (const g of state.prefs.genreFilters || []) pills.push({ kind: "genre", value: g, label: g });
  if (sp.unplayedOnly) pills.push({ kind: "unplayed", value: "1", label: "Unplayed only" });
  if (sp.earlyAccessOnly) pills.push({ kind: "earlyAccess", value: "1", label: "Early Access only" });
  if (sp.staleOnly) pills.push({ kind: "stale", value: "1", label: "Stale sync only" });
  const coopMode = getCoopFilterMode();
  if (coopMode !== "off") {
    pills.push({ kind: "coop", value: coopMode, label: COOP_FILTER_LABELS[coopMode] || coopMode });
  }
  const minR = +(sp.minRating || 0);
  if (minR > 0) pills.push({ kind: "minRating", value: String(minR), label: `Rating ≥ ${minR}%` });
  const maxH = sp.maxHours == null ? 200 : +sp.maxHours;
  if (maxH < 200) pills.push({ kind: "maxHours", value: String(maxH), label: `HLTB ≤ ${maxH}h` });
  if (state.prefs.hltbBucket != null) {
    const labels = ["0–2h", "2–5h", "5–10h", "10–20h", "20–40h", "40h+"];
    const lbl = labels[state.prefs.hltbBucket];
    if (lbl) pills.push({ kind: "hltbBucket", value: String(state.prefs.hltbBucket), label: `HLTB ${lbl}` });
  }
  if (state.cleanupModeActive && state.activeView === "library") pills.push({ kind: "cleanup", value: "1", label: "Cleanup mode" });
  if (state.activeView === "itch" && state.sessionPrefs.itchHideNonGames) pills.push({ kind: "itchHideNonGames", value: "1", label: "Hide tools, soundtracks, etc." });
  if (state.sessionPrefs.crossStoreDedup && state.allGames.length > 0) pills.push({ kind: "dedup", value: "1", label: "Hide duplicates" });
  if (state.activeView === "wishlist") {
    if (state.prefs.dealOnSaleOnly) pills.push({ kind: "dealOnSale", value: "1", label: "On sale only" });
    if (state.prefs.dealHistoricalLowOnly) pills.push({ kind: "dealLow", value: "1", label: "Historical low only" });
    if (state.prefs.dealHideOwned) pills.push({ kind: "dealHideOwned", value: "1", label: "Hide owned" });
    if (+state.prefs.dealMinDiscount > 0) pills.push({ kind: "dealMinDiscount", value: String(state.prefs.dealMinDiscount), label: `Discount ≥ ${state.prefs.dealMinDiscount}%` });
    if (+state.prefs.dealMaxPrice < 100) {
      pills.push({
        kind: "dealMaxPrice",
        value: String(state.prefs.dealMaxPrice),
        label: `Price ≤ ${formatMoney(state.prefs.dealMaxPrice, displayCurrency(), { maximumFractionDigits: 0, minimumFractionDigits: 0 })}`,
      });
    }
  }
  return pills;
}
