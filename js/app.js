import {
  state,
  STORAGE_KEY,
  PREFS_KEY,
  MANUAL_KEY,
  CLEANUP_MAX_RATING,
  CLEANUP_MIN_AGE_MS,
  GENRE_CHIP_COLLAPSE_AT,
  GENRE_ALIASES,
  ITCH_NON_GAME_CLASSIFICATIONS,
  STATUS_CHIP_DEFS,
  WISHLIST_STATUS_CHIP_DEFS,
  STATUS_FILTER_LABELS,
} from './state.js';
import { collectTableParams, isEarlyAccess, queryGamesAsync } from './table-query.js';
import {
  shouldVirtualize,
  virtualRange,
  virtualRangeAroundIndex,
  tableVirtualMetrics,
  TABLE_ROW_HEIGHT,
  setMeasuredRowHeight,
  measuredRowHeight,
} from './virtual-table.js';
import { buildStatusSelect, STATUS_LABELS, WISHLIST_STATUS_LABELS } from './row-templates.js';
import { createMemo } from './memo.js';

import { escapeHtml, escapeAttr, formatNum } from './dom-util.js';
import { personalStore, configurePersonalStore, showMigrationBanner } from './personal-store.js';
import { fetcherRunner, loadFetcherSources, renderDashboardFetcherHealth, configureFetcherHealth, consumeItadAutoRunFlag, diffItadDeals } from './fetcher-health.js';
import { initConnections, refreshConnections, startConnectionsPolling, stopConnectionsPolling } from './connections.js';
import {
  initDashboard,
  scheduleDashboardRender,
  cancelScheduledDashboardRender,
  destroyDashboardCharts,
  dashboardLibraryGames,
  dashDrillCoop,
} from './dashboard.js';

const personalMemo = createMemo();

function hydrateState() {
  state.personal = loadPersonal();
  state.prefs = loadPrefs();
}

// === Constants & config ===
const STORE_PRIORITY = ["steam", "psn", "gog", "epic", "amazon", "nintendo", "itch", "xbox", "battlenet", "ubisoft", "other", "manual"];
const JUNK_NAMES = new Set(["live", "fortnite"]);
const JUNK_NAME_PATTERNS = [
  /\btech beta\b/i,
  /\b(pre[- ]game )?editor\b/i,
  /\bresource archiver\b/i,
  /\bbeta\b$/i,
];

// === Game normalization & dedup ===
function storePriority(store) {
  const idx = STORE_PRIORITY.indexOf(store);
  return idx === -1 ? STORE_PRIORITY.length : idx;
}

function normalizeNameForDedup(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[\u2122\u00ae\u00a9]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|of the year|game of the year|special|standard|deluxe|collection|anthology|pack|the)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isJunkEntry(g) {
  const raw = String(g.name || "").trim();
  if (!raw) return true;
  const lower = raw.toLowerCase();
  if (JUNK_NAMES.has(lower)) return true;
  return JUNK_NAME_PATTERNS.some(re => re.test(raw));
}

function dedupeWithinStore(games) {
  const byKey = new Map();
  for (const g of games) {
    if (isJunkEntry(g)) continue;
    const ng = normalizeGame(g);
    const key = `${ng.store}:${ng.id}`;
    const existing = byKey.get(key);
    if (!existing || scoreEntry(g) > scoreEntry(existing)) byKey.set(key, g);
  }
  const byNorm = new Map();
  const noNameOut = [];
  for (const g of byKey.values()) {
    const ng = normalizeGame(g);
    const norm = normalizeNameForDedup(g.name);
    if (!norm) { noNameOut.push(g); continue; }
    const composite = `${ng.store}::${norm}`;
    const existing = byNorm.get(composite);
    if (!existing || scoreEntry(g) > scoreEntry(existing)) byNorm.set(composite, g);
  }
  return [...byNorm.values(), ...noNameOut];
}

function scoreEntry(g) {
  let s = 0;
  if (g.header_image) s += 4;
  if (g.library_image) s += 2;
  if (g.hltb_main_hours) s += 2;
  if (g.steam_review_percent != null) s += 2;
  if (g.release_date) s += 1;
  if ((g.genres || []).length) s += 1;
  if (g.playtime_minutes) s += 1;
  return s;
}

function recomputeCrossStoreHidden() {
  state.crossStoreHiddenKeys = new Set();
  state.crossStoreOwnedStores = new Map();
  const groups = new Map();
  for (const g of state.allGames) {
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    if (!groups.has(norm)) groups.set(norm, []);
    groups.get(norm).push(g);
  }
  for (const [, list] of groups) {
    if (list.length < 2) continue;
    list.sort((a, b) => {
      const pa = storePriority(normalizeGame(a).store);
      const pb = storePriority(normalizeGame(b).store);
      if (pa !== pb) return pa - pb;
      return scoreEntry(b) - scoreEntry(a);
    });
    const orderedStores = [];
    for (const g of list) {
      const s = normalizeGame(g).store;
      if (!orderedStores.includes(s)) orderedStores.push(s);
    }
    if (orderedStores.length > 1) {
      state.crossStoreOwnedStores.set(gameKey(list[0]), orderedStores);
    }
    if (state.prefs.crossStoreDedup) {
      for (let i = 1; i < list.length; i++) {
        state.crossStoreHiddenKeys.add(gameKey(list[i]));
      }
    }
  }
  recomputeWishlistCrossStore();
}

function wishlistEntryStore(g) {
  return g.wishlist_store || g.store_target || (g.manual ? "manual" : "steam");
}

function recomputeWishlistCrossStore() {
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.wishlistCrossStoreOwnedStores = new Map();
  const groups = new Map();
  for (const g of state.wishlistGames) {
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    if (!groups.has(norm)) groups.set(norm, []);
    groups.get(norm).push(g);
  }
  for (const [, list] of groups) {
    if (list.length < 2) continue;
    list.sort((a, b) => {
      const pa = storePriority(wishlistEntryStore(a));
      const pb = storePriority(wishlistEntryStore(b));
      if (pa !== pb) return pa - pb;
      return scoreEntry(b) - scoreEntry(a);
    });
    const orderedStores = [];
    for (const g of list) {
      const s = wishlistEntryStore(g);
      if (!orderedStores.includes(s)) orderedStores.push(s);
    }
    if (orderedStores.length > 1) {
      state.wishlistCrossStoreOwnedStores.set(gameKey(list[0]), orderedStores);
    }
    if (state.prefs.crossStoreDedup) {
      for (let i = 1; i < list.length; i++) {
        state.wishlistCrossStoreHiddenKeys.add(gameKey(list[i]));
      }
    }
  }
}

window.__dashFailedCovers = window.__dashFailedCovers || new Set();
let _dashRebalanceTimer = null;
function scheduleDashRebalance() {
  clearTimeout(_dashRebalanceTimer);
  _dashRebalanceTimer = setTimeout(() => {
    window.dispatchEvent(new CustomEvent("dash:cover-failures"));
  }, 600);
}
window.coverFallback = function (img) {
  const fb = img.dataset.fallback;
  if (fb && img.src !== fb) {
    img.src = fb;
    img.dataset.fallback = "";
    return;
  }
  const dashRow = img.closest(".dash-versus-row, .dash-list-row, .coop-pick-row, .dash-spotlight, .itch-hero-card");
  if (dashRow) {
    const key = dashRow.dataset.key || dashRow.dataset.gameKey;
    if (key) {
      window.__dashFailedCovers.add(key);
      scheduleDashRebalance();
    }
    dashRow.style.display = "none";
    return;
  }
  const name = img.dataset.name || "";
  const cls = img.classList.contains("pick-cover") ? "pick-cover placeholder" : "cover placeholder";
  const words = name.split(/\s+/).filter(Boolean);
  const initials = (words.slice(0, 3).map(w => w[0]).join("") || "?").toUpperCase().slice(0, 3);
  const captionRaw = words.slice(0, 4).join(" ").slice(0, 28);
  const safeName = name.replace(/"/g, "&quot;");
  const safeCap = captionRaw.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  img.outerHTML = `<div class="${cls}" title="${safeName}"><span class="placeholder-initials">${initials}</span><span class="placeholder-caption">${safeCap}</span></div>`;
};
const LANDSCAPE_CACHE_KEY = "baklog-landscape-covers";
window.__landscapeCovers = (() => {
  try { return new Set(JSON.parse(localStorage.getItem(LANDSCAPE_CACHE_KEY) || "[]")); }
  catch { return new Set(); }
})();
let _landscapeSaveTimer = 0;
function persistLandscapeCache() {
  if (_landscapeSaveTimer) return;
  _landscapeSaveTimer = setTimeout(() => {
    _landscapeSaveTimer = 0;
    try { localStorage.setItem(LANDSCAPE_CACHE_KEY, JSON.stringify([...window.__landscapeCovers].slice(-1500))); } catch {}
  }, 800);
}
window.coverLandscapeAttr = function (url) {
  return url && window.__landscapeCovers.has(url) ? " landscape" : "";
};
window.markLandscape = function (img) {
  if (!img?.classList) return;
  const isLandscape = !!(img.naturalWidth && img.naturalHeight && img.naturalWidth > img.naturalHeight * 1.1);
  img.classList.toggle("landscape", isLandscape);
  const wrap = img.closest(".cover-wrap");
  if (wrap) wrap.classList.toggle("landscape", isLandscape);
  const src = img.currentSrc || img.src;
  if (src) {
    const had = window.__landscapeCovers.has(src);
    if (isLandscape && !had) { window.__landscapeCovers.add(src); persistLandscapeCache(); }
    else if (!isLandscape && had) { window.__landscapeCovers.delete(src); persistLandscapeCache(); }
  }
};

/** Virtual scroll rebuilds rows from HTML; cached images often skip inline onload. */
function syncCoverFits(root) {
  if (!root?.querySelectorAll) return;
  for (const img of root.querySelectorAll("img.cover, img.pick-cover, img.deal-hero-cover")) {
    if (img.complete && img.naturalWidth > 0) window.markLandscape(img);
    else img.addEventListener("load", () => window.markLandscape(img), { once: true });
  }
}

// === Storage ===
function loadPersonal() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch { return {}; }
}
function migrateV3() {
  if (state.personal.__migrated_v3) return;
  const next = {};
  for (const [k, v] of Object.entries(state.personal)) {
    if (k === "__migrated_v3") continue;
    if (String(k).includes(":")) next[k] = v;
    else next[`steam:${k}`] = v;
  }
  next.__migrated_v3 = true;
  state.personal = next;
  savePersonal();
}
let _savePersonalTimer = null;
function savePersonal() {
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = setTimeout(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state.personal));
    personalStore.notify();
  }, 250);
}
function flushSavePersonal() {
  if (!_savePersonalTimer) return;
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = null;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.personal));
  personalStore.notify();
}
window.addEventListener("beforeunload", flushSavePersonal);
window.addEventListener("blur", flushSavePersonal);
window.addEventListener("dash:cover-failures", () => {
  if (state.activeView === "dashboard") scheduleDashboardRender();
});
function loadPrefs() {
  const fallback = { picksTab: "topRated", libraryPicksTab: "topRated", itchPicksTab: "topRated", itchHideNonGames: true, picksCollapsed: false, showScoreColumn: false, genreFilters: [], genreFilterMode: "OR", quickWinMaxHours: 15, storeFilter: "", wishlistStoreFilter: "", crossStoreDedup: true, picksLimit: 16, tagFilters: [], tagFilterMode: "OR", dealOnSaleOnly: false, dealHistoricalLowOnly: false, dealHideOwned: false, dealMinDiscount: 0, dealMaxPrice: 100, viewSorts: {}, fetcherHealthStaleOnly: false };
  try { return { ...fallback, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}")) }; } catch { return fallback; }
}
function savePrefs() {
  localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs));
  personalStore.notify();
}

const VIEW_SORT_DEFAULTS = {
  library: { key: "name", dir: 1 },
  wishlist: { key: "deal_price", dir: 1 },
  itch: { key: "name", dir: 1 },
};

function getSavedSortForView(view) {
  const def = VIEW_SORT_DEFAULTS[view];
  if (!def) return null;
  const saved = state.prefs.viewSorts && state.prefs.viewSorts[view];
  if (saved && typeof saved.key === "string" && (saved.dir === 1 || saved.dir === -1)) {
    return { key: saved.key, dir: saved.dir };
  }
  return { ...def };
}

function applySavedSortForView(view) {
  const s = getSavedSortForView(view);
  if (!s) return;
  state.sortKey = s.key;
  state.sortDir = s.dir;
}

function persistCurrentSort() {
  if (!VIEW_SORT_DEFAULTS[state.activeView]) return;
  if (!state.prefs.viewSorts || typeof state.prefs.viewSorts !== "object") {
    state.prefs.viewSorts = {};
  }
  state.prefs.viewSorts[state.activeView] = { key: state.sortKey, dir: state.sortDir };
  savePrefs();
}
function loadManualGames() {
  try {
    const raw = JSON.parse(localStorage.getItem(MANUAL_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}
function saveManualGames(list) {
  localStorage.setItem(MANUAL_KEY, JSON.stringify(list));
  personalStore.notify();
}
let manualGames = loadManualGames();
function addManualGame(g) {
  manualGames = loadManualGames();
  const dupIdx = manualGames.findIndex(m => m.id === g.id && m.store === g.store);
  if (dupIdx >= 0) manualGames[dupIdx] = g;
  else manualGames.push(g);
  saveManualGames(manualGames);
}
configurePersonalStore({
  getManualGames: loadManualGames,
  setManualGames: (list) => { manualGames = list; },
});

function removeManualGame(store, id) {
  manualGames = loadManualGames().filter(m => !(m.store === store && m.id === id));
  saveManualGames(manualGames);
}

function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  const store = g.store || "steam";
  const id = g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
  return { ...g, store, id };
}
function gameStore(g) {
  return g.store || "steam";
}
function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
}
function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}
function gameNumericId(g) {
  return gameId(g);
}
function coverFallbackFor(g) {
  const ng = normalizeGame(g);
  if (ng.header_image) return ng.header_image;
  if (ng.store === "steam") return `https://cdn.akamai.steamstatic.com/steam/apps/${ng.id}/header.jpg`;
  return "";
}
const EPIC_PUBLIC_SLUG = /^[a-z0-9][a-z0-9-]*$/;
const GENERIC_STORE_URLS = new Set([
  "https://gaming.amazon.com/home",
  "https://gaming.amazon.com/home/",
]);
function isEpicPublicSlug(slug) {
  return EPIC_PUBLIC_SLUG.test(String(slug || "").trim());
}
function isGenericStoreUrl(url) {
  if (!url) return true;
  const u = String(url).trim().replace(/\/$/, "");
  return GENERIC_STORE_URLS.has(u) || u === "https://gaming.amazon.com/home";
}
function storeUrlForGame(g) {
  const ng = normalizeGame(g);
  let url = (ng.store_url || "").trim();
  if (ng.store === "gog" && url.startsWith("/")) {
    return "https://www.gog.com" + url;
  }
  if (url && url.startsWith("http") && !isGenericStoreUrl(url)) {
    if (ng.store === "epic" && url.includes("/p/")) {
      const slug = url.split("/p/").pop()?.split(/[?#]/)[0] || "";
      if (isEpicPublicSlug(slug)) return url;
    } else {
      return url;
    }
  }
  if (ng.store === "steam" && ng.id != null) {
    return `https://store.steampowered.com/app/${ng.id}/`;
  }
  if (ng.store === "gog" && ng.gog_id) {
    return `https://www.gog.com/en/game/${ng.gog_id}`;
  }
  if (ng.store === "psn" && ng.concept_id) {
    return `https://store.playstation.com/en-us/concept/${ng.concept_id}`;
  }
  if (ng.store === "epic") {
    return `https://store.epicgames.com/en-US/browse?q=${encodeURIComponent(ng.name || "")}`;
  }
  if (ng.store === "amazon") {
    if (ng.asin) return `https://www.amazon.com/dp/${ng.asin}`;
    return `https://www.amazon.com/s?k=${encodeURIComponent(ng.name || "")}&i=videogames`;
  }
  if (ng.store === "itch" && ng.itch_slug) {
    return `https://itch.io/${ng.itch_slug}`;
  }
  if (ng.store === "xbox") {
    if (url && url.startsWith("http")) return url;
    const tid = ng.xbox_title_id ?? ng.id;
    if (tid) return `https://www.xbox.com/en-us/games/store/_/${tid}`;
    return `https://www.xbox.com/en-us/search/results?q=${encodeURIComponent(ng.name || "")}`;
  }
  if (ng.store === "battlenet") {
    if (url && url.startsWith("http")) return url;
    return `https://shop.battle.net/?search=${encodeURIComponent(ng.name || "")}`;
  }
  if (ng.store === "ubisoft") {
    if (url && url.startsWith("http")) return url;
    return `https://store.ubisoft.com/us/search?q=${encodeURIComponent(ng.name || "")}`;
  }
  return url && url.startsWith("http") && !isGenericStoreUrl(url) ? url : null;
}
function storeLinkHtml(g, className, labelHtml) {
  const url = storeUrlForGame(g);
  if (!url) return `<span class="${className}">${labelHtml}</span>`;
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener" class="${className}">${labelHtml}</a>`;
}
const PERSONAL_DEFAULT = { status: "backlog", notes: "", priority: 0, hltb_override: null, tags: [] };
const PERSONAL_EMPTY = Object.freeze({ status: "backlog", notes: "", priority: 0, hltb_override: null, tags: Object.freeze([]) });
function getPersonal(g) {
  const key = gameKey(g);
  const ver = window._dataVersion || 0;
  return personalMemo.get(`${key}:${ver}`, () => {
    const found = state.personal[key] || (typeof state.personal[gameId(g)] === "object" ? state.personal[gameId(g)] : null);
    if (!found) return PERSONAL_EMPTY;
    if (found.status == null) found.status = "backlog";
    if (found.notes == null) found.notes = "";
    if (found.priority == null) found.priority = 0;
    if (found.hltb_override === undefined) found.hltb_override = null;
    if (!Array.isArray(found.tags)) found.tags = [];
    return found;
  });
}
let _downstreamSyncTimer = null;
function scheduleDownstreamSync() {
  clearTimeout(_downstreamSyncTimer);
  _downstreamSyncTimer = setTimeout(() => {
    renderSummary();
    if (state.activeView === "dashboard") scheduleDashboardRender();
    else renderPicks();
  }, 200);
}
function setPersonal(g, field, value, options) {
  const key = gameKey(g);
  if (!state.personal[key]) state.personal[key] = { ...PERSONAL_DEFAULT, tags: [] };
  if (!Array.isArray(state.personal[key].tags)) state.personal[key].tags = [];
  state.personal[key][field] = value;
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  savePersonal();
  if (options?.silent) return;
  scheduleDownstreamSync();
}
function normalizeTag(t) {
  return String(t || "").trim().toLowerCase().replace(/\s+/g, " ").slice(0, 32);
}
function addTagToGame(g, raw) {
  const tag = normalizeTag(raw);
  if (!tag) return false;
  const cur = getPersonal(g).tags;
  if (cur.includes(tag)) return false;
  setPersonal(g, "tags", [...cur, tag].sort());
  return true;
}
function removeTagFromGame(g, tag) {
  const cur = getPersonal(g).tags;
  if (!cur.includes(tag)) return false;
  setPersonal(g, "tags", cur.filter(x => x !== tag));
  return true;
}
function allPersonalTags() {
  const counts = new Map();
  for (const v of Object.values(state.personal)) {
    if (!v || typeof v !== "object" || !Array.isArray(v.tags)) continue;
    for (const t of v.tags) counts.set(t, (counts.get(t) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
function hltbMain(g) {
  const p = getPersonal(g);
  if (p.hltb_override != null && p.hltb_override !== "") return +p.hltb_override;
  return g.hltb_main_hours;
}
function ratingValue(g) { return g.steam_review_percent ?? 0; }
const MIN_REVIEW_COUNT = 50;
function hasEnoughReviews(g) {
  const pct = g.steam_review_percent;
  if (pct != null && pct > 0) return (g.steam_review_count || 0) >= MIN_REVIEW_COUNT;
  return false;
}
function priorityScore(g) {
  const review = ratingValue(g);
  const h = hltbMain(g) || 20;
  return review / Math.log2(h + 2);
}
function isHiddenGem(g) {
  const p = getPersonal(g);
  const rating = g.steam_review_percent ?? 0;
  return rating >= 90 && (g.playtime_minutes || 0) === 0 && p.status === "backlog";
}
function earlyAccessRibbonHtml(g, { label = "EARLY ACCESS" } = {}) {
  return isEarlyAccess(g) ? `<span class="ea-ribbon" title="Early Access">${label}</span>` : "";
}
function earlyAccessPillHtml(g) {
  return isEarlyAccess(g) ? '<span class="ea-pill" title="Early Access">EA</span>' : "";
}
function coopPillsHtml(g) {
  if (!g) return "";
  const bits = [];
  if (g.coop_online) bits.push('<span class="coop-pill coop-pill-online" title="Online co-op">ONLINE CO-OP</span>');
  if (g.coop_local) bits.push('<span class="coop-pill coop-pill-local" title="Shared / split-screen co-op">COUCH CO-OP</span>');
  return bits.join("");
}
function storeLetter(s) {
  return s === "gog" ? "G" : s === "psn" ? "P" : s === "epic" ? "E" : s === "amazon" ? "A" : s === "nintendo" ? "N" : s === "itch" ? "I" : s === "xbox" ? "X" : s === "battlenet" ? "B" : s === "ubisoft" ? "U" : s === "other" ? "?" : s === "manual" ? "M" : "S";
}
function singleStoreBadgeHtml(s, title) {
  return `<span class="store-badge ${s}" title="${title || s.toUpperCase()}">${storeLetter(s)}</span>`;
}
function storeBadgeHtml(g) {
  const primary = normalizeGame(g).store;
  const owned = state.crossStoreOwnedStores.get(gameKey(g));
  if (!owned || owned.length < 2) return singleStoreBadgeHtml(primary);
  const tip = `Owned on: ${owned.map(s => s.toUpperCase()).join(", ")}`;
  return `<span class="inline-flex items-center gap-0.5 align-middle" title="${tip}">${owned.map(s => singleStoreBadgeHtml(s, tip)).join("")}</span>`;
}
function wishlistStatusSelectHtml(g, p) {
  const key = gameKey(g);
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="bg-slate-700 border border-slate-600 rounded text-xs py-1" title="Wishlist tracking">
    ${Object.entries(WISHLIST_STATUS_LABELS).map(([val, label]) => `<option value="${val}" ${p.status === val ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
  </select>`;
}

function bulkStatusOptsForView(view) {
  const labels = view === "wishlist" ? WISHLIST_STATUS_LABELS : STATUS_LABELS;
  return Object.entries(labels).map(([status, label]) => ({ status, label }));
}

function renderBulkStatusButtons() {
  const wrap = document.getElementById("bulkStatusButtons");
  if (!wrap) return;
  if (state.activeView === "dashboard") {
    wrap.innerHTML = "";
    return;
  }
  wrap.innerHTML = bulkStatusOptsForView(state.activeView).map(
    ({ status, label }) => `<button type="button" class="bulk-status px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs" data-status="${escapeAttr(status)}">${escapeHtml(label)}</button>`,
  ).join("");
}

function tableColSpan() {
  return state.prefs.showScoreColumn ? 14 : 13;
}

function wishlistBadgeHtml(g) {
  const target = wishlistEntryStore(g);
  const manualMark = g.manual ? " manual" : "";
  const owned = state.wishlistCrossStoreOwnedStores.get(gameKey(g));
  if (owned && owned.length > 1) {
    const tip = `Wishlisted on: ${owned.map(s => s.toUpperCase()).join(", ")}`;
    return `<span class="inline-flex items-center gap-0.5 align-middle" title="${tip}">${owned.map(s => singleStoreBadgeHtml(s, tip)).join("")}</span>`;
  }
  const tip = `Wishlist · ${target.toUpperCase()}${g.manual ? " (manual)" : ""}`;
  return `<span class="store-badge ${target}${manualMark}" title="${tip}">${storeLetter(target)}</span>`;
}
function formatHours(minutes) { return !minutes ? "0h" : `${(minutes / 60).toFixed(1)}h`; }
function formatDate(unixOrStr) {
  if (!unixOrStr) return "—";
  if (typeof unixOrStr === "number") return unixOrStr === 0 ? "—" : new Date(unixOrStr * 1000).toLocaleDateString();
  return unixOrStr;
}
function parseReleaseForSort(d) { const t = Date.parse(d || ""); return isNaN(t) ? 0 : t; }
const RELEASE_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function formatReleaseDate(d) {
  if (!d) return "—";
  const s = String(d).trim();
  if (!s) return "—";
  const iso = s.match(/^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?/);
  if (iso) {
    const y = iso[1];
    const m = Number(iso[2]);
    const day = iso[3] ? Number(iso[3]) : null;
    if (m >= 1 && m <= 12) {
      return day ? `${RELEASE_MONTHS[m - 1]} ${day}, ${y}` : `${RELEASE_MONTHS[m - 1]} ${y}`;
    }
    return y;
  }
  const t = Date.parse(s);
  if (!isNaN(t)) {
    const dt = new Date(t);
    return `${RELEASE_MONTHS[dt.getUTCMonth()]} ${dt.getUTCDate()}, ${dt.getUTCFullYear()}`;
  }
  if (/^\d{4}$/.test(s)) return s;
  return s;
}

function formatDollar(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "—";
  return num.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: num % 1 ? 2 : 0, maximumFractionDigits: 2 });
}

function isStealDeal(g) {
  const d = getDealInfo(g);
  if (!d) return false;
  const cut = d.cut || 0;
  if (cut <= 0) return false;
  const rating = ratingValue(g);
  if (rating < 80) return false;
  return cut >= 50 || d.isHistoricalLow;
}

function wishlistGamesWithDeals(wl) {
  return wl.filter(g => {
    const d = getDealInfo(g);
    return d && (d.cut || 0) > 0;
  });
}

function syncDealFilterControls() {
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

function drillWishlistDealFilter({ onSaleOnly, minDiscount }) {
  if (onSaleOnly) state.prefs.dealOnSaleOnly = true;
  if (minDiscount != null) state.prefs.dealMinDiscount = minDiscount;
  syncDealFilterControls();
  savePrefs();
  if (state.activeView !== "wishlist") switchView("wishlist");
  else refreshFilterUI();
}

function dealHeroCardHtml(g) {
  const d = getDealInfo(g);
  const key = gameKey(g);
  const cover = g.library_image || coverFallbackFor(g);
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
    ? `<div class="deal-hero-genres">${genres.map(escapeHtml).join(" · ")}</div>`
    : "";
  const statStrip = (statPills.length || genreLine)
    ? `<div class="deal-hero-stats">
        ${statPills.length ? `<div class="deal-hero-stats-row">${statPills.join("")}</div>` : ""}
        ${genreLine}
      </div>`
    : "";
  const heroBadges = [];
  if (cut > 0) heroBadges.push(`<span class="deal-cut-badge">-${cut}%</span>`);
  if (lowPin) heroBadges.push(lowPin);
  if (droppedPin) heroBadges.push(droppedPin);
  const wlBadge = wishlistBadgeHtml(g);
  if (wlBadge) heroBadges.push(wlBadge);
  if (ownedPin) heroBadges.push(ownedPin);
  const heroBadgesHtml = heroBadges.slice(0, 4).join("");
  return `<button type="button" class="deal-card-clickable deal-hero dash-card text-left w-full" data-action="deal-hero" data-key="${escapeAttr(key)}" title="Jump to ${escapeAttr(g.name)} on wishlist">
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

function dealHeroEmptyHtml() {
  return `<div class="dash-card deal-hero-empty">
    <div class="dash-kpi-label">Today&apos;s top deal</div>
    <div class="text-sm text-slate-400 mt-3">No active deals — check back after the next ITAD refresh.</div>
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

function dealSaleScoreboardCardHtml({ onSaleCount, totalCount, avgCut, bestCut, bestCutGame, hasPricing, cuts }) {
  if (!hasPricing) {
    return `<button type="button" class="deal-card-clickable dash-card text-left w-full" data-action="deal-on-sale" title="Show wishlist items on sale">
      <div class="dash-kpi-label">Sale scoreboard</div>
      <div class="text-xs text-slate-400 mt-2">Run <code class="text-slate-300">fetch_itad.py</code> for cross-store sale stats.</div>
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
        <div class="sale-stat-value ${noSale ? "sale-stat-muted" : ""}">${noSale ? "—" : `-${avgCut}%`}</div>
      </div>
      <div class="sale-stat">
        <div class="sale-stat-label">Best cut</div>
        <div class="sale-stat-value ${noSale ? "sale-stat-muted" : "sale-stat-best"}">${noSale ? "—" : `-${bestCut}%`}</div>
        ${noSale ? "" : bestLabel}
      </div>
    </div>
    ${distHtml}
  </button>`;
}

function dealStealsCardHtml(steals) {
  if (!steals.length) {
    return `<button type="button" class="deal-card-clickable dash-card text-left w-full" data-action="deal-steals" title="Show wishlist steals (50%+ off, 80%+ rated)">
      <div class="dash-kpi-label">Steals waiting</div>
      <div class="text-xs text-slate-400 mt-1">50%+ off or historical low · 80%+ rated</div>
      <div class="text-xs text-slate-500 mt-3">No steals match right now.</div>
    </button>`;
  }
  const ranked = [...steals].sort((a, b) => dealScore(b) - dealScore(a));
  const shown = ranked.slice(0, 6);
  const remaining = ranked.length - shown.length;
  const rows = shown.map(g => {
    const cover = g.library_image || coverFallbackFor(g);
    const fb = coverFallbackFor(g);
    const d = getDealInfo(g) || {};
    const cut = d.cut || 0;
    const cutLabel = cut > 0 ? `-${cut}%` : "★";
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
      <span class="steal-row-cut">${cutLabel}</span>
      ${price}
    </button>`;
  }).join("");
  const footer = remaining > 0
    ? `<div class="steal-list-footer" data-action="deal-steals" title="Show all steals">+${remaining} more · view all →</div>`
    : `<div class="steal-list-footer" data-action="deal-steals" title="Show all steals on wishlist">View on wishlist →</div>`;
  return `<div class="dash-card steal-card" title="50%+ off or historical low · 80%+ rated">
    <div class="flex items-baseline justify-between gap-2">
      <div>
        <div class="dash-kpi-label">Steals waiting</div>
        <div class="text-[10px] text-slate-500 mt-0.5">50%+ off or historical low · 80%+ rated</div>
      </div>
      <div class="text-sm font-semibold text-slate-300">${steals.length}</div>
    </div>
    <div class="steal-list mt-2">${rows}</div>
    ${footer}
  </div>`;
}

function buildOwnedNormNames() {
  state.ownedNormNames = new Set();
  for (const g of state.allGames) {
    if (state.crossStoreHiddenKeys.has(gameKey(g))) continue;
    const n = normalizeNameForDedup(g.name);
    if (n) state.ownedNormNames.add(n);
  }
}

function isOwnedByTitle(name) {
  const n = normalizeNameForDedup(name);
  return n && state.ownedNormNames.has(n);
}

function isCleanupCandidate(g) {
  const p = getPersonal(g);
  if (p.status !== "backlog") return false;
  if ((g.playtime_minutes || 0) > 0) return false;
  const rating = ratingValue(g);
  if (rating > 0 && rating >= CLEANUP_MAX_RATING) return false;
  const released = parseReleaseForSort(g.release_date);
  if (!released) return true;
  return Date.now() - released >= CLEANUP_MIN_AGE_MS;
}

const ITAD_SNAPSHOT_KEY = "baklog-itad-snapshot";

function getItadForGame(g) {
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

function itadPriceDropped(g) {
  for (const k of itadKeysForGame(g)) {
    if (state.itadPriceDroppedKeys.has(k)) return true;
  }
  return false;
}

function dealDroppedBadgeHtml(g) {
  return itadPriceDropped(g)
    ? '<span class="deal-badge-drop" title="Price dropped since your last ITAD refresh">↓ dropped</span>'
    : "";
}

function ownedElsewhereBadgeHtml(g) {
  return isOwnedByTitle(g.name)
    ? '<span class="owned-elsewhere-pill" title="You already own this (matched by title in your library)">owned</span>'
    : "";
}

function dealLowBadgeHtml(d) {
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

function crossStoreOwnPillHtml(g) {
  if (state.activeView !== "library") return "";
  const owned = state.crossStoreOwnedStores.get(gameKey(g));
  if (!owned || owned.length < 2) return "";
  const rest = owned.slice(1).map(s => s.toUpperCase()).join(" · ");
  return `<span class="cross-store-pill" title="Also on: ${escapeAttr(owned.map(s => s.toUpperCase()).join(", "))}">also on ${escapeHtml(rest)}</span>`;
}

function applyItadPriceSnapshot(prevByKey, nextByKey) {
  state.itadPriceDroppedKeys = new Set();
  for (const [key, n] of Object.entries(nextByKey || {})) {
    const p = prevByKey?.[key];
    if (!p || n?.price == null || p.price == null) continue;
    if (n.price < p.price - 0.009) state.itadPriceDroppedKeys.add(key);
  }
}

function slimItadSnapshot(byKey) {
  const slim = {};
  for (const [k, v] of Object.entries(byKey || {})) {
    if (v?.price != null) slim[k] = { price: v.price, cut: v.cut || 0 };
  }
  return slim;
}

function parsePriceLike(v) {
  if (v == null) return null;
  if (typeof v === "number") return v;
  const m = String(v).match(/-?\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

// Returns unified deal info for a game. ITAD is preferred (cross-store best price);
// Steam discount is the fallback. Manual wishlist entries can supply price/discount.
function getDealInfo(g) {
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
  const steamPrice = parsePriceLike(g.price);
  const steamRegular = parsePriceLike(g.price_initial);
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

function dealShopShort(shop) {
  if (!shop) return "";
  const k = String(shop).trim().toLowerCase();
  if (DEAL_SHOP_SHORT[k]) return DEAL_SHOP_SHORT[k];
  return shop.length > 10 ? shop.slice(0, 10) + "…" : shop;
}

function shopSlug(shop) {
  const short = dealShopShort(shop);
  return String(short || shop || "").trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function effectiveDiscountPercent(g) {
  const d = getDealInfo(g);
  if (d) return d.cut || 0;
  return g.discount_percent || 0;
}

function effectiveSortPrice(g) {
  const d = getDealInfo(g);
  if (d && d.price != null) return d.price;
  return parsePriceLike(g.price);
}

function dealScore(g) {
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

// === Filter + sort ===
function hasPersonalEntry(g) {
  const key = gameKey(g);
  return !!(state.personal[key] || (typeof state.personal[gameId(g)] === "object" && state.personal[gameId(g)]));
}

function chipStatusKey(g) {
  if (!hasPersonalEntry(g)) return "backlog";
  return getPersonal(g).status || "backlog";
}

function renderStatusChipsHtml(games, defs = STATUS_CHIP_DEFS) {
  const counts = Object.fromEntries(defs.map(d => [d.key, 0]));
  for (const g of games) {
    const k = chipStatusKey(g);
    if (k in counts) counts[k] = (counts[k] || 0) + 1;
  }
  const active = document.getElementById("statusFilter")?.value || "";
  return defs.map(def => {
    const n = counts[def.key] || 0;
    if (def.key === "__none__" && n === 0) return "";
    if (n === 0) return "";
    const isActive = active === def.key;
    const title = isActive ? `Clear ${def.label} filter` : `Filter: ${def.label}`;
    return `<button type="button" class="status-chip${isActive ? " active" : ""}" data-status-filter="${escapeAttr(def.key)}" title="${escapeAttr(title)}">${escapeHtml(def.label)} <span class="text-slate-100 font-semibold ml-1">${n}</span></button>`;
  }).join("");
}

function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === "game") return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

function alphaBucket(name) {
  const ch = (name || "").trim().charAt(0);
  if (!ch || !/[A-Za-z]/.test(ch)) return "#";
  return ch.toUpperCase();
}

function initAlphaNav() {
  const nav = document.getElementById("alphaNav");
  if (!nav || nav.dataset.built) return;
  const letters = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];
  nav.innerHTML = letters.map(l => {
    const letter = l;
    const title = letter === "#" ? "Jump to non-letter titles" : `Jump to ${letter}`;
    return `<button type="button" class="alpha-nav-btn" data-letter="${letter}" title="${title}">${letter}</button>`;
  }).join("");
  nav.dataset.built = "1";
  nav.addEventListener("click", e => {
    const btn = e.target.closest(".alpha-nav-btn");
    if (!btn || btn.disabled) return;
    jumpToLetter(btn.dataset.letter);
  });
}

function buildAlphaNav(list) {
  const nav = document.getElementById("alphaNav");
  if (!nav) return;
  const letters = new Set(list.map(g => alphaBucket(g.name)));
  nav.querySelectorAll(".alpha-nav-btn").forEach(btn => {
    const enabled = letters.has(btn.dataset.letter);
    btn.classList.toggle("enabled", enabled);
    btn.disabled = !enabled;
  });
}

function tableListDocTop() {
  const shell = document.getElementById("tableShell");
  const tableWrap = document.getElementById("tableWrap");
  const anchor = shell || tableWrap;
  if (!anchor) return 0;
  const thead = tableWrap?.querySelector("thead");
  const headerH = thead?.offsetHeight ?? 0;
  return anchor.getBoundingClientRect().top + window.scrollY + headerH;
}

function rowScrollTop(idx) {
  return tableListDocTop() + idx * TABLE_ROW_HEIGHT;
}

function scrollToRowIndex(idx, { smooth = false } = {}) {
  const list = state._visibleList || sortedGames(filteredGames());
  if (!list.length || idx < 0 || idx >= list.length) return;
  state.focusedRowIndex = idx;
  const key = gameKey(list[idx]);
  state.pickedKey = key;

  if (state._virtualActive) {
    const target = Math.max(0, rowScrollTop(idx) - 100);
    window.scrollTo({ top: target, behavior: smooth ? "smooth" : "auto" });
    paintTableBody(list, { anchorIndex: idx });
    requestAnimationFrame(() => {
      paintTableBody(list, { anchorIndex: idx });
      document.querySelectorAll("tr.row-picked").forEach(r => r.classList.remove("row-picked"));
      const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
      row?.classList.add("row-picked", "row-focused");
    });
    return;
  }

  focusRow(key);
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) scrollRowToCenter(row);
}

function jumpToLetter(letter) {
  const list = state._visibleList || sortedGames(filteredGames());
  const idx = list.findIndex(g => alphaBucket(g.name) === letter);
  if (idx < 0) return;
  scrollToRowIndex(idx);
}

function filteredGames() {
  return state._visibleList || [];
}

function passesDealFilters(g) {
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

function visibleListForKeyboard() {
  return sortedGames(filteredGames());
}

// === Selection & bulk ===
function updateBulkBar() {
  renderBulkStatusButtons();
  const bar = document.getElementById("bulkBar");
  const n = state.selectedKeys.size;
  document.getElementById("bulkCount").textContent = `${n} selected`;
  const show = n > 0 && state.activeView !== "dashboard";
  bar.classList.toggle("hidden", !show);
  document.body.classList.toggle("bulk-bar-open", show);
}

function toggleSelection(key, on) {
  if (on) state.selectedKeys.add(key);
  else state.selectedKeys.delete(key);
  updateBulkBar();
}

function bulkSetStatus(status) {
  for (const key of state.selectedKeys) {
    const g = findGameByKey(key);
    if (g) setPersonal(g, "status", status);
  }
  state.selectedKeys.clear();
  updateBulkBar();
  invalidateTableCache();
  renderTable();
}

function sortedGames(list) {
  return list;
}

function pickCardHtml(g) {
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
      <div class="text-xs text-slate-400 flex justify-between"><span>${rating}</span><span>${h != null ? `${h}h` : ""}</span></div>
    </div>`;
}

function passesTagFilter(g) {
  const tagFilters = state.prefs.tagFilters || [];
  if (!tagFilters.length) return true;
  const gameTags = getPersonal(g).tags || [];
  if (state.prefs.tagFilterMode === "AND") return tagFilters.every(t => gameTags.includes(t));
  return tagFilters.some(t => gameTags.includes(t));
}

function renderPicks() {
  const tab = state.prefs.picksTab;
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
    default: data = backlogRated;
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
  picksGrid.innerHTML = data.length
    ? data.slice(0, limit).map(renderCard).join("")
    : `<div class="col-span-full text-sm text-slate-400 italic">${emptyMsg}</div>`;
  syncCoverFits(picksGrid);
  document.querySelectorAll(".pick-tab").forEach(el => {
    const owner = el.dataset.pickView || "library";
    el.classList.toggle("active", owner === pickView && el.dataset.tab === tab);
  });
  updatePicksChrome();
  renderPicksLimitButtons();
}

function dealCardHtml(g) {
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

function normalizePicksLimit() {
  const validLimits = [16, 24, 48, 96];
  const n = Number(state.prefs.picksLimit);
  if (!validLimits.includes(n)) {
    state.prefs.picksLimit = 16;
    savePrefs();
  }
  return state.prefs.picksLimit;
}

function renderPicksLimitButtons() {
  const limit = normalizePicksLimit();
  document.querySelectorAll(".picks-limit-btn").forEach(btn => {
    btn.classList.toggle("active", +btn.dataset.limit === limit);
  });
}


function renderSummary() {
  const el = document.getElementById("summary");
  if (!el) return;
  if (state.activeView === "dashboard") {
    const games = dashboardLibraryGames();
    el.innerHTML = `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Dashboard overview · <span class="text-slate-100 font-semibold ml-1">${games.length}</span> library games</div>`;
    return;
  }
  if (state.activeView === "wishlist") {
    const wl = state.wishlistGames.filter(g => !state.wishlistCrossStoreHiddenKeys.has(gameKey(g)));
    const hiddenCount = state.wishlistGames.length - wl.length;
    const sourceSet = new Set();
    for (const g of state.wishlistGames) {
      const s = (g.wishlist_store || g.store_target || (g.store === "wishlist" ? "steam" : g.store) || "").toLowerCase();
      if (s) sourceSet.add(s);
    }
    const sourcesList = [...sourceSet].map(s => s.toUpperCase()).sort().join(", ");
    const onSale = wl.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
    const lows = wl.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; });
    const owned = wl.filter(g => isOwnedByTitle(g.name)).length;
    const cuts = onSale.map(g => effectiveDiscountPercent(g)).filter(c => c > 0);
    const avgDisc = cuts.length ? Math.round(cuts.reduce((s, c) => s + c, 0) / cuts.length) : null;
    const prices = wl.map(g => effectiveSortPrice(g)).filter(p => p != null);
    const avgPrice = prices.length ? (prices.reduce((s, p) => s + p, 0) / prices.length).toFixed(2) : null;
    const onSaleActive = !!state.prefs.dealOnSaleOnly;
    const lowOnlyActive = !!state.prefs.dealHistoricalLowOnly;
    const hideOwnedActive = !!state.prefs.dealHideOwned;
    const wishlistFiltersDirty = onSaleActive || lowOnlyActive || hideOwnedActive
      || !!state.prefs.wishlistStoreFilter
      || !!document.getElementById("statusFilter")?.value;
    const resetChip = `<button type="button" class="summary-wishlist-reset px-3 py-2 rounded-full bg-slate-800 hover:bg-slate-700 text-xs cursor-pointer border border-slate-700${wishlistFiltersDirty ? " text-slate-200" : " text-slate-400 cursor-default"}" title="${wishlistFiltersDirty ? "Clear all wishlist filters" : "All wishlist entries"}"><span>Wishlist</span> <span class="text-slate-100 font-semibold ml-1">${wl.length}</span>${hiddenCount ? ` <span class="text-slate-500 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</button>`;
    const onSaleChip = `<button type="button" class="summary-deal-chip${onSaleActive ? " active" : ""}" data-wishlist-deal-filter="onSale" title="${onSaleActive ? "Clear: show only on-sale wishlist items" : "Show only on-sale wishlist items"}">On sale <span class="text-emerald-200 font-semibold ml-1">${onSale.length}</span></button>`;
    const lowChip = lows.length
      ? `<button type="button" class="summary-deal-chip historical${lowOnlyActive ? " active" : ""}" data-wishlist-deal-filter="historicalLow" title="${lowOnlyActive ? "Clear: show only historical lows" : "Show only historical lows"}">Historical low <span class="text-amber-300 font-semibold ml-1">${lows.length}</span></button>`
      : "";
    const ownedChip = owned
      ? `<button type="button" class="summary-deal-chip owned${hideOwnedActive ? " active" : ""}" data-wishlist-deal-filter="hideOwned" title="${hideOwnedActive ? "Currently hiding already-owned wishlist items — click to show" : "Hide wishlist items you already own elsewhere"}">Already owned <span class="text-amber-200 font-semibold ml-1">${owned}</span></button>`
      : "";
    const statusChips = renderStatusChipsHtml(wl, WISHLIST_STATUS_CHIP_DEFS);
    const sourcesChip = sourceSet.size
      ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs" title="Wishlist sources: ${escapeAttr(sourcesList)}">Sources <span class="text-slate-100 font-semibold ml-1">${sourceSet.size}</span></div>`
      : "";
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        ${resetChip}
        ${sourcesChip}
        ${onSaleChip}
        ${lowChip}
        ${avgDisc != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg discount <span class="text-slate-100 font-semibold ml-1">${avgDisc}%</span></div>` : ""}
        ${avgPrice != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg price <span class="text-slate-100 font-semibold ml-1">$${avgPrice}</span></div>` : ""}
        ${ownedChip}
      </div>
      ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
    return;
  }
  if (state.activeView === "itch") {
    const total = state.itchGames.length;
    const gamesOnly = state.itchGames.filter(itchIsGame).length;
    const showingGames = state.prefs.itchHideNonGames ? gamesOnly : total;
    const backlog = state.itchGames.filter(g => getPersonal(g).status === "backlog" && (!state.prefs.itchHideNonGames || itchIsGame(g)));
    const totalHltb = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
    const rated = state.itchGames.filter(g => ratingValue(g) > 0 && (!state.prefs.itchHideNonGames || itchIsGame(g)));
    const avg = rated.length ? (rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length).toFixed(0) : "—";
    const fetched = state.libraryMeta.itch?.fetched_at ? new Date(state.libraryMeta.itch.fetched_at).toLocaleString() : "";
    const countLabel = state.prefs.itchHideNonGames && gamesOnly !== total
      ? `${gamesOnly} of ${total}`
      : String(total);
    const itchScope = state.prefs.itchHideNonGames ? state.itchGames.filter(itchIsGame) : state.itchGames;
    const statusChips = renderStatusChipsHtml(itchScope);
    el.innerHTML = `
      <div class="w-full flex flex-wrap gap-2">
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">itch.io <span class="text-slate-100 font-semibold ml-1">${countLabel}</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Backlog hours <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(totalHltb))}h</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Rated <span class="text-slate-100 font-semibold ml-1">${rated.length}</span></div>
        <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg rating <span class="text-slate-100 font-semibold ml-1">${avg}${avg !== "—" ? "%" : ""}</span></div>
        ${fetched ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs text-slate-400">Fetched ${escapeHtml(fetched)}</div>` : ""}
      </div>
      ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
    return;
  }
  const visible = state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)));
  const backlog = visible.filter(g => getPersonal(g).status === "backlog");
  const totalHltb = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
  const played = visible.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  const storeLabels = {
    steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic",
    amazon: "Amazon", xbox: "Xbox", battlenet: "Battle.net",
    ubisoft: "Ubisoft", nintendo: "Nintendo", itch: "itch.io",
  };
  const storeCounts = Object.keys(storeLabels)
    .map(k => ({
      key: k,
      label: storeLabels[k],
      count: k === "itch" ? state.itchGames.filter(itchIsGame).length : state.allGames.filter(g => normalizeGame(g).store === k).length,
    }))
    .sort((a, b) => b.count - a.count);
  const rated = visible.filter(g => ratingValue(g) > 0);
  const avg = rated.length ? (rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length).toFixed(0) : "—";
  const hiddenCount = state.allGames.length - visible.length;
  const activeStore = state.prefs.storeFilter || "";
  const storeChips = storeCounts
    .map(s => {
      if (s.key === "itch" && s.count > 0) {
        const itchTotal = state.itchGames.length;
        const titleText = itchTotal !== s.count
          ? `Open itch.io library tab (${s.count} games of ${itchTotal} total keys)`
          : "Open itch.io library tab";
        return `<button type="button" class="summary-jump-chip px-3 py-2 rounded-full bg-slate-800 hover:bg-slate-700 text-xs cursor-pointer border border-slate-700" data-jump-view="itch" title="${titleText}">${s.label} <span class="text-slate-100 font-semibold ml-1">${s.count}</span> <span class="text-slate-400 ml-0.5">→</span></button>`;
      }
      if (s.count === 0) return "";
      const isActive = activeStore === s.key;
      const title = isActive ? `Clear ${s.label} filter` : `Filter: ${s.label}`;
      return `<button type="button" class="summary-store-chip${isActive ? " active" : ""}" data-store-filter="${escapeAttr(s.key)}" title="${escapeAttr(title)}">${escapeHtml(s.label)} <span class="text-slate-100 font-semibold ml-1">${s.count}</span></button>`;
    })
    .join("");
  const statusChips = renderStatusChipsHtml(visible);
  el.innerHTML = `
    <div class="w-full flex flex-wrap gap-2">
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Games <span class="text-slate-100 font-semibold ml-1">${visible.length}</span>${hiddenCount ? ` <span class="text-slate-500 ml-1">(${hiddenCount} dupes hidden)</span>` : ""}</div>
      ${storeChips}
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Backlog hours <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(totalHltb))}h</span></div>
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Played <span class="text-slate-100 font-semibold ml-1">${formatNum(Math.round(played))}h</span></div>
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg rating <span class="text-slate-100 font-semibold ml-1">${avg}${avg !== "—" ? "%" : ""}</span></div>
    </div>
    ${statusChips ? `<div class="w-full flex flex-wrap gap-2">${statusChips}</div>` : ""}`;
}

function findGameByKey(key) {
  return state.allGames.find(g => gameKey(g) === key)
    || state.itchGames.find(g => gameKey(g) === key)
    || state.wishlistGames.find(g => gameKey(g) === key);
}

function updateRowInPlace(tr, g) {
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const key = gameKey(g);
  const selected = state.selectedKeys.has(key);
  const focused = tr.classList.contains("row-focused");
  tr.className = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}`;
}

function tagCellHtml(g) {
  const key = gameKey(g);
  const p = getPersonal(g);
  return (p.tags || []).map(t => `<span class="row-tag inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-700/40 border border-amber-500/40 text-[11px] text-amber-100">${escapeHtml(t)}<button type="button" class="row-tag-remove text-amber-200 hover:text-white" style="cursor: pointer" data-game-key="${escapeAttr(key)}" data-tag="${escapeAttr(t)}" title="Remove tag" aria-label="Remove tag">×</button></span>`).join("") + `<button type="button" class="row-tag-add text-[11px] px-1.5 py-0.5 rounded-full border border-dashed border-slate-500 text-slate-400 hover:text-slate-100 hover:border-slate-300" style="cursor: pointer" data-game-key="${escapeAttr(key)}" title="Add a tag">+ tag</button>`;
}

function updateTagCellInPlace(tr, g) {
  if (!tr) return;
  const wrap = tr.querySelector(".tag-chip-wrap");
  if (wrap) wrap.innerHTML = tagCellHtml(g);
}

let _tagChipsRefreshTimer = null;
function scheduleTagChipsRefresh() {
  clearTimeout(_tagChipsRefreshTimer);
  _tagChipsRefreshTimer = setTimeout(renderTagChips, 150);
}

function rowClass(g, lowConf) {
  const status = getPersonal(g).status;
  const stateClass = status === "next" ? "status-next" : status === "playing" ? "status-playing" : status === "unfinished" ? "status-unfinished" : status === "live" ? "status-live" : status === "finished" ? "status-finished" : status === "skip" ? "status-skip" : "";
  const lowClass = lowConf ? " low-confidence" : "";
  const picked = state.pickedKey === gameKey(g) ? " row-picked" : "";
  return `bg-slate-800/50 hover:bg-slate-700/50 ${stateClass}${lowClass}${picked}`;
}

function hltbLabel(g) {
  const p = getPersonal(g);
  if (p.hltb_override != null && p.hltb_override !== "") return `${p.hltb_override}* / - / -`;
  const m = g.hltb_main_hours ?? "-";
  const e = g.hltb_main_extra_hours ?? "-";
  const c = g.hltb_completionist_hours ?? "-";
  return `${m} / ${e} / ${c}`;
}

function formatPrice(g) {
  const itad = getItadForGame(g);
  if (itad?.price_str) {
    const onSale = (itad.cut || 0) > 0;
    const cutTxt = onSale ? ` (-${itad.cut}%)` : "";
    const priceHtml = onSale
      ? `<span class="text-emerald-300 font-semibold">${escapeHtml(itad.price_str)}${escapeHtml(cutTxt)}</span>`
      : escapeHtml(itad.price_str);
    const d = getDealInfo(g);
    const lowBadge = d ? dealLowBadgeHtml(d).replace(/^/, "&nbsp;") : "";
    const dropBadge = dealDroppedBadgeHtml(g).replace(/^/, "&nbsp;");
    const shopHtml = itad.shop ? `@ ${escapeHtml(itad.shop)}` : "";
    return `<div class="flex flex-col items-end leading-tight">
      <span class="whitespace-nowrap">${priceHtml}${dropBadge}${lowBadge}</span>
      ${shopHtml ? `<span class="text-[10px] text-slate-400 truncate w-full text-right" title="${escapeAttr(itad.shop)}">${shopHtml}</span>` : ""}
    </div>`;
  }
  if (!g.price && g.discount_percent == null) return "—";
  const base = g.price || "N/A";
  const cut = g.discount_percent || 0;
  if (cut > 0) {
    return `<span class="text-emerald-300 font-semibold">${escapeHtml(base)} (-${cut}%)</span>`;
  }
  return escapeHtml(base);
}

function focusGame(key) {
  state.pickedKey = key;
  const targetIsWishlist = String(key).startsWith("wishlist:");
  const targetIsItch = String(key).startsWith("itch:");
  const targetView = targetIsWishlist ? "wishlist" : targetIsItch ? "itch" : "library";
  if (state.activeView !== targetView) {
    state._pendingFocusKey = key;
    switchView(targetView);
    return;
  }
  const existing = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (existing) {
    document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
    document.querySelectorAll("tr.row-picked").forEach(r => r.classList.remove("row-picked"));
    existing.classList.add("row-focused", "row-picked");
    scrollRowToCenter(existing);
    const list = visibleListForKeyboard();
    const idx = list.findIndex(g => gameKey(g) === key);
    if (idx >= 0) state.focusedRowIndex = idx;
    return;
  }
  const list = visibleListForKeyboard();
  const idx = list.findIndex(g => gameKey(g) === key);
  if (idx >= 0) scrollToRowIndex(idx);
  else renderTable();
}

function consumePendingFocus(list) {
  const key = state._pendingFocusKey;
  if (!key) return;
  state._pendingFocusKey = null;
  const idx = list.findIndex(g => gameKey(g) === key);
  if (idx < 0) return;
  state.pickedKey = key;
  state.focusedRowIndex = idx;
  requestAnimationFrame(() => {
    const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
    if (row) {
      document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
      document.querySelectorAll("tr.row-picked").forEach(r => r.classList.remove("row-picked"));
      row.classList.add("row-focused", "row-picked");
      scrollRowToCenter(row);
    } else {
      scrollToRowIndex(idx);
    }
  });
}

function scrollRowToCenter(row) {
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
}

function scrollFocusedRow() {
  const list = visibleListForKeyboard();
  const idx = state.focusedRowIndex;
  if (idx < 0 || !list[idx]) return;
  const key = gameKey(list[idx]);
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) {
    scrollRowToCenter(row);
    focusRow(key);
    if (state._virtualActive) paintTableBody(list, { anchorIndex: idx });
    return;
  }
  scrollToRowIndex(idx);
}

function focusRow(key) {
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (!row) return;
  document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
  row.classList.add("row-focused");
}

function openStoreForFocused() {
  const list = visibleListForKeyboard();
  const g = list[state.focusedRowIndex];
  if (!g) return;
  const url = storeUrlForGame(g);
  if (url) window.open(url, "_blank", "noopener");
}

let _tableFingerprint = "";
let _lastRenderedView = null;
function tableFingerprint() {
  return JSON.stringify({
    v: state.activeView,
    sk: state.sortKey, sd: state.sortDir,
    q: (document.getElementById("search")?.value || "").trim().toLowerCase(),
    sf: document.getElementById("statusFilter")?.value || "",
    store: state.prefs.storeFilter || "",
    wstore: state.prefs.wishlistStoreFilter || "",
    gen: state.prefs.genreFilters || [],
    gm: state.prefs.genreFilterMode,
    tags: state.prefs.tagFilters || [],
    tm: state.prefs.tagFilterMode,
    deal: [state.prefs.dealOnSaleOnly, state.prefs.dealHistoricalLowOnly, state.prefs.dealHideOwned, state.prefs.dealMinDiscount, state.prefs.dealMaxPrice],
    unp: !!state.prefs.unplayedOnly,
    ea: !!document.getElementById("earlyAccessOnly")?.checked,
    co: !!document.getElementById("coopOnlineOnly")?.checked,
    cc: !!document.getElementById("coopLocalOnly")?.checked,
    cleanup: !!state.cleanupModeActive,
    score: !!state.prefs.showScoreColumn,
    dedupe: !!state.prefs.crossStoreDedup,
    ihng: !!state.prefs.itchHideNonGames,
    lib: state.allGames.length,
    wl: state.wishlistGames.length,
    itch: state.itchGames.length,
    dv: window._dataVersion || 0,
  });
}

function invalidateTableCache() {
  _tableFingerprint = "";
  state._visibleList = null;
}

let _renderTableGen = 0;
let _virtualScrollRaf = 0;

function tableRowHtml(g, idx, { isWish, showScore }) {
  const p = getPersonal(g);
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const hiddenGem = isHiddenGem(g);
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const ownedWish = state.activeView === "wishlist" && isOwnedByTitle(g.name);
  const selected = state.selectedKeys.has(key);
  const focused = idx === state.focusedRowIndex;
  const cls = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}`;
  return `<tr data-row-key="${escapeAttr(key)}" data-row-index="${idx}" class="${cls}">
      <td class="p-2 text-center"><input type="checkbox" class="row-select rounded" data-game-key="${escapeAttr(key)}" ${selected ? "checked" : ""} /></td>
      <td class="p-2"><span class="cover-wrap${window.coverLandscapeAttr(g.library_image || headerFallback)}"><img class="cover${window.coverLandscapeAttr(g.library_image || headerFallback)}" src="${g.library_image || headerFallback}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />${earlyAccessRibbonHtml(g, { label: "EA" })}</span></td>
      <td class="p-2 game-name-cell">
        <div class="flex items-center gap-1.5 min-w-0">
          ${storeLinkHtml(g, "text-sky-400 hover:underline font-medium game-name truncate flex-1 min-w-0", escapeHtml(g.name))}
          ${earlyAccessPillHtml(g)}
          ${hiddenGem ? '<span class="text-purple-400 shrink-0" style="cursor: default" title="Hidden gem: 90%+ rated and unplayed">✦</span>' : ""}
          ${ownedWish ? '<span class="text-amber-400 text-xs shrink-0" title="You already own this (matched by title)">owned</span>' : ""}
        </div>
        <div class="mt-1 flex items-center gap-1.5 flex-wrap">
          ${state.activeView === "wishlist" ? wishlistBadgeHtml(g) : storeBadgeHtml(g)}
          ${coopPillsHtml(g)}
        </div>
        ${lowConf && g.hltb_name ? `<div class="text-xs text-amber-400">HLTB match: ${escapeHtml(g.hltb_name)}</div>` : ""}
      </td>
      ${isWish ? `<td class="p-2">${wishlistStatusSelectHtml(g, p)}</td>` : `<td class="p-2">${buildStatusSelect(key, p.status)}</td>`}
      <td class="col-score p-2 text-right">${priorityScore(g).toFixed(1)}</td>
      <td class="p-2 text-right text-slate-300">${formatHours(g.playtime_minutes)}</td>
      <td class="p-2 text-right">
        <button data-hltb-edit="${escapeAttr(key)}" class="bg-slate-700 hover:bg-slate-600 px-2 py-1 rounded text-xs" style="cursor: pointer" title="Open HowLongToBeat (Shift+click to override main hours)">${hltbLabel(g)}</button>
      </td>
      <td class="p-2 text-right">${g.steam_review_percent != null ? `${g.steam_review_percent}%` : "—"}</td>
      <td class="p-2 text-right">${formatPrice(g)}</td>
      <td class="p-2 text-slate-300">${formatReleaseDate(g.release_date)}</td>
      <td class="p-2 text-slate-300">${formatDate(g.last_played)}</td>
      <td class="p-2 text-slate-400 text-xs truncate" title="${(g.genres || []).filter(x => !isPlatformToken(x)).join(", ")}">${(g.genres || []).filter(x => !isPlatformToken(x)).slice(0, 2).join(", ") || "—"}</td>
      <td class="p-2 notes-cell">
        <div class="tag-chip-wrap flex flex-wrap gap-1 mb-1">${tagCellHtml(g)}</div>
        <input type="text" data-game-key="${escapeAttr(key)}" data-field="notes" value="${escapeAttr(p.notes)}" placeholder="Notes..." class="notes-input bg-slate-700 border border-slate-600 rounded text-xs w-full px-2 py-1" />
      </td>
    </tr>`;
}

function paintTableBody(list, opts = {}) {
  const tbody = document.getElementById("tbody");
  const scrollEl = document.getElementById("tableWrap");
  const colSpan = tableColSpan();
  const isWish = state.activeView === "wishlist";
  const showScore = !!state.prefs.showScoreColumn;
  let start = 0;
  let end = list.length;
  let topPad = 0;
  let bottomPad = 0;
  state._virtualActive = shouldVirtualize(list.length);
  if (state._virtualActive && scrollEl && !opts.resetScroll) {
    let range;
    if (typeof opts.anchorIndex === "number") {
      range = virtualRangeAroundIndex(opts.anchorIndex, list.length);
    } else {
      const { scrollTop, clientHeight } = tableVirtualMetrics(scrollEl);
      range = virtualRange(scrollTop, clientHeight, list.length);
    }
    if (range.start >= range.end && list.length > 0) {
      range = virtualRangeAroundIndex(0, list.length);
    }
    ({ start, end, topPad, bottomPad } = range);
  } else if (opts.resetScroll) {
    const shell = document.getElementById("tableShell");
    if (shell) window.scrollTo({ top: shell.offsetTop - 8, behavior: "instant" in window ? "instant" : "auto" });
  }
  state._virtualStart = start;
  const parts = [];
  parts.push(`<tr class="virtual-spacer" aria-hidden="true"><td colspan="${colSpan}" style="height:${topPad}px;padding:0;border:0"></td></tr>`);
  for (let i = start; i < end; i++) {
    parts.push(tableRowHtml(list[i], i, { isWish, showScore }));
  }
  parts.push(`<tr class="virtual-spacer" aria-hidden="true"><td colspan="${colSpan}" style="height:${bottomPad}px;padding:0;border:0"></td></tr>`);
  tbody.innerHTML = parts.join("");
  syncCoverFits(tbody);
  // Re-measure on first real render of a view — never on virtual-scroll repaints,
  // and average multiple rows so per-row variation (tag chips, etc.) doesn't oscillate.
  if (state._virtualActive && end > start && opts.measure) {
    requestAnimationFrame(() => {
      const rows = tbody.querySelectorAll("tr[data-row-index]");
      if (!rows.length) return;
      const sampleCount = Math.min(rows.length, 8);
      let total = 0;
      for (let i = 0; i < sampleCount; i++) total += rows[i].offsetHeight;
      const avg = Math.round(total / sampleCount);
      if (avg && Math.abs(avg - measuredRowHeight()) > 4) {
        setMeasuredRowHeight(avg);
        cancelAnimationFrame(_virtualScrollRaf);
        _virtualScrollRaf = requestAnimationFrame(() => renderTable({ virtualOnly: true }));
      }
    });
  }
}

async function renderTable(opts) {
  const force = !!opts?.force;
  const virtualOnly = !!opts?.virtualOnly;
  const fp = tableFingerprint();
  if (!force && !virtualOnly && fp === _tableFingerprint && _lastRenderedView === state.activeView) {
    if (state._pendingFocusKey && state._visibleList) consumePendingFocus(state._visibleList);
    return;
  }
  const gen = ++_renderTableGen;
  let list = state._visibleList;
  if (!virtualOnly) {
    const params = collectTableParams();
    list = await queryGamesAsync(state, params);
    if (gen !== _renderTableGen) return;
    state._visibleList = list;
  } else if (!list) {
    return;
  }
  const showScore = !!state.prefs.showScoreColumn;
  const isWish = state.activeView === "wishlist";
  document.getElementById("tableWrap")?.classList.toggle("table-hide-score", !showScore);
  const statusHdr = document.getElementById("statusHeader");
  if (statusHdr) statusHdr.textContent = isWish ? "Tracking" : "Status";
  const priceHdr = document.getElementById("priceHeader");
  if (priceHdr) {
    priceHdr.title = isWish
      ? "Sort by best discount (ITAD cross-store price, then Steam). Shift+click header to sort by deal price."
      : "";
  }
  document.getElementById("tableWrap").classList.toggle("cleanup-active", state.cleanupModeActive && state.activeView === "library");
  const selectAll = document.getElementById("selectAllVisible");
  if (selectAll) {
    selectAll.disabled = false;
    selectAll.checked = list.length > 0 && list.every(g => state.selectedKeys.has(gameKey(g)));
  }

  if (state.focusedRowIndex >= list.length) state.focusedRowIndex = list.length - 1;
  if (state.focusedRowIndex < 0 && list.length) state.focusedRowIndex = 0;

  paintTableBody(list, {
    resetScroll: force && !virtualOnly,
    anchorIndex: opts?.anchorIndex,
    measure: !virtualOnly,
  });

  let base;
  if (state.activeView === "wishlist") {
    const onSale = list.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
    const lows = list.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; }).length;
    const dealBits = [];
    if (onSale) dealBits.push(`${onSale} on sale`);
    if (lows) dealBits.push(`${lows} at historical low`);
    const tail = dealBits.length ? ` · ${dealBits.join(", ")}` : "";
    base = `Wishlist: ${list.length} of ${state.wishlistGames.length - state.wishlistCrossStoreHiddenKeys.size}${tail}`;
  } else if (state.activeView === "itch") {
    const total = state.itchGames.length;
    const gamesOnly = state.itchGames.filter(itchIsGame).length;
    const suffix = state.prefs.itchHideNonGames && gamesOnly !== total ? ` (${gamesOnly} games of ${total} items)` : "";
    base = `Itch.io: ${list.length} of ${state.itchGames.length}${suffix}`;
  } else {
    base = `Showing ${list.length} of ${state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))).length} games`;
  }
  const extra = state.cleanupModeActive && state.activeView === "library" ? " · cleanup mode" : "";
  document.getElementById("rowCount").textContent = base + extra;
  updateBulkBar();
  buildAlphaNav(list);
  _tableFingerprint = fp;
  _lastRenderedView = state.activeView;
  consumePendingFocus(list);
}

// === Drawer + active pills ===
const NON_GENRE_TOKENS = new Set([
  "ps3", "ps4", "ps5", "psp", "ps vita", "psvita", "vita",
  "xbox", "xbox 360", "xbox one", "xbox series x", "xbox series s", "xbox series x|s", "xbox series x/s", "xbox series",
  "nintendo switch", "switch", "wii", "wii u", "ds", "3ds", "nintendo ds", "nintendo 3ds",
  "pc", "windows", "mac", "macos", "osx", "linux", "steamos",
  "ios", "android", "browser", "stadia", "google stadia",
  "default", "html", "html5", "flash", "java", "unity", "godot",
  "physical_game", "physical game", "assets", "asset_pack", "asset pack",
  "tool", "book", "comic", "soundtrack", "other",
]);
function isPlatformToken(name) {
  return NON_GENRE_TOKENS.has(String(name || "").trim().toLowerCase());
}
function aliasCanonicalGenre(name) {
  return GENRE_ALIASES[name] || name;
}
function gameGenresCanonical(g) {
  return [...new Set((g.genres || []).filter(x => !isPlatformToken(x)).map(aliasCanonicalGenre))];
}
function gameMatchesGenreFilters(g, genres, genreMode) {
  const gameGenres = gameGenresCanonical(g);
  if (!genres.length) return true;
  if (genreMode === "AND") return genres.every(x => gameGenres.includes(x));
  return genres.some(x => gameGenres.includes(x));
}

function collectActiveFilters() {
  const pills = [];
  const q = document.getElementById("search").value.trim();
  if (q) pills.push({ kind: "search", value: q, label: `Search: ${q}` });
  if (state.activeView === "library" || state.activeView === "itch") {
    const status = document.getElementById("statusFilter").value;
    if (status) pills.push({ kind: "status", value: status, label: `Status: ${STATUS_FILTER_LABELS[status] || status}` });
  }
  if (state.prefs.storeFilter) pills.push({ kind: "store", value: state.prefs.storeFilter, label: `Store: ${state.prefs.storeFilter}` });
  if (state.activeView === "wishlist" && state.prefs.wishlistStoreFilter) {
    const labelMap = { steam: "Steam", gog: "GOG", epic: "Epic" };
    const v = state.prefs.wishlistStoreFilter;
    pills.push({ kind: "wishlistStore", value: v, label: `Wishlist source: ${labelMap[v] || v}` });
  }
  for (const g of state.prefs.genreFilters || []) pills.push({ kind: "genre", value: g, label: g });
  for (const t of state.prefs.tagFilters || []) pills.push({ kind: "tag", value: t, label: `#${t}` });
  if (document.getElementById("unplayedOnly").checked) pills.push({ kind: "unplayed", value: "1", label: "Unplayed only" });
  if (document.getElementById("earlyAccessOnly")?.checked) pills.push({ kind: "earlyAccess", value: "1", label: "Early Access only" });
  if (document.getElementById("coopOnlineOnly")?.checked) pills.push({ kind: "coopOnline", value: "1", label: "Online co-op" });
  if (document.getElementById("coopLocalOnly")?.checked) pills.push({ kind: "coopLocal", value: "1", label: "Couch co-op" });
  const minR = +document.getElementById("minRating").value;
  if (minR > 0) pills.push({ kind: "minRating", value: String(minR), label: `Rating ≥ ${minR}%` });
  const maxH = +document.getElementById("maxHours").value;
  if (maxH < 200) pills.push({ kind: "maxHours", value: String(maxH), label: `HLTB ≤ ${maxH}h` });
  if (state.cleanupModeActive && state.activeView === "library") pills.push({ kind: "cleanup", value: "1", label: "Cleanup mode" });
  if (state.activeView === "itch" && state.prefs.itchHideNonGames) pills.push({ kind: "itchHideNonGames", value: "1", label: "Hide tools, soundtracks, etc." });
  if (state.prefs.crossStoreDedup) pills.push({ kind: "dedup", value: "1", label: "Hide duplicates" });
  if ((state.prefs.tagFilters || []).length > 1 && state.prefs.tagFilterMode === "AND") {
    pills.push({ kind: "tagMode", value: "AND", label: "Tags: all" });
  }
  if (state.activeView === "wishlist") {
    if (state.prefs.dealOnSaleOnly) pills.push({ kind: "dealOnSale", value: "1", label: "On sale only" });
    if (state.prefs.dealHistoricalLowOnly) pills.push({ kind: "dealLow", value: "1", label: "Historical low only" });
    if (state.prefs.dealHideOwned) pills.push({ kind: "dealHideOwned", value: "1", label: "Hide owned" });
    if (+state.prefs.dealMinDiscount > 0) pills.push({ kind: "dealMinDiscount", value: String(state.prefs.dealMinDiscount), label: `Discount ≥ ${state.prefs.dealMinDiscount}%` });
    if (+state.prefs.dealMaxPrice < 100) pills.push({ kind: "dealMaxPrice", value: String(state.prefs.dealMaxPrice), label: `Price ≤ $${state.prefs.dealMaxPrice}` });
  }
  return pills;
}

function renderFiltersButtonBadge() {
  const n = collectActiveFilters().length;
  const badge = document.getElementById("filtersBtnBadge");
  if (!badge) return;
  badge.textContent = String(n);
  badge.classList.toggle("hidden", n === 0);
}

function renderActiveFilterPills() {
  const wrap = document.getElementById("activeFilterPills");
  if (!wrap) return;
  const pills = collectActiveFilters();
  if (!pills.length) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = pills.map(p => `
    <span class="active-filter-pill">
      ${escapeHtml(p.label)}
      <button type="button" class="active-filter-remove" data-kind="${escapeAttr(p.kind)}" data-value="${escapeAttr(p.value)}" aria-label="Remove filter">×</button>
    </span>
  `).join("") + `<button type="button" id="clearAllFiltersBtn" class="text-xs text-slate-400 hover:text-slate-200 underline ml-1">Clear all</button>`;
  wrap.querySelector("#clearAllFiltersBtn")?.addEventListener("click", clearAllFilters);
  wrap.querySelectorAll(".active-filter-remove").forEach(btn => {
    btn.addEventListener("click", () => removeActiveFilter(btn.dataset.kind, btn.dataset.value));
  });
}

function removeActiveFilter(kind, value) {
  switch (kind) {
    case "search": document.getElementById("search").value = ""; break;
    case "status": document.getElementById("statusFilter").value = ""; break;
    case "store": state.prefs.storeFilter = ""; savePrefs(); renderStoreChips(); break;
    case "wishlistStore": state.prefs.wishlistStoreFilter = ""; savePrefs(); renderWishlistStoreChips(); break;
    case "genre":
      state.prefs.genreFilters = (state.prefs.genreFilters || []).filter(x => x !== value);
      savePrefs();
      break;
    case "tag":
      state.prefs.tagFilters = (state.prefs.tagFilters || []).filter(x => x !== value);
      savePrefs();
      break;
    case "unplayed": document.getElementById("unplayedOnly").checked = false; break;
    case "earlyAccess": {
      const el = document.getElementById("earlyAccessOnly");
      if (el) el.checked = false;
      break;
    }
    case "coopOnline": {
      const el = document.getElementById("coopOnlineOnly");
      if (el) el.checked = false;
      break;
    }
    case "coopLocal": {
      const el = document.getElementById("coopLocalOnly");
      if (el) el.checked = false;
      break;
    }
    case "minRating": document.getElementById("minRating").value = "0"; document.getElementById("minRatingVal").textContent = "0"; break;
    case "maxHours": document.getElementById("maxHours").value = "200"; document.getElementById("maxHoursVal").textContent = "200+"; break;
    case "cleanup": state.cleanupModeActive = false; updateCleanupBtnState(); break;
    case "dedup":
      state.prefs.crossStoreDedup = false;
      savePrefs();
      document.getElementById("crossStoreDedup").checked = false;
      recomputeCrossStoreHidden();
      renderSummary();
      break;
    case "itchHideNonGames": {
      state.prefs.itchHideNonGames = false;
      savePrefs();
      const itchToggle = document.getElementById("itchShowNonGames");
      if (itchToggle) itchToggle.checked = true;
      break;
    }
    case "tagMode":
      state.prefs.tagFilterMode = "OR";
      savePrefs();
      document.getElementById("tagFilterMode").value = "OR";
      break;
    case "dealOnSale":
      state.prefs.dealOnSaleOnly = false;
      savePrefs();
      document.getElementById("dealOnSaleOnly").checked = false;
      break;
    case "dealLow":
      state.prefs.dealHistoricalLowOnly = false;
      savePrefs();
      document.getElementById("dealHistoricalLowOnly").checked = false;
      break;
    case "dealHideOwned":
      state.prefs.dealHideOwned = false;
      savePrefs();
      document.getElementById("dealHideOwned").checked = false;
      break;
    case "dealMinDiscount":
      state.prefs.dealMinDiscount = 0;
      savePrefs();
      document.getElementById("dealMinDiscount").value = "0";
      document.getElementById("dealMinDiscountVal").textContent = "0";
      break;
    case "dealMaxPrice":
      state.prefs.dealMaxPrice = 100;
      savePrefs();
      document.getElementById("dealMaxPrice").value = "100";
      document.getElementById("dealMaxPriceVal").textContent = "any";
      break;
  }
  refreshFilterUI();
}

function clearAllFilters() {
  document.getElementById("search").value = "";
  document.getElementById("statusFilter").value = "";
  document.getElementById("unplayedOnly").checked = false;
  const eaEl = document.getElementById("earlyAccessOnly");
  if (eaEl) eaEl.checked = false;
  const coEl = document.getElementById("coopOnlineOnly");
  if (coEl) coEl.checked = false;
  const ccEl = document.getElementById("coopLocalOnly");
  if (ccEl) ccEl.checked = false;
  document.getElementById("minRating").value = "0";
  document.getElementById("minRatingVal").textContent = "0";
  document.getElementById("maxHours").value = "200";
  document.getElementById("maxHoursVal").textContent = "200+";
  state.prefs.storeFilter = "";
  state.prefs.wishlistStoreFilter = "";
  state.prefs.genreFilters = [];
  state.prefs.tagFilters = [];
  state.prefs.tagFilterMode = "OR";
  state.cleanupModeActive = false;
  savePrefs();
  document.getElementById("crossStoreDedup").checked = false;
  state.prefs.crossStoreDedup = false;
  document.getElementById("tagFilterMode").value = "OR";
  recomputeCrossStoreHidden();
  renderSummary();
  updateCleanupBtnState();
  refreshFilterUI();
}

function openFiltersDrawer() {
  state.filtersDrawerOpen = true;
  document.getElementById("filterDrawerBackdrop").classList.add("open");
  document.getElementById("filterDrawer").classList.add("open");
  document.getElementById("filterDrawerBackdrop").setAttribute("aria-hidden", "false");
  document.getElementById("filterDrawer").setAttribute("aria-hidden", "false");
}

function closeFiltersDrawer() {
  state.filtersDrawerOpen = false;
  document.getElementById("filterDrawerBackdrop").classList.remove("open");
  document.getElementById("filterDrawer").classList.remove("open");
  document.getElementById("filterDrawerBackdrop").setAttribute("aria-hidden", "true");
  document.getElementById("filterDrawer").setAttribute("aria-hidden", "true");
}

function updateCleanupBtnState() {
  const btn = document.getElementById("cleanupModeBtn");
  if (!btn) return;
  btn.classList.toggle("active", state.cleanupModeActive);
  btn.classList.toggle("ring-2", state.cleanupModeActive);
  btn.classList.toggle("ring-orange-400", state.cleanupModeActive);
}

function updateGenreChipsCollapse() {
  const el = document.getElementById("genreChips");
  const btn = document.getElementById("toggleGenreChipsBtn");
  if (!el || !btn) return;
  const count = el.querySelectorAll(".genre-chip").length;
  if (count <= GENRE_CHIP_COLLAPSE_AT) {
    btn.classList.add("hidden");
    el.classList.remove("collapsed", "expanded");
    return;
  }
  btn.classList.remove("hidden");
  btn.textContent = state.genreChipsExpanded ? "Show fewer genres" : `Show all (${count})`;
  el.classList.toggle("collapsed", !state.genreChipsExpanded);
  el.classList.toggle("expanded", state.genreChipsExpanded);
}

function refreshFilterUI(options) {
  renderFiltersButtonBadge();
  renderActiveFilterPills();
  if (state.activeView === "dashboard") {
    scheduleDashboardRender();
    return;
  }
  renderSummary();
  renderTable();
  if (options?.skipPicks) return;
  renderPicks();
}

function updateWishlistDrawerVisibility() {
  const section = document.getElementById("wishlistDealsSection");
  if (!section) return;
  section.classList.toggle("hidden", state.activeView !== "wishlist");
}

function updatePicksChrome() {
  const hideQuick = state.activeView === "wishlist" || state.activeView === "itch";
  document.getElementById("quickWinMaxWrap")?.classList.toggle("hidden", hideQuick);
}

function updateViewChrome() {
  const isWish = state.activeView === "wishlist";
  const isItch = state.activeView === "itch";
  const isDash = state.activeView === "dashboard";
  const isConn = state.activeView === "connections";
  updateWishlistDrawerVisibility();
  updatePickTabsVisibility();
  updatePicksChrome();
  document.getElementById("picksSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("toolbarSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("tableShell")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("rowCount")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("summary")?.classList.toggle("hidden", isConn);
  document.getElementById("alphaNav")?.classList.toggle("dashboard-hidden", isDash || isConn);
  document.getElementById("dashboardContainer")?.classList.toggle("hidden", !isDash);
  document.getElementById("connectionsContainer")?.classList.toggle("hidden", !isConn);
  document.getElementById("libraryStatusSection")?.classList.add("hidden");
  document.getElementById("itchFilterSection")?.classList.toggle("hidden", !isItch);
  document.getElementById("libraryStoreSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn);
  document.getElementById("wishlistStoreSection")?.classList.toggle("hidden", !isWish);
  document.getElementById("libraryMiscSection")?.classList.toggle("hidden", isWish || isItch || isDash || isConn);
  document.getElementById("earlyAccessSection")?.classList.toggle("hidden", isDash || isConn);
  document.getElementById("coopSection")?.classList.toggle("hidden", isDash || isConn);
  if (isDash) scheduleDashboardRender();
  else destroyDashboardCharts();
  if (isConn) refreshConnections();
  renderBulkStatusButtons();
  renderSummary();
}

function updatePickTabsVisibility() {
  document.querySelectorAll(".pick-tab").forEach(btn => {
    const owner = btn.dataset.pickView || "library";
    btn.classList.toggle("hidden", owner !== state.activeView);
  });
}

function showViewLoading(label) {
  const ov = document.getElementById("viewLoadingOverlay");
  const lbl = document.getElementById("viewLoadingLabel");
  if (lbl && label) lbl.textContent = label;
  if (ov) {
    ov.setAttribute("aria-hidden", "false");
    ov.classList.add("show");
  }
  document.querySelectorAll(".view-tab").forEach(b => { b.disabled = true; });
}

function hideViewLoading() {
  const ov = document.getElementById("viewLoadingOverlay");
  if (ov) {
    ov.classList.remove("show");
    ov.setAttribute("aria-hidden", "true");
  }
  document.querySelectorAll(".view-tab").forEach(b => { b.disabled = false; });
}

function switchView(view) {
  if (view === state.activeView) return;
  const fromView = state.activeView;
  const fpBefore = view !== "dashboard" ? tableFingerprint().replace(/"v":"[^"]+"/, `"v":"${view}"`) : "";
  const willBeCached = view !== "dashboard" && view === _lastRenderedView && fpBefore === _tableFingerprint;
  const useOverlay = !willBeCached;
  const label = view === "dashboard" ? "Loading dashboard…" : view === "wishlist" ? "Loading wishlist…" : view === "itch" ? "Loading itch.io…" : view === "connections" ? "Loading connections…" : "Loading library…";
  if (useOverlay) showViewLoading(label);
  const doSwitch = () => {
    if (fromView === "dashboard") {
      cancelScheduledDashboardRender();
      destroyDashboardCharts();
    }
    invalidateTableCache();
    state.activeView = view;
    state.prefs.activeView = view;
    state.selectedKeys.clear();
    state.focusedRowIndex = 0;
    document.querySelectorAll(".view-tab").forEach(b => b.classList.toggle("active", b.dataset.view === view));
    if (view === "dashboard") {
      state.cleanupModeActive = false;
    } else if (view === "wishlist") {
      state.cleanupModeActive = false;
      document.getElementById("statusFilter").value = "";
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "wishlistDeals") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = "wishlistDeals";
    } else if (view === "itch") {
      state.cleanupModeActive = false;
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "topRated") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = "topRated";
    } else {
      state.prefs.picksTab = state.prefs.libraryPicksTab || "topRated";
    }
    applySavedSortForView(view);
    savePrefs();
    updateCleanupBtnState();
    updateBulkBar();
    updateViewChrome();
    refreshFilterUI();
    if (view === "dashboard") {
      fetcherRunner.probeApi().then(async ok => {
        if (!ok) return;
        await fetcherRunner.syncFromServer();
        fetcherRunner.startDashboardPolling();
        stopConnectionsPolling();
      });
    } else if (view === "connections") {
      fetcherRunner.stopDashboardPolling();
      startConnectionsPolling();
      refreshConnections();
    } else {
      fetcherRunner.stopDashboardPolling();
      stopConnectionsPolling();
    }
    if (useOverlay) hideViewLoading();
  };
  if (useOverlay) {
    requestAnimationFrame(() => requestAnimationFrame(doSwitch));
  } else {
    doSwitch();
  }
}
let _filterDebounceTimer = null;
function refreshFilterUIDebounced(options) {
  clearTimeout(_filterDebounceTimer);
  _filterDebounceTimer = setTimeout(() => refreshFilterUI(options), 120);
}
let _tableRerenderTimer = null;
function scheduleTableRerender() {
  clearTimeout(_tableRerenderTimer);
  _tableRerenderTimer = setTimeout(renderTable, 200);
}

function renderGenreChips() {
  const genreSource = state.activeView === "itch" ? state.itchGames : state.allGames;
  const genres = [...new Set(genreSource.flatMap(g => gameGenresCanonical(g)))].sort();
  const html = genres.map(genre => {
    const active = (state.prefs.genreFilters || []).includes(genre);
    return `<button type="button" class="genre-chip px-2 py-1 rounded border border-slate-600 text-xs ${active ? "active" : "bg-slate-700 text-slate-300"}" data-genre="${escapeAttr(genre)}">${escapeHtml(genre)}</button>`;
  }).join("");
  document.getElementById("genreChips").innerHTML = html || '<span class="text-xs text-slate-400">No genres found.</span>';
  updateGenreChipsCollapse();
}

function renderTagChips() {
  const tags = allPersonalTags();
  const wrap = document.getElementById("tagChips");
  if (!wrap) return;
  if (!tags.length) {
    wrap.innerHTML = '<span class="text-xs text-slate-500 italic">No personal tags yet. Use "+ Tag selected" or the tag input on a row.</span>';
    return;
  }
  wrap.innerHTML = tags.map(([t, n]) => {
    const active = (state.prefs.tagFilters || []).includes(t);
    return `<button class="personal-tag-chip px-2 py-0.5 rounded-full border text-xs ${active ? "bg-amber-600 border-amber-400 text-white" : "bg-slate-700 border-slate-600 text-slate-300 hover:bg-slate-600"}" data-tag="${escapeAttr(t)}">${escapeHtml(t)}<span class="ml-1 text-[10px] text-slate-400">${n}</span></button>`;
  }).join("");
}

function exportTopBacklogMarkdown() {
  const visible = state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)));
  const backlog = visible
    .filter(g => chipStatusKey(g) === "backlog")
    .sort((a, b) => priorityScore(b) - priorityScore(a))
    .slice(0, 20);
  if (!backlog.length) {
    alert("No backlog games to export.");
    return;
  }
  const lines = [
    "# BAKLOG — Top 20 backlog",
    "",
    "| # | Game | Store | Score | HLTB main | Rating |",
    "|---:|---|---|---:|---:|---:|",
  ];
  backlog.forEach((g, i) => {
    const store = normalizeGame(g).store.toUpperCase();
    const h = hltbMain(g);
    const rating = ratingValue(g);
    lines.push(
      `| ${i + 1} | ${g.name.replace(/\|/g, "\\|")} | ${store} | ${priorityScore(g).toFixed(1)} | ${h != null ? `${h}h` : "—"} | ${rating > 0 ? `${rating}%` : "—"} |`,
    );
  });
  const md = lines.join("\n");
  navigator.clipboard.writeText(md).then(
    () => { /* copied */ },
    () => download("baklog-top-20.md", md, "text/markdown"),
  );
}

function exportCsv() {
  const list = sortedGames(filteredGames());
  const isWish = state.activeView === "wishlist";
  const headers = isWish
    ? ["store", "wishlist_store", "id", "name", "tracking_status", "deal_price", "deal_discount_pct", "deal_shop", "historical_low", "steam_review_percent", "hltb_main", "release_date", "genres", "tags", "notes", "store_url"]
    : ["store", "id", "name", "status", "score", "playtime_hours", "hltb_main", "hltb_main_extra", "hltb_completionist", "steam_review_percent", "price", "discount_percent", "release_date", "genres", "tags", "notes"];
  const rows = list.map(g => {
    const p = getPersonal(g);
    const ng = normalizeGame(g);
    const d = getDealInfo(g);
    if (isWish) {
      return [
        ng.store, g.wishlist_store ?? "", ng.id, g.name, p.status,
        d?.price != null ? d.price.toFixed(2) : "", effectiveDiscountPercent(g) || "",
        d?.shop ?? "", d?.isHistoricalLow ? "yes" : "",
        g.steam_review_percent ?? "", hltbMain(g) ?? "",
        g.release_date ?? "", (g.genres || []).join("; "), (p.tags || []).join("; "), p.notes,
        g.store_url ?? d?.url ?? "",
      ];
    }
    return [
      ng.store, ng.id, g.name, p.status, priorityScore(g).toFixed(2), (g.playtime_minutes / 60).toFixed(1),
      hltbMain(g) ?? "", g.hltb_main_extra_hours ?? "", g.hltb_completionist_hours ?? "", g.steam_review_percent ?? "",
      g.price ?? "", effectiveDiscountPercent(g) || (g.discount_percent ?? ""), g.release_date ?? "", (g.genres || []).join("; "), (p.tags || []).join("; "), p.notes
    ];
  }).map(cells => cells.map(x => `"${String(x).replace(/"/g, '""')}"`).join(","));
  const fname = isWish ? "steam-backlog-wishlist.csv" : "steam-backlog-library.csv";
  download(fname, `${headers.join(",")}\n${rows.join("\n")}`, "text/csv");
}

function download(name, content, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([content], { type }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// === Library loading ===
async function loadItadPrices() {
  let prevByKey = {};
  try {
    const raw = localStorage.getItem(ITAD_SNAPSHOT_KEY);
    if (raw) prevByKey = JSON.parse(raw)?.by_key || {};
  } catch (_) {}
  try {
    const data = await fetchLibraryJson("itad_prices.json");
    state.libraryMeta.itad = data || null;
    const nextByKey = data?.by_key || {};
    applyItadPriceSnapshot(prevByKey, nextByKey);
    state.itadByKey = nextByKey;
    try {
      localStorage.setItem(ITAD_SNAPSHOT_KEY, JSON.stringify({
        saved_at: Date.now(),
        by_key: slimItadSnapshot(nextByKey),
      }));
    } catch (_) {}
  } catch {
    state.libraryMeta.itad = null;
    state.itadByKey = {};
    state.itadPriceDroppedKeys = new Set();
  }
}

function showItadAlertBanner({ newSales, newHistoricalLows }) {
  const el = document.getElementById("itadAlertBanner");
  if (!el) return;
  const parts = [];
  if (newSales > 0) parts.push(`${newSales} new sale${newSales === 1 ? "" : "s"}`);
  if (newHistoricalLows > 0) {
    parts.push(`${newHistoricalLows} new historical low${newHistoricalLows === 1 ? "" : "s"}`);
  }
  if (!parts.length) return;
  el.innerHTML = `
    <div class="migration-banner-body">
      <span><strong>Prices refreshed</strong> — ${escapeHtml(parts.join(" · "))}.
        <button type="button" class="text-sky-300 hover:text-sky-200 underline ml-1" data-itad-view-deals>View deals →</button>
      </span>
      <span class="migration-banner-actions">
        <button type="button" class="fh-log-btn" data-itad-dismiss>Dismiss</button>
      </span>
    </div>`;
  el.classList.remove("hidden");
  el.querySelector("[data-itad-dismiss]")?.addEventListener("click", () => {
    state.prefs.itadAlertLastDismissedAt = Date.now();
    savePrefs();
    el.classList.add("hidden");
  }, { once: true });
  el.querySelector("[data-itad-view-deals]")?.addEventListener("click", () => {
    state.prefs.itadAlertLastDismissedAt = Date.now();
    savePrefs();
    el.classList.add("hidden");
    if (state.activeView !== "wishlist") {
      switchView("wishlist");
    } else {
      state.prefs.picksTab = "wishlistDeals";
      savePrefs();
      document.querySelectorAll(".pick-tab").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === "wishlistDeals");
      });
      renderPicks();
    }
  }, { once: true });
}

async function loadCacheMeta(url, metaKey) {
  try {
    const res = await fetch(`${url}?t=${Date.now()}`);
    if (!res.ok) {
      state.libraryMeta[metaKey] = null;
      return;
    }
    const data = await res.json();
    if (data && !data.fetched_at) {
      const lm = res.headers.get("Last-Modified");
      if (lm) {
        const ts = Date.parse(lm);
        if (Number.isFinite(ts)) data.fetched_at = new Date(ts).toISOString();
      }
    }
    state.libraryMeta[metaKey] = data || null;
  } catch {
    state.libraryMeta[metaKey] = null;
  }
}

async function loadHltbCache() {
  await loadCacheMeta("cache/hltb_map.json", "hltb");
}

async function loadSteamReviewCache() {
  await loadCacheMeta("cache/steam_review_map.json", "steamReviews");
}

async function loadSteamCoversMeta() {
  await loadCacheMeta("cache/cross_store_images_meta.json", "steamCovers");
}

function applyMergedLibrary() {
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  buildOwnedNormNames();
  const banner = document.getElementById("bootErrorBanner");
  if (banner) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
  }
  renderStoreChips();
  renderWishlistStoreChips();
  renderGenreChips();
  renderTagChips();
  renderSummary();
  if (state.activeView === "dashboard") scheduleDashboardRender();
  else {
    renderPicks();
    refreshFilterUI();
  }
}

async function fetchLibraryJson(path) {
  const res = await fetch(`${path}?t=${Date.now()}`);
  if (!res.ok) return null;
  return res.json();
}

const LIBRARY_STORE_JSON = {
  steam: "games_steam.json",
  gog: "games_gog.json",
  psn: "games_psn.json",
  epic: "games_epic.json",
  amazon: "games_amazon.json",
  nintendo: "games_nintendo.json",
  itch: "games_itch.json",
  xbox: "games_xbox.json",
  battlenet: "games_battlenet.json",
  ubisoft: "games_ubisoft.json",
};
const WISHLIST_FETCHER_JSON = {
  wishlistSteam: "games_wishlist.json",
  wishlistGog: "games_wishlist_gog.json",
  wishlistEpic: "games_wishlist_epic.json",
};
const WISHLIST_FETCHER_META_KEY = {
  wishlistSteam: "wishlist",
  wishlistGog: "wishlistGog",
  wishlistEpic: "wishlistEpic",
};
const ENRICH_FETCHER_KEYS = new Set(["hltb", "steamReviews", "steamCovers"]);

function rebuildAllGamesFromMetas() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualLibrary = allManual.filter(g => !g.wishlist);
  const { steam: steamData, gog, psn, epic, amazon, nintendo, xbox, battlenet, ubisoft, itch } = state.libraryMeta;
  const sources = [
    (steamData?.games || []).map(g => normalizeGame({ ...g, store: g.store || "steam", id: g.id ?? g.appid })),
    (gog?.games || []).map(g => normalizeGame({ ...g, store: "gog", id: g.id ?? g.gog_id })),
    (psn?.games || []).map(g => normalizeGame({ ...g, store: "psn", id: g.id ?? g.psn_id })),
    (epic?.games || []).map(g => normalizeGame({ ...g, store: "epic", id: g.id })),
    (amazon?.games || []).map(g => normalizeGame({ ...g, store: "amazon", id: g.id ?? g.amazon_id })),
    (nintendo?.games || []).map(g => normalizeGame({ ...g, store: "nintendo", id: g.id ?? g.nintendo_id })),
    (xbox?.games || []).map(g => normalizeGame({ ...g, store: "xbox", id: g.id ?? g.xbox_title_id })),
    (battlenet?.games || []).map(g => normalizeGame({ ...g, store: "battlenet", id: g.id ?? g.battlenet_id })),
    (ubisoft?.games || []).map(g => normalizeGame({ ...g, store: "ubisoft", id: g.id ?? g.ubisoft_id })),
    manualLibrary,
  ];
  state.allGames = sources.flatMap(dedupeWithinStore);
  state.itchGames = dedupeWithinStore(
    (itch?.games || []).map(g => normalizeGame({ ...g, store: "itch", id: g.id ?? g.itch_id })),
  );
}

function rebuildWishlistFromMetas() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const { wishlist, wishlistGog, wishlistEpic } = state.libraryMeta;
  const fetchedWishlist = [
    ...((wishlist?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? g.appid }))),
    ...((wishlistGog?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: `gog-${g.id ?? g.gog_id}`, wishlist_store: "gog" }))),
    ...((wishlistEpic?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `epic-${g.epic_namespace}:${g.epic_offer_id}`, wishlist_store: "epic" }))),
  ];
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
}

async function reloadAllLibraryStoreFiles() {
  const entries = await Promise.all(
    Object.entries(LIBRARY_STORE_JSON).map(async ([metaKey, file]) => {
      try {
        return [metaKey, await fetchLibraryJson(file)];
      } catch {
        return [metaKey, state.libraryMeta[metaKey] ?? null];
      }
    }),
  );
  for (const [metaKey, data] of entries) state.libraryMeta[metaKey] = data;
  rebuildAllGamesFromMetas();
}

async function reloadAfterFetcher(key) {
  if (key === "itad") {
    const prevByKey = { ...state.itadByKey };
    const wasAuto = consumeItadAutoRunFlag();
    await loadItadPrices();
    if (wasAuto) {
      const diff = diffItadDeals(prevByKey, state.itadByKey);
      if (diff.newSales > 0 || diff.newHistoricalLows > 0) {
        showItadAlertBanner(diff);
      }
    }
  } else if (ENRICH_FETCHER_KEYS.has(key)) {
    await reloadAllLibraryStoreFiles();
    if (key === "hltb") await loadHltbCache();
    if (key === "steamReviews") await loadSteamReviewCache();
    if (key === "steamCovers") await loadSteamCoversMeta();
  } else if (WISHLIST_FETCHER_JSON[key]) {
    const metaKey = WISHLIST_FETCHER_META_KEY[key];
    state.libraryMeta[metaKey] = await fetchLibraryJson(WISHLIST_FETCHER_JSON[key]);
    rebuildWishlistFromMetas();
  } else if (LIBRARY_STORE_JSON[key]) {
    state.libraryMeta[key] = await fetchLibraryJson(LIBRARY_STORE_JSON[key]);
    rebuildAllGamesFromMetas();
  } else {
    await reloadGames();
    return;
  }
  applyMergedLibrary();
}

configureFetcherHealth({ reloadGames, reloadAfterFetcher });
async function reloadGames() {
  const steam = await fetchLibraryJson("games_steam.json");
  const gog = await fetchLibraryJson("games_gog.json");
  const psn = await fetchLibraryJson("games_psn.json");
  const epic = await fetchLibraryJson("games_epic.json");
  const amazon = await fetchLibraryJson("games_amazon.json");
  const nintendo = await fetchLibraryJson("games_nintendo.json");
  const itch = await fetchLibraryJson("games_itch.json");
  const xbox = await fetchLibraryJson("games_xbox.json");
  const battlenet = await fetchLibraryJson("games_battlenet.json");
  const ubisoft = await fetchLibraryJson("games_ubisoft.json");
  if (!steam && !gog && !psn && !epic && !amazon && !nintendo && !itch && !xbox && !battlenet && !ubisoft) throw new Error("No library files found");
  state.libraryMeta.steam = steam;
  state.libraryMeta.gog = gog;
  state.libraryMeta.psn = psn;
  state.libraryMeta.epic = epic;
  state.libraryMeta.amazon = amazon;
  state.libraryMeta.nintendo = nintendo;
  state.libraryMeta.itch = itch;
  state.libraryMeta.xbox = xbox;
  state.libraryMeta.battlenet = battlenet;
  state.libraryMeta.ubisoft = ubisoft;
  rebuildAllGamesFromMetas();
  const wishlist = await fetchLibraryJson("games_wishlist.json");
  const wishlistGog = await fetchLibraryJson("games_wishlist_gog.json");
  const wishlistEpic = await fetchLibraryJson("games_wishlist_epic.json");
  state.libraryMeta.wishlist = wishlist;
  state.libraryMeta.wishlistGog = wishlistGog;
  state.libraryMeta.wishlistEpic = wishlistEpic;
  rebuildWishlistFromMetas();
  await loadItadPrices();
  await loadHltbCache();
  await loadSteamReviewCache();
  await loadSteamCoversMeta();
  applyMergedLibrary();
}

function refreshAfterManualChange() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualLibrary = allManual.filter(g => !g.wishlist);
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const nonManualLibrary = state.allGames.filter(g => !g.manual);
  state.allGames = [...nonManualLibrary, ...dedupeWithinStore(manualLibrary)];
  const fetchedWishlist = state.wishlistGames.filter(g => !g.manual);
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
  applyMergedLibrary();
}

function renderStoreChips() {
  // Drawer chips were retired in the filter consolidation; the top-bar summary
  // chips are the source of truth. Kept for backward compat with callers that
  // touch this after a state-only filter change (e.g. removeActiveFilter).
  document.querySelectorAll(".store-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.store === (state.prefs.storeFilter || ""));
  });
  if (state.activeView !== "dashboard") renderSummary();
}

function renderWishlistStoreChips() {
  document.querySelectorAll(".wishlist-store-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.wishlistStore === (state.prefs.wishlistStoreFilter || ""));
  });
}

// === Modals ===
let addGameTarget = "library";
function setAddGameTarget(target) {
  addGameTarget = target === "wishlist" ? "wishlist" : "library";
  document.querySelectorAll(".add-target-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.target === addGameTarget);
  });
  document.getElementById("addGameWishlistFields").classList.toggle("hidden", addGameTarget !== "wishlist");
  const titleEl = document.getElementById("addGameModalTitle");
  const hint = document.getElementById("addGameHint");
  if (addGameTarget === "wishlist") {
    titleEl.textContent = "Add to wishlist";
    hint.textContent = "Tracking a deal? Add an optional price and/or discount % and store URL. Discount-only entries still match On sale / Min discount filters even without a price.";
  } else {
    titleEl.textContent = "Add a game";
    hint.textContent = "Type a title and click Search Steam. Pick the closest match to import its cover, Steam rating, and store link. The game will be saved under your chosen platform.";
  }
}
function openAddGameModal() {
  const m = document.getElementById("addGameModal");
  m.classList.remove("hidden");
  m.classList.add("flex");
  setAddGameTarget(state.activeView === "wishlist" ? "wishlist" : "library");
  document.getElementById("addGameTitle").focus();
}
function closeAddGameModal() {
  const m = document.getElementById("addGameModal");
  m.classList.add("hidden");
  m.classList.remove("flex");
  document.getElementById("addGameTitle").value = "";
  document.getElementById("addGameResults").innerHTML = "";
  document.getElementById("addGameStatus").textContent = "";
  document.getElementById("addGameWishPrice").value = "";
  document.getElementById("addGameWishDiscount").value = "";
  document.getElementById("addGameWishUrl").value = "";
}
async function steamSearch(term) {
  const url = `https://store.steampowered.com/api/storesearch/?term=${encodeURIComponent(term)}&l=english&cc=US`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Steam search HTTP ${res.status}`);
  const data = await res.json();
  return (data.items || []).slice(0, 6);
}
async function steamAppReviews(appid) {
  const url = `https://store.steampowered.com/appreviews/${appid}?json=1&language=all&purchase_type=all&num_per_page=0`;
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.success || !data.query_summary) return null;
    const q = data.query_summary;
    return {
      steam_review_percent: q.total_reviews > 0 ? Math.round((q.total_positive / q.total_reviews) * 100) : null,
      steam_review_count: q.total_reviews || 0,
      steam_review_desc: q.review_score_desc || null,
    };
  } catch { return null; }
}
function manualSlug(title) {
  return "manual-" + String(title).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 60);
}
function readWishlistFields() {
  const priceRaw = document.getElementById("addGameWishPrice").value.trim();
  const discountRaw = document.getElementById("addGameWishDiscount").value.trim();
  const url = document.getElementById("addGameWishUrl").value.trim();
  const priceNum = priceRaw ? parseFloat(priceRaw.replace(/[^0-9.]/g, "")) : null;
  const discount = discountRaw ? Math.max(0, Math.min(100, parseInt(discountRaw, 10) || 0)) : null;
  return {
    price: priceNum != null && !isNaN(priceNum) ? `$${priceNum.toFixed(2)}` : null,
    priceNumeric: priceNum != null && !isNaN(priceNum) ? priceNum : null,
    discount_percent: discount,
    store_url: url || null,
  };
}
function applyWishlistMeta(game) {
  const w = readWishlistFields();
  game.wishlist = true;
  game.wishlist_added = new Date().toISOString();
  if (w.price) game.price = w.price;
  if (w.discount_percent != null) game.discount_percent = w.discount_percent;
  if (w.store_url) game.store_url = w.store_url;
}
async function importSteamMatch(title, platform, match) {
  const status = document.getElementById("addGameStatus");
  status.textContent = "Pulling details from Steam...";
  const reviews = await steamAppReviews(match.id) || {};
  const isWishlist = addGameTarget === "wishlist";
  const game = {
    store: isWishlist ? "wishlist" : platform,
    wishlist_store: isWishlist ? platform : undefined,
    id: (isWishlist ? "wish-" : "") + (platform === "steam" ? match.id : manualSlug(title || match.name)),
    name: title || match.name,
    header_image: match.tiny_image || `https://cdn.akamai.steamstatic.com/steam/apps/${match.id}/header.jpg`,
    library_image: `https://cdn.akamai.steamstatic.com/steam/apps/${match.id}/library_600x900_2x.jpg`,
    playtime_minutes: 0,
    last_played: null,
    release_date: null,
    genres: [],
    tags: [],
    steam_review_percent: reviews.steam_review_percent ?? null,
    steam_review_count: reviews.steam_review_count ?? null,
    steam_review_desc: reviews.steam_review_desc ?? null,
    hltb_main_hours: null,
    hltb_main_extra_hours: null,
    hltb_completionist_hours: null,
    hltb_match_confidence: null,
    hltb_name: null,
    store_url: `https://store.steampowered.com/app/${match.id}/`,
    steam_appid: match.id,
    steam_match_name: match.name,
    manual: true,
    added_at: new Date().toISOString(),
  };
  if (isWishlist) applyWishlistMeta(game);
  addManualGame(game);
  const where = isWishlist ? `wishlist (${platform})` : platform;
  status.textContent = `Saved "${game.name}" under ${where}.`;
  refreshAfterManualChange();
  setTimeout(closeAddGameModal, 700);
}
function importTitleOnly() {
  const title = document.getElementById("addGameTitle").value.trim();
  const platform = document.getElementById("addGamePlatform").value;
  if (!title) { document.getElementById("addGameStatus").textContent = "Enter a title first."; return; }
  const isWishlist = addGameTarget === "wishlist";
  const game = {
    store: isWishlist ? "wishlist" : platform,
    wishlist_store: isWishlist ? platform : undefined,
    id: (isWishlist ? "wish-" : "") + manualSlug(title),
    name: title,
    header_image: null,
    library_image: null,
    playtime_minutes: 0,
    last_played: null,
    release_date: null,
    genres: [],
    tags: [],
    steam_review_percent: null,
    steam_review_count: null,
    steam_review_desc: null,
    hltb_main_hours: null,
    hltb_main_extra_hours: null,
    hltb_completionist_hours: null,
    hltb_match_confidence: null,
    hltb_name: null,
    store_url: null,
    manual: true,
    added_at: new Date().toISOString(),
  };
  if (isWishlist) applyWishlistMeta(game);
  addManualGame(game);
  const where = isWishlist ? `wishlist (${platform})` : platform;
  document.getElementById("addGameStatus").textContent = `Saved "${title}" under ${where} (no Steam data).`;
  refreshAfterManualChange();
  setTimeout(closeAddGameModal, 700);
}
function bindAddGameModal() {
  const titleEl = document.getElementById("addGameTitle");
  const platformEl = document.getElementById("addGamePlatform");
  const searchBtn = document.getElementById("addGameSearch");
  const resultsEl = document.getElementById("addGameResults");
  const statusEl = document.getElementById("addGameStatus");

  document.getElementById("addGameBtn").addEventListener("click", openAddGameModal);
  document.getElementById("addGameClose").addEventListener("click", closeAddGameModal);
  document.querySelectorAll(".add-target-btn").forEach(btn => {
    btn.addEventListener("click", () => setAddGameTarget(btn.dataset.target));
  });
  document.getElementById("addGameModal").addEventListener("click", e => {
    if (e.target.id === "addGameModal") closeAddGameModal();
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !document.getElementById("addGameModal").classList.contains("hidden")) closeAddGameModal();
  });

  async function runSearch() {
    const term = titleEl.value.trim();
    if (!term) { statusEl.textContent = "Enter a title first."; return; }
    statusEl.textContent = "Searching Steam...";
    resultsEl.innerHTML = "";
    try {
      const matches = await steamSearch(term);
      if (!matches.length) {
        statusEl.textContent = "No Steam matches. Save without a match to add the title only.";
        return;
      }
      statusEl.textContent = `Pick a match to import:`;
      resultsEl.innerHTML = matches.map(m => `
        <button class="add-game-match w-full text-left flex gap-3 items-center bg-slate-700 hover:bg-slate-600 rounded p-2" data-appid="${m.id}">
          <img src="${m.tiny_image || ''}" alt="" class="w-20 h-10 object-cover rounded bg-slate-800" onerror="this.style.visibility='hidden'" />
          <div class="flex-1 min-w-0">
            <div class="text-sm text-slate-100 truncate">${escapeHtml(m.name)}</div>
            <div class="text-xs text-slate-400">App ${m.id}${m.price ? ` · ${escapeHtml(m.price.final_formatted || '')}` : ""}</div>
          </div>
          <span class="text-xs text-emerald-400">Import &rarr;</span>
        </button>
      `).join("");
    } catch (err) {
      statusEl.textContent = `Steam search failed: ${err.message}. (Steam may rate-limit; try again.)`;
    }
  }

  searchBtn.addEventListener("click", runSearch);
  titleEl.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); runSearch(); } });
  resultsEl.addEventListener("click", async e => {
    const btn = e.target.closest(".add-game-match");
    if (!btn) return;
    const appid = +btn.dataset.appid;
    const match = (await steamSearch(titleEl.value.trim())).find(m => m.id === appid);
    if (!match) { statusEl.textContent = "Couldn't refetch match details."; return; }
    await importSteamMatch(titleEl.value.trim(), platformEl.value, match);
  });
  document.getElementById("addGameSkipSteam").addEventListener("click", importTitleOnly);

  document.getElementById("addGameExport").addEventListener("click", () => {
    download("steam-backlog-manual-games.json", JSON.stringify(loadManualGames(), null, 2), "application/json");
  });
  document.getElementById("addGameImport").addEventListener("change", async e => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const incoming = JSON.parse(await file.text());
      if (!Array.isArray(incoming)) throw new Error("File must be an array of manual games.");
      const merged = [...loadManualGames()];
      for (const g of incoming) {
        const idx = merged.findIndex(m => m.store === g.store && m.id === g.id);
        if (idx >= 0) merged[idx] = g; else merged.push(g);
      }
      saveManualGames(merged);
      refreshAfterManualChange();
      statusEl.textContent = `Imported ${incoming.length} manual games.`;
    } catch (err) {
      statusEl.textContent = `Import failed: ${err.message}`;
    }
    e.target.value = "";
  });
}

// === Keyboard shortcuts ===
function handleGlobalKeydown(e) {
  if (e.key === "Escape") {
    if (state.filtersDrawerOpen) { closeFiltersDrawer(); return; }
    if (!document.getElementById("addGameModal").classList.contains("hidden")) return;
    state.selectedKeys.clear();
    updateBulkBar();
    renderTable();
    return;
  }
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable) {
    if (e.key === "/" && tag !== "input" && tag !== "textarea") { /* allow below */ }
    else return;
  }
  if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
    e.preventDefault();
    document.getElementById("search").focus();
    return;
  }
  const list = visibleListForKeyboard();
  if (!list.length) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    const next = Math.min((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex + 1), list.length - 1);
    scrollToRowIndex(next);
    return;
  }
  if (e.key === "ArrowUp") {
    e.preventDefault();
    const next = Math.max((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex - 1), 0);
    scrollToRowIndex(next);
    return;
  }
  if (e.key === "Enter") {
    e.preventDefault();
    openStoreForFocused();
    return;
  }
  if (state.activeView !== "library") return;
  const statusKeys = { b: "backlog", n: "next", p: "playing", u: "unfinished", l: "live", f: "finished", s: "skip" };
  if (statusKeys[e.key.toLowerCase()]) {
    e.preventDefault();
    const g = list[state.focusedRowIndex] || list[0];
    if (g) { setPersonal(g, "status", statusKeys[e.key.toLowerCase()]); renderTable(); }
    return;
  }
  if (e.key === " ") {
    e.preventDefault();
    const g = list[state.focusedRowIndex];
    if (!g) return;
    const key = gameKey(g);
    toggleSelection(key, !state.selectedKeys.has(key));
    renderTable();
  }
}

// === Event wiring ===
function bindEvents() {
  const onTableVirtualScroll = () => {
    if (!state._virtualActive) return;
    cancelAnimationFrame(_virtualScrollRaf);
    _virtualScrollRaf = requestAnimationFrame(() => renderTable({ virtualOnly: true }));
  };
  window.addEventListener("scroll", onTableVirtualScroll, { passive: true });
  window.addEventListener("resize", onTableVirtualScroll, { passive: true });

  document.getElementById("dashboardFetcherHealth")?.addEventListener("change", e => {
    if (e.target.id === "fetcherHealthStaleOnly") {
      state.prefs.fetcherHealthStaleOnly = e.target.checked;
      savePrefs();
      renderDashboardFetcherHealth();
    }
  });

  document.getElementById("dashboardFetcherHealth")?.addEventListener("click", e => {
    const staleBtn = e.target.closest(".fh-run-stale");
    if (staleBtn && !staleBtn.disabled) {
      e.preventDefault();
      fetcherRunner.runAllStale();
      return;
    }
    const chip = e.target.closest(".fh-chip[data-fetcher-key]");
    if (!chip || chip.disabled) return;
    e.preventDefault();
    fetcherRunner.run(chip.dataset.fetcherKey, { refresh: e.shiftKey });
  });

  document.getElementById("dashboardWishlistStats")?.addEventListener("click", e => {
    const card = e.target.closest("[data-action]");
    if (!card) return;
    const action = card.dataset.action;
    if ((action === "deal-hero" || action === "deal-steal-jump") && card.dataset.key) {
      focusGame(card.dataset.key);
      return;
    }
    if (action === "deal-on-sale") {
      drillWishlistDealFilter({ onSaleOnly: true });
      return;
    }
    if (action === "deal-steals") {
      drillWishlistDealFilter({ minDiscount: 50 });
    }
  });

  const onDashListClick = e => {
    const row = e.target.closest('[data-action="dash-list-jump"]');
    if (!row || !row.dataset.key) return;
    focusGame(row.dataset.key);
  };
  document.getElementById("dashPicksVersusCard")?.addEventListener("click", onDashListClick);
  document.getElementById("dashItchRecap")?.addEventListener("click", onDashListClick);
  document.getElementById("dashboardMega")?.addEventListener("click", onDashListClick);

  const handleCoopActivate = (e) => {
    const target = e.target.closest("[data-action]");
    if (!target) return;
    const action = target.dataset.action;
    if (action === "coop-pick-jump" && target.dataset.key) {
      e.stopPropagation();
      focusGame(target.dataset.key);
      return;
    }
    if (action === "coop-drill") {
      try {
        const args = JSON.parse(target.dataset.drill || "{}");
        dashDrillCoop(args);
      } catch (err) { console.error("co-op drill payload error", err); }
    }
  };
  const coopSpotlightEl = document.getElementById("dashboardCoopSpotlight");
  if (coopSpotlightEl) {
    coopSpotlightEl.addEventListener("click", handleCoopActivate);
    coopSpotlightEl.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const target = e.target.closest('[role="button"][data-action]');
      if (!target) return;
      e.preventDefault();
      handleCoopActivate(e);
    });
  }

  document.querySelectorAll("th[data-sort]").forEach(th => {
    th.addEventListener("click", e => {
      let key = th.dataset.sort;
      if (key === "discount_percent" && e.shiftKey && state.activeView === "wishlist") {
        key = "deal_price";
      }
      if (state.sortKey === key) state.sortDir *= -1;
      else {
        state.sortKey = key;
        state.sortDir = (key === "discount_percent" || key === "deal_price") ? -1 : 1;
      }
      persistCurrentSort();
      renderTable();
    });
  });
  document.getElementById("openFiltersBtn").addEventListener("click", openFiltersDrawer);
  document.getElementById("closeFiltersBtn").addEventListener("click", closeFiltersDrawer);
  document.getElementById("filterDrawerBackdrop").addEventListener("click", closeFiltersDrawer);
  document.getElementById("toggleGenreChipsBtn").addEventListener("click", () => {
    state.genreChipsExpanded = !state.genreChipsExpanded;
    updateGenreChipsCollapse();
  });
  const kebabBtn = document.getElementById("kebabBtn");
  const kebabMenu = document.getElementById("kebabMenu");
  kebabBtn.addEventListener("click", e => {
    e.stopPropagation();
    kebabMenu.classList.toggle("open");
  });
  document.addEventListener("click", () => kebabMenu.classList.remove("open"));
  const itadAutoRefreshToggle = document.getElementById("itadAutoRefreshToggle");
  if (itadAutoRefreshToggle) {
    itadAutoRefreshToggle.checked = !state.prefs.itadAutoRefreshDisabled;
    itadAutoRefreshToggle.addEventListener("change", () => {
      state.prefs.itadAutoRefreshDisabled = !itadAutoRefreshToggle.checked;
      savePrefs();
    });
  }
  ["search", "statusFilter", "unplayedOnly", "earlyAccessOnly", "coopOnlineOnly", "coopLocalOnly", "minRating", "maxHours"].forEach(id => {
    document.getElementById(id).addEventListener("input", () => {
      document.getElementById("minRatingVal").textContent = document.getElementById("minRating").value;
      const h = +document.getElementById("maxHours").value;
      document.getElementById("maxHoursVal").textContent = h >= 200 ? "200+" : h;
      refreshFilterUIDebounced({ skipPicks: id === "search" });
    });
  });
  const itchShowNonGamesEl = document.getElementById("itchShowNonGames");
  if (itchShowNonGamesEl) {
    itchShowNonGamesEl.addEventListener("change", () => {
      state.prefs.itchHideNonGames = !itchShowNonGamesEl.checked;
      savePrefs();
      refreshFilterUI();
    });
  }
  initAlphaNav();
  const bindDealCheckbox = (id, key) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = !!state.prefs[key];
    el.addEventListener("change", () => {
      state.prefs[key] = el.checked;
      savePrefs();
      refreshFilterUI();
    });
  };
  bindDealCheckbox("dealOnSaleOnly", "dealOnSaleOnly");
  bindDealCheckbox("dealHistoricalLowOnly", "dealHistoricalLowOnly");
  bindDealCheckbox("dealHideOwned", "dealHideOwned");
  const dealMinDiscountEl = document.getElementById("dealMinDiscount");
  const dealMinDiscountVal = document.getElementById("dealMinDiscountVal");
  if (dealMinDiscountEl) {
    dealMinDiscountEl.value = String(state.prefs.dealMinDiscount || 0);
    dealMinDiscountVal.textContent = String(state.prefs.dealMinDiscount || 0);
    dealMinDiscountEl.addEventListener("input", () => {
      state.prefs.dealMinDiscount = +dealMinDiscountEl.value;
      dealMinDiscountVal.textContent = String(state.prefs.dealMinDiscount);
      savePrefs();
      refreshFilterUIDebounced();
    });
  }
  const dealMaxPriceEl = document.getElementById("dealMaxPrice");
  const dealMaxPriceVal = document.getElementById("dealMaxPriceVal");
  if (dealMaxPriceEl) {
    const initMax = state.prefs.dealMaxPrice ?? 100;
    dealMaxPriceEl.value = String(initMax);
    dealMaxPriceVal.textContent = initMax >= 100 ? "any" : `$${initMax}`;
    dealMaxPriceEl.addEventListener("input", () => {
      state.prefs.dealMaxPrice = +dealMaxPriceEl.value;
      dealMaxPriceVal.textContent = state.prefs.dealMaxPrice >= 100 ? "any" : `$${state.prefs.dealMaxPrice}`;
      savePrefs();
      refreshFilterUIDebounced();
    });
  }
  const resetDealFiltersBtn = document.getElementById("resetDealFiltersBtn");
  if (resetDealFiltersBtn) {
    resetDealFiltersBtn.addEventListener("click", () => {
      state.prefs.dealOnSaleOnly = false;
      state.prefs.dealHistoricalLowOnly = false;
      state.prefs.dealHideOwned = false;
      state.prefs.dealMinDiscount = 0;
      state.prefs.dealMaxPrice = 100;
      savePrefs();
      if (dealMinDiscountEl) { dealMinDiscountEl.value = "0"; dealMinDiscountVal.textContent = "0"; }
      if (dealMaxPriceEl) { dealMaxPriceEl.value = "100"; dealMaxPriceVal.textContent = "any"; }
      ["dealOnSaleOnly", "dealHistoricalLowOnly", "dealHideOwned"].forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; });
      refreshFilterUI();
    });
  }
  document.getElementById("genreMode").addEventListener("change", e => {
    state.prefs.genreFilterMode = e.target.value;
    savePrefs();
    refreshFilterUI();
  });
  document.getElementById("showScoreColumn").addEventListener("change", e => {
    state.prefs.showScoreColumn = e.target.checked;
    savePrefs();
    document.getElementById("tableWrap")?.classList.toggle("table-hide-score", !e.target.checked);
  });
  document.getElementById("quickWinMax").addEventListener("input", e => {
    state.prefs.quickWinMaxHours = +e.target.value;
    document.getElementById("quickWinMaxVal").textContent = state.prefs.quickWinMaxHours;
    savePrefs();
    renderPicks();
  });
  normalizePicksLimit();
  renderPicksLimitButtons();
  document.getElementById("picksLimitGroup").addEventListener("click", e => {
    const btn = e.target.closest(".picks-limit-btn");
    if (!btn) return;
    state.prefs.picksLimit = +btn.dataset.limit || 16;
    savePrefs();
    renderPicksLimitButtons();
    renderPicks();
  });
  document.getElementById("togglePicks").addEventListener("click", () => {
    state.prefs.picksCollapsed = !state.prefs.picksCollapsed;
    savePrefs();
    document.getElementById("picksContainer").classList.toggle("hidden", state.prefs.picksCollapsed);
    document.getElementById("togglePicks").textContent = state.prefs.picksCollapsed ? "Show" : "Hide";
  });
  document.querySelectorAll(".pick-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      state.prefs.picksTab = tab;
      const pv = btn.dataset.pickView || "library";
      if (pv === "library") state.prefs.libraryPicksTab = tab;
      if (pv === "itch") state.prefs.itchPicksTab = tab;
      savePrefs();
      renderPicks();
    });
  });
  // The drawer's store-chip row was removed in the filter consolidation;
  // the top-bar summary chips are the only store-filter UI now. Click handling
  // for those lives in the #summary listener below.
  document.getElementById("wishlistStoreChips")?.addEventListener("click", e => {
    const chip = e.target.closest(".wishlist-store-chip");
    if (!chip) return;
    state.prefs.wishlistStoreFilter = chip.dataset.wishlistStore || "";
    savePrefs();
    renderWishlistStoreChips();
    refreshFilterUI();
  });
  document.getElementById("summary").addEventListener("click", e => {
    const statusChip = e.target.closest(".status-chip");
    if (statusChip) {
      const sf = document.getElementById("statusFilter");
      const val = statusChip.dataset.statusFilter;
      sf.value = sf.value === val ? "" : val;
      refreshFilterUI();
      return;
    }
    const storeChip = e.target.closest(".summary-store-chip");
    if (storeChip) {
      const val = storeChip.dataset.storeFilter || "";
      state.prefs.storeFilter = state.prefs.storeFilter === val ? "" : val;
      savePrefs();
      refreshFilterUI();
      return;
    }
    const dealChip = e.target.closest(".summary-deal-chip[data-wishlist-deal-filter]");
    if (dealChip) {
      const kind = dealChip.dataset.wishlistDealFilter;
      if (kind === "onSale") state.prefs.dealOnSaleOnly = !state.prefs.dealOnSaleOnly;
      else if (kind === "historicalLow") state.prefs.dealHistoricalLowOnly = !state.prefs.dealHistoricalLowOnly;
      else if (kind === "hideOwned") state.prefs.dealHideOwned = !state.prefs.dealHideOwned;
      savePrefs();
      syncDealFilterControls();
      refreshFilterUI();
      return;
    }
    if (e.target.closest(".summary-wishlist-reset")) {
      state.prefs.dealOnSaleOnly = false;
      state.prefs.dealHistoricalLowOnly = false;
      state.prefs.dealHideOwned = false;
      state.prefs.wishlistStoreFilter = "";
      const sf = document.getElementById("statusFilter");
      if (sf) sf.value = "";
      savePrefs();
      syncDealFilterControls();
      renderWishlistStoreChips();
      refreshFilterUI();
      return;
    }
    const chip = e.target.closest(".summary-jump-chip");
    if (!chip) return;
    const view = chip.dataset.jumpView;
    if (view) switchView(view);
  });
  document.getElementById("dashboardContent")?.addEventListener("click", e => {
    const chip = e.target.closest("[data-jump-view]");
    if (chip?.dataset.jumpView) switchView(chip.dataset.jumpView);
  });
  const dedupEl = document.getElementById("crossStoreDedup");
  if (dedupEl) {
    if (typeof state.prefs.crossStoreDedup !== "boolean") state.prefs.crossStoreDedup = true;
    dedupEl.checked = !!state.prefs.crossStoreDedup;
    dedupEl.addEventListener("change", () => {
      state.prefs.crossStoreDedup = dedupEl.checked;
      savePrefs();
      recomputeCrossStoreHidden();
      renderSummary();
      refreshFilterUI();
    });
  }
  document.getElementById("genreChips").addEventListener("click", e => {
    const chip = e.target.closest(".genre-chip");
    if (!chip) return;
    const genre = chip.dataset.genre;
    if (state.prefs.genreFilters.includes(genre)) state.prefs.genreFilters = state.prefs.genreFilters.filter(x => x !== genre);
    else state.prefs.genreFilters.push(genre);
    savePrefs();
    renderGenreChips();
    refreshFilterUI();
  });
  document.getElementById("tagChips").addEventListener("click", e => {
    const chip = e.target.closest(".personal-tag-chip");
    if (!chip) return;
    const tag = chip.dataset.tag;
    const cur = state.prefs.tagFilters || [];
    state.prefs.tagFilters = cur.includes(tag) ? cur.filter(x => x !== tag) : [...cur, tag];
    savePrefs();
    renderTagChips();
    refreshFilterUI();
  });
  const tagModeEl = document.getElementById("tagFilterMode");
  tagModeEl.value = state.prefs.tagFilterMode || "OR";
  tagModeEl.addEventListener("change", () => {
    state.prefs.tagFilterMode = tagModeEl.value;
    savePrefs();
    refreshFilterUI();
  });
  document.getElementById("addTagBtn").addEventListener("click", () => {
    const list = sortedGames(filteredGames());
    const targets = [];
    if (state.selectedKeys.size) {
      for (const k of state.selectedKeys) {
        const g = findGameByKey(k);
        if (g) targets.push(g);
      }
    } else if (state.focusedRowIndex >= 0 && list[state.focusedRowIndex]) {
      targets.push(list[state.focusedRowIndex]);
    }
    if (!targets.length) { alert("Select rows (or focus a row with arrow keys) before adding a tag."); return; }
    const raw = prompt(`Add a tag to ${targets.length} game${targets.length === 1 ? "" : "s"} (lowercase, e.g. co-op, cozy, bedtime):`);
    if (!raw) return;
    let added = 0;
    for (const g of targets) if (addTagToGame(g, raw)) added++;
    renderTagChips();
    renderTable();
  });
  document.getElementById("tbody").addEventListener("change", e => {
    const t = e.target;
    if (t.classList.contains("row-select")) {
      const tr = t.closest("tr");
      toggleSelection(t.dataset.gameKey, t.checked);
      if (tr) tr.classList.toggle("row-selected", t.checked);
      return;
    }
    if (!t.dataset.gameKey || !t.dataset.field) return;
    const g = findGameByKey(t.dataset.gameKey);
    if (!g) return;
    const field = t.dataset.field;
    setPersonal(g, field, t.value);
    const tr = t.closest("tr");
    if (tr) updateRowInPlace(tr, g);
    const statusFilterActive = !!document.getElementById("statusFilter").value;
    const sortAffected = state.sortKey === field || state.sortKey === "status";
    if ((field === "status" && (statusFilterActive || state.cleanupModeActive)) || sortAffected) {
      scheduleTableRerender();
    }
  });
  document.getElementById("selectAllVisible").addEventListener("change", e => {
    const list = state._visibleList || sortedGames(filteredGames());
    if (e.target.checked) list.forEach(g => state.selectedKeys.add(gameKey(g)));
    else list.forEach(g => state.selectedKeys.delete(gameKey(g)));
    updateBulkBar();
    invalidateTableCache();
    renderTable();
  });
  document.querySelectorAll(".view-tab").forEach(btn => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view || "library";
      if (view === state.activeView) return;
      switchView(view);
    });
  });
  document.getElementById("cleanupModeBtn").addEventListener("click", () => {
    if (state.activeView !== "library") return;
    state.cleanupModeActive = !state.cleanupModeActive;
    updateCleanupBtnState();
    state.focusedRowIndex = 0;
    refreshFilterUI();
  });
  document.getElementById("bulkBar")?.addEventListener("click", e => {
    const btn = e.target.closest(".bulk-status");
    if (btn?.dataset.status) bulkSetStatus(btn.dataset.status);
  });
  document.getElementById("bulkClear").addEventListener("click", () => {
    state.selectedKeys.clear();
    updateBulkBar();
    invalidateTableCache();
    renderTable();
  });
  document.getElementById("tbody").addEventListener("blur", e => {
    const t = e.target;
    if (!t.classList.contains("notes-input")) return;
    const g = findGameByKey(t.dataset.gameKey);
    if (g) setPersonal(g, "notes", t.value);
  }, true);
  document.getElementById("tbody").addEventListener("click", e => {
    if (!e.target.closest("select, input, a, button, .row-tag-remove, .row-tag-add, [data-hltb-edit]")) {
      const tr = e.target.closest("tr[data-row-key]");
      if (tr) {
        state.focusedRowIndex = Number(tr.dataset.rowIndex || -1);
        focusRow(tr.dataset.rowKey);
      }
    }
    const removeBtn = e.target.closest(".row-tag-remove");
    if (removeBtn) {
      e.stopPropagation();
      const g = findGameByKey(removeBtn.dataset.gameKey);
      if (g) {
        removeTagFromGame(g, removeBtn.dataset.tag);
        const tr = removeBtn.closest("tr");
        updateTagCellInPlace(tr, g);
        scheduleTagChipsRefresh();
      }
      return;
    }
    const addBtn = e.target.closest(".row-tag-add");
    if (addBtn) {
      e.stopPropagation();
      const g = findGameByKey(addBtn.dataset.gameKey);
      if (!g) return;
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "tag…";
      input.maxLength = 32;
      input.className = "row-tag-input text-[11px] px-1.5 py-0.5 rounded-full border border-amber-500/60 bg-slate-700 text-amber-100 w-20 focus:outline-none focus:border-amber-300";
      addBtn.replaceWith(input);
      let done = false;
      const tr = input.closest("tr");
      const commit = () => {
        if (done) return;
        done = true;
        const raw = input.value;
        if (raw && raw.trim()) {
          addTagToGame(g, raw);
          updateTagCellInPlace(tr, g);
          scheduleTagChipsRefresh();
        } else if (input.parentNode) {
          input.replaceWith(addBtn);
        }
      };
      const cancel = () => {
        if (done) return;
        done = true;
        if (input.parentNode) input.replaceWith(addBtn);
      };
      input.addEventListener("keydown", ev => {
        if (ev.key === "Enter") { ev.preventDefault(); commit(); }
        else if (ev.key === "Escape") { ev.preventDefault(); cancel(); }
      });
      input.addEventListener("blur", commit);
      setTimeout(() => input.focus(), 0);
      return;
    }
    const btn = e.target.closest("[data-hltb-edit]");
    if (!btn) return;
    const g = findGameByKey(btn.dataset.hltbEdit);
    if (!g) return;
    if (e.shiftKey || e.altKey) {
      const existing = getPersonal(g).hltb_override ?? "";
      const next = prompt("Override HLTB main hours (blank to reset):", existing);
      if (next === null) return;
      const value = String(next).trim();
      setPersonal(g, "hltb_override", value === "" ? null : Number(value));
      renderTable();
      return;
    }
    const hltbName = g.hltb_name || g.name || "";
    if (!hltbName) return;
    const url = `https://howlongtobeat.com/?q=${encodeURIComponent(hltbName)}`;
    window.open(url, "_blank", "noopener");
  });
  document.addEventListener("click", e => {
    const card = e.target.closest(".pick-card");
    if (card) focusGame(card.dataset.gameKey);
  });
  document.addEventListener("keydown", handleGlobalKeydown);
  document.getElementById("pickForMe").addEventListener("click", e => {
    let list = filteredGames();
    if (state.activeView === "library") {
      if (!e.shiftKey) list = list.filter(g => getPersonal(g).status === "backlog");
    } else if (!e.shiftKey) {
      const onSale = list.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
      if (onSale.length) list = onSale;
    }
    if (!list.length) return;
    const pick = list[Math.floor(Math.random() * list.length)];
    focusGame(gameKey(pick));
  });
  document.getElementById("reloadData").addEventListener("click", async () => {
    kebabMenu.classList.remove("open");
    try { await reloadGames(); } catch { alert("Could not reload library files. Use Load Steam JSON… or run the fetch scripts."); }
  });
  kebabMenu.querySelectorAll("button, label").forEach(el => {
    el.addEventListener("click", () => kebabMenu.classList.remove("open"));
  });
  bindAddGameModal();
  document.getElementById("exportCsv").addEventListener("click", exportCsv);
  document.getElementById("exportTopBacklog")?.addEventListener("click", exportTopBacklogMarkdown);
  document.getElementById("exportNotes").addEventListener("click", () => download("baklog-notes.json", JSON.stringify(state.personal, null, 2), "application/json"));
  document.getElementById("importNotes").addEventListener("change", async e => {
    const file = e.target.files[0];
    if (!file) return;
    state.personal = { ...state.personal, ...JSON.parse(await file.text()) };
    savePersonal();
    renderSummary();
    renderPicks();
    renderTable();
    e.target.value = "";
  });
  document.getElementById("loadGamesFile").addEventListener("change", async e => {
    const file = e.target.files[0];
    if (!file) return;
    const data = JSON.parse(await file.text());
    if (data.store === "gog") {
      state.libraryMeta.gog = data;
      state.allGames = [
        ...state.allGames.filter(g => normalizeGame(g).store !== "gog"),
        ...(data.games || []).map(g => normalizeGame({ ...g, store: "gog", id: g.id ?? g.gog_id })),
      ];
    } else if (data.store === "psn") {
      state.libraryMeta.psn = data;
      state.allGames = [
        ...state.allGames.filter(g => normalizeGame(g).store !== "psn"),
        ...(data.games || []).map(g => normalizeGame({ ...g, store: "psn", id: g.id ?? g.psn_id })),
      ];
    } else if (data.store === "epic") {
      state.libraryMeta.epic = data;
      state.allGames = [
        ...state.allGames.filter(g => normalizeGame(g).store !== "epic"),
        ...(data.games || []).map(g => normalizeGame({ ...g, store: "epic", id: g.id })),
      ];
    } else if (data.store === "amazon") {
      state.libraryMeta.amazon = data;
      state.allGames = [
        ...state.allGames.filter(g => normalizeGame(g).store !== "amazon"),
        ...(data.games || []).map(g => normalizeGame({ ...g, store: "amazon", id: g.id ?? g.amazon_id })),
      ];
    } else {
      state.libraryMeta.steam = data;
      state.allGames = [
        ...state.allGames.filter(g => normalizeGame(g).store !== "steam"),
        ...(data.games || []).map(g => normalizeGame({ ...g, store: g.store || "steam", id: g.id ?? g.appid })),
      ];
    }
    applyMergedLibrary();
    e.target.value = "";
  });
}

// === Init ===
async function bootstrap() {
  initDashboard({
    getPersonal,
    gameKey,
    coverFallbackFor,
    normalizeGame,
    hltbMain,
    ratingValue,
    hasEnoughReviews,
    getDealInfo,
    itchIsGame,
    wishlistGamesWithDeals,
    dealScore,
    isStealDeal,
    dealHeroCardHtml,
    dealHeroEmptyHtml,
    dealSaleScoreboardCardHtml,
    dealStealsCardHtml,
    chipStatusKey,
    gameGenresCanonical,
    savePrefs,
    switchView,
    renderStoreChips,
    refreshFilterUI,
    renderGenreChips,
    invalidateTableCache,
    renderTable,
  });
  let migrationInfo = { migrated: true, pendingMigration: null };
  try {
    migrationInfo = await personalStore.init();
  } catch (err) {
    console.warn("[personalStore] init failed, falling back to localStorage", err);
  }
  migrateV3();
  state.prefs.genreFilters = (state.prefs.genreFilters || []).map(aliasCanonicalGenre);
  const VALID_VIEWS = new Set(["dashboard", "library", "wishlist", "itch", "connections"]);
  if (VALID_VIEWS.has(state.prefs.activeView)) {
    state.activeView = state.prefs.activeView;
  }
  applySavedSortForView(state.activeView);
  document.querySelectorAll(".view-tab").forEach(b => b.classList.toggle("active", b.dataset.view === state.activeView));
  savePrefs();
  bindEvents();
  document.getElementById("showScoreColumn").checked = !!state.prefs.showScoreColumn;
  document.getElementById("tableWrap")?.classList.toggle("table-hide-score", !state.prefs.showScoreColumn);
  document.getElementById("genreMode").value = state.prefs.genreFilterMode;
  document.getElementById("quickWinMax").value = state.prefs.quickWinMaxHours;
  document.getElementById("quickWinMaxVal").textContent = state.prefs.quickWinMaxHours;
  document.getElementById("picksContainer").classList.toggle("hidden", state.prefs.picksCollapsed);
  document.getElementById("togglePicks").textContent = state.prefs.picksCollapsed ? "Show" : "Hide";
  const dedupEl = document.getElementById("crossStoreDedup");
  if (dedupEl) dedupEl.checked = !!state.prefs.crossStoreDedup;
  document.getElementById("tagFilterMode").value = state.prefs.tagFilterMode || "OR";
  if (typeof state.prefs.itchHideNonGames !== "boolean") state.prefs.itchHideNonGames = true;
  const itchShowNonGamesEl = document.getElementById("itchShowNonGames");
  if (itchShowNonGamesEl) itchShowNonGamesEl.checked = !state.prefs.itchHideNonGames;
  updateCleanupBtnState();
  updateViewChrome();
  if (state.activeView === "library" && state.prefs.picksTab === "wishlistDeals") {
    state.prefs.picksTab = state.prefs.libraryPicksTab || "topRated";
    savePrefs();
  }
  renderStoreChips();
  renderWishlistStoreChips();
  renderBulkStatusButtons();
  renderPicksLimitButtons();
  const chartScript = document.querySelector('script[src*="chart.js"]');
  if (chartScript && !chartScript.dataset.bound) {
    chartScript.dataset.bound = "1";
    chartScript.addEventListener("load", () => {
      if (state.activeView === "dashboard") scheduleDashboardRender();
    });
  }
  try {
    await reloadGames();
  } catch {
    const banner = document.getElementById("bootErrorBanner");
    if (banner) {
      banner.innerHTML = '<div class="migration-banner-body"><span class="text-amber-400">No library data found. Run fetch scripts (<code class="bg-slate-700 px-1 rounded">fetch_games.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_gog.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_wishlist.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_itad.py</code>, …), then reload.</span></div>';
      banner.classList.remove("hidden");
    }
  }
  await loadFetcherSources();
  initConnections();
  fetcherRunner.probeApi().then(async available => {
    if (!available) return;
    await fetcherRunner.syncFromServer();
    if (state.activeView === "dashboard") {
      fetcherRunner.startDashboardPolling();
      renderDashboardFetcherHealth();
    }
  });
  if (migrationInfo.pendingMigration) {
    showMigrationBanner(migrationInfo.pendingMigration, {
      escapeHtml,
      onUploaded: () => reloadGames().then(() => scheduleDashboardRender()),
    });
  }
  if (state.activeView === "dashboard") scheduleDashboardRender();
}

hydrateState();
bootstrap();
