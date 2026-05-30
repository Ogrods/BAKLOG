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
  STATUS_FILTER_LABELS,
} from './state.js';
import { collectTableParams, queryGamesAsync } from './table-query.js';
import { shouldVirtualize, virtualRange } from './virtual-table.js';
import { buildStatusSelect, buildPrioritySelect } from './row-templates.js';
import { createMemo } from './memo.js';

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
}

window.coverFallback = function (img) {
  const fb = img.dataset.fallback;
  if (fb && img.src !== fb) {
    img.src = fb;
    img.dataset.fallback = "";
    return;
  }
  const name = img.dataset.name || "";
  const cls = img.classList.contains("pick-cover") ? "pick-cover placeholder" : "cover placeholder";
  img.outerHTML = `<div class="${cls}" title="${name.replace(/"/g, "&quot;")}">${name.slice(0, 18)}</div>`;
};
window.markLandscape = function (img) {
  if (img.naturalWidth && img.naturalHeight && img.naturalWidth > img.naturalHeight * 1.1) {
    img.classList.add("landscape");
  }
};

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
  }, 250);
}
function flushSavePersonal() {
  if (!_savePersonalTimer) return;
  clearTimeout(_savePersonalTimer);
  _savePersonalTimer = null;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.personal));
}
window.addEventListener("beforeunload", flushSavePersonal);
window.addEventListener("blur", flushSavePersonal);
function loadPrefs() {
  const fallback = { picksTab: "topRated", libraryPicksTab: "topRated", itchPicksTab: "topRated", itchHideNonGames: true, picksCollapsed: false, showScoreColumn: false, genreFilters: [], genreFilterMode: "OR", quickWinMaxHours: 15, storeFilter: "", crossStoreDedup: true, picksLimit: 16, tagFilters: [], tagFilterMode: "OR", dealOnSaleOnly: false, dealHistoricalLowOnly: false, dealHideOwned: false, dealMinDiscount: 0, dealMaxPrice: 100, wishlistSortInitialized: false };
  try { return { ...fallback, ...(JSON.parse(localStorage.getItem(PREFS_KEY) || "{}")) }; } catch { return fallback; }
}
function savePrefs() { localStorage.setItem(PREFS_KEY, JSON.stringify(state.prefs)); }
function loadManualGames() {
  try {
    const raw = JSON.parse(localStorage.getItem(MANUAL_KEY) || "[]");
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}
function saveManualGames(list) { localStorage.setItem(MANUAL_KEY, JSON.stringify(list)); }
let manualGames = loadManualGames();
function addManualGame(g) {
  manualGames = loadManualGames();
  const dupIdx = manualGames.findIndex(m => m.id === g.id && m.store === g.store);
  if (dupIdx >= 0) manualGames[dupIdx] = g;
  else manualGames.push(g);
  saveManualGames(manualGames);
}
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
function ratingValue(g) { return g.steam_review_percent ?? g.metacritic_score ?? 0; }
const MIN_REVIEW_COUNT = 50;
function hasEnoughReviews(g) {
  const pct = g.steam_review_percent;
  if (pct != null && pct > 0) return (g.steam_review_count || 0) >= MIN_REVIEW_COUNT;
  return (g.metacritic_score || 0) > 0;
}
function priorityScore(g) {
  const p = getPersonal(g);
  const review = ratingValue(g);
  const h = hltbMain(g) || 20;
  return (review * (p.priority + 1)) / Math.log2(h + 2);
}
function isHiddenGem(g) {
  const p = getPersonal(g);
  const rating = g.steam_review_percent ?? g.metacritic_score ?? 0;
  return rating >= 90 && (g.playtime_minutes || 0) === 0 && p.status === "backlog";
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
  const opts = [
    ["backlog", "Watching"],
    ["next", "Want it"],
    ["skip", "Pass"],
    ["finished", "Bought"],
  ];
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="bg-slate-700 border border-slate-600 rounded text-xs py-1" title="Wishlist tracking">
    ${opts.map(([val, label]) => `<option value="${val}" ${p.status === val ? "selected" : ""}>${label}</option>`).join("")}
  </select>`;
}

function tableColSpan() {
  return state.prefs.showScoreColumn ? 15 : 14;
}

function wishlistBadgeHtml(g) {
  const target = g.wishlist_store || g.store_target || (g.manual ? "manual" : "steam");
  const cls = target === "gog" ? "gog" : target === "epic" ? "epic" : target === "psn" ? "psn" : target === "amazon" ? "amazon" : target === "nintendo" ? "nintendo" : target === "xbox" ? "xbox" : target === "battlenet" ? "battlenet" : target === "ubisoft" ? "ubisoft" : target === "itch" ? "itch" : target === "manual" ? "other" : "steam";
  const letter = target === "gog" ? "G" : target === "epic" ? "E" : target === "psn" ? "P" : target === "amazon" ? "A" : target === "nintendo" ? "N" : target === "xbox" ? "X" : target === "battlenet" ? "B" : target === "ubisoft" ? "U" : target === "itch" ? "I" : target === "manual" ? "M" : "S";
  const manualMark = g.manual ? " manual" : "";
  const tip = `Wishlist · ${target.toUpperCase()}${g.manual ? " (manual)" : ""}`;
  return `<span class="store-badge ${cls}${manualMark}" title="${tip}">W${letter}</span>`;
}
function formatHours(minutes) { return !minutes ? "0h" : `${(minutes / 60).toFixed(1)}h`; }
function formatDate(unixOrStr) {
  if (!unixOrStr) return "—";
  if (typeof unixOrStr === "number") return unixOrStr === 0 ? "—" : new Date(unixOrStr * 1000).toLocaleDateString();
  return unixOrStr;
}
function parseReleaseForSort(d) { const t = Date.parse(d || ""); return isNaN(t) ? 0 : t; }
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function escapeAttr(s) { return String(s ?? "").replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;"); }
function formatNum(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return String(n);
  return Math.abs(num) >= 10000 ? num.toLocaleString("en-US") : String(num);
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
    return {
      source: "itad",
      price: itad.price,
      regular: itad.regular,
      cut: itad.cut || 0,
      isHistoricalLow: !!itad.is_historical_low,
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

function renderStatusChipsHtml(games) {
  const counts = Object.fromEntries(STATUS_CHIP_DEFS.map(d => [d.key, 0]));
  for (const g of games) {
    const k = chipStatusKey(g);
    counts[k] = (counts[k] || 0) + 1;
  }
  const active = document.getElementById("statusFilter")?.value || "";
  return STATUS_CHIP_DEFS.map(def => {
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

function jumpToLetter(letter) {
  const list = sortedGames(filteredGames());
  const idx = list.findIndex(g => alphaBucket(g.name) === letter);
  if (idx < 0) return;
  state.focusedRowIndex = idx;
  const key = gameKey(list[idx]);
  state.pickedKey = key;
  focusRow(key);
  scrollFocusedRow();
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
  const bar = document.getElementById("bulkBar");
  const n = state.selectedKeys.size;
  document.getElementById("bulkCount").textContent = `${n} selected`;
  const show = n > 0 && state.activeView === "library";
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
  renderTable();
}

function bulkSetPriority(priority) {
  for (const key of state.selectedKeys) {
    const g = findGameByKey(key);
    if (g) setPersonal(g, "priority", priority);
  }
  state.selectedKeys.clear();
  updateBulkBar();
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
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : (g.metacritic_score != null ? `${g.metacritic_score}` : "—");
  const h = hltbMain(g);
  const store = normalizeGame(g).store;
  const badge = store === "gog" ? "G" : store === "psn" ? "P" : store === "epic" ? "E" : store === "amazon" ? "A" : store === "nintendo" ? "N" : store === "xbox" ? "X" : store === "battlenet" ? "B" : store === "ubisoft" ? "U" : store === "other" ? "?" : "S";
  return `
    <div class="pick-card relative bg-slate-700/50 rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" title="${escapeAttr(g.name)} · ${rating}${h != null ? ` · ${h}h` : ""}">
      <span class="pick-store store-badge ${store}">${badge}</span>
      <img class="pick-cover" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
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
  const nextUp = visible.filter(g => getPersonal(g).status === "next").sort((a, b) => {
    const pa = getPersonal(a).priority;
    const pb = getPersonal(b).priority;
    if (pb !== pa) return pb - pa;
    return ratingValue(b) - ratingValue(a);
  });
  const quickWins = visible
    .filter(g => getPersonal(g).status === "backlog" && ratingValue(g) >= 75 && hasEnoughReviews(g) && (hltbMain(g) || 999) <= state.prefs.quickWinMaxHours)
    .sort((a, b) => ratingValue(b) - ratingValue(a));
  const hidden = visible.filter(g => isHiddenGem(g) && hasEnoughReviews(g)).sort((a, b) => ratingValue(b) - ratingValue(a));
  const returnTo = visible
    .filter(g => getPersonal(g).status === "unfinished")
    .sort((a, b) => {
      const pa = getPersonal(a).priority;
      const pb = getPersonal(b).priority;
      if (pb !== pa) return pb - pa;
      const la = a.last_played ? Date.parse(a.last_played) : 0;
      const lb = b.last_played ? Date.parse(b.last_played) : 0;
      if (lb !== la) return lb - la;
      return ratingValue(b) - ratingValue(a);
    });
  const wishlistDeals = state.wishlistGames
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
  document.getElementById("picksGrid").innerHTML = data.length
    ? data.slice(0, limit).map(renderCard).join("")
    : `<div class="col-span-full text-sm text-slate-400 italic">${emptyMsg}</div>`;
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
  const lowFlag = d && d.isHistoricalLow ? '<span class="deal-flag-low" title="Historical low">★ low</span>' : "";
  const rating = g.steam_review_percent != null ? `${g.steam_review_percent}%` : "";
  const ownedFlag = isOwnedByTitle(g.name) ? '<span class="text-amber-400 text-[10px]" title="Already owned elsewhere">owned</span>' : "";
  const shop = d && d.shop ? d.shop : "";
  return `
    <div class="pick-card relative bg-slate-700/50 rounded p-2 cursor-pointer" data-game-key="${escapeAttr(key)}" data-pick-context="wishlist" title="${escapeAttr(g.name)}${cutLabel ? ` · ${cutLabel}` : ""}${shop ? ` @ ${shop}` : ""}">
      <span class="pick-store store-badge steam">W</span>
      <img class="pick-cover" src="${cover}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />
      <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(g.name)}</div>
      <div class="text-xs text-slate-400 flex justify-between items-center gap-1">
        <span class="text-slate-100">${priceLabel}</span>
        <span class="flex items-center gap-1">
          ${cutLabel ? `<span class="${cutClass}">${cutLabel}</span>` : ""}
          ${lowFlag}
        </span>
      </div>
      <div class="text-[10px] text-slate-500 flex justify-between mt-0.5">
        <span class="truncate">${escapeHtml(shop)}</span>
        <span class="flex items-center gap-1">${rating}${ownedFlag ? ` ${ownedFlag}` : ""}</span>
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

// === Dashboard ===
const dashboardCharts = {};
let _dashboardRenderTimer = null;
const DASH_STORE_COLORS = {
  steam: "#ea580c", gog: "#6d28d9", psn: "#003791", epic: "#64748b",
  amazon: "#c2410c", xbox: "#107C10", battlenet: "#148EFF", ubisoft: "#FFD200",
  nintendo: "#E60012", itch: "#fa5c5c", other: "#94a3b8", manual: "#64748b",
};
const DASH_STATUS_COLORS = {
  backlog: "#64748b", next: "#38bdf8", playing: "#10b981", unfinished: "#a855f7",
  live: "#ec4899", finished: "#94a3b8", skip: "#475569", __none__: "#334155",
};
const DASH_STORE_LABELS = {
  steam: "Steam", gog: "GOG", psn: "PSN", epic: "Epic", amazon: "Amazon",
  xbox: "Xbox", battlenet: "Battle.net", ubisoft: "Ubisoft", nintendo: "Nintendo",
  itch: "itch.io", other: "Other", manual: "Manual",
};

function destroyDashboardCharts() {
  Object.values(dashboardCharts).forEach(c => { try { c.destroy(); } catch (_) {} });
  Object.keys(dashboardCharts).forEach(k => delete dashboardCharts[k]);
}

function dashboardLibraryGames() {
  return state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g)));
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

function dashDrillStore(store) {
  state.prefs.storeFilter = store || "";
  savePrefs();
  document.getElementById("statusFilter").value = "";
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
}

function dashDrillStatus(status) {
  document.getElementById("statusFilter").value = status || "";
  state.prefs.storeFilter = "";
  savePrefs();
  switchView("library");
  renderStoreChips();
  refreshFilterUI();
}

function dashDrillGenre(genre) {
  if (!state.prefs.genreFilters.includes(genre)) state.prefs.genreFilters.push(genre);
  savePrefs();
  switchView("library");
  renderGenreChips();
  refreshFilterUI();
}

function dashDrillTag(tag) {
  const cur = state.prefs.tagFilters || [];
  if (!cur.includes(tag)) state.prefs.tagFilters = [...cur, tag];
  savePrefs();
  switchView("library");
  renderTagChips();
  refreshFilterUI();
}

function renderDashboardKPIs(games) {
  const backlog = games.filter(g => getPersonal(g).status === "backlog");
  const backlogHrs = backlog.reduce((s, g) => s + (hltbMain(g) || 0), 0);
  const playedHrs = games.reduce((s, g) => s + (g.playtime_minutes || 0), 0) / 60;
  const nonSkip = games.filter(g => getPersonal(g).status !== "skip");
  const finished = games.filter(g => getPersonal(g).status === "finished").length;
  const completion = nonSkip.length ? Math.round((finished / nonSkip.length) * 100) : 0;
  const rated = games.filter(g => ratingValue(g) > 0);
  const avgRating = rated.length ? Math.round(rated.reduce((s, g) => s + ratingValue(g), 0) / rated.length) : "—";
  const wlDeals = state.wishlistGames.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
  const itchGameCount = state.itchGames.filter(itchIsGame).length;
  const stores = new Set(games.map(g => normalizeGame(g).store)).size;
  const kpis = [
    { label: "Library games", value: formatNum(games.length) },
    { label: "Backlog hours", value: `${formatNum(Math.round(backlogHrs))}h` },
    { label: "Played hours", value: `${formatNum(Math.round(playedHrs))}h` },
    { label: "Completion", value: `${completion}%` },
    { label: "Avg review", value: avgRating === "—" ? "—" : `${avgRating}%` },
    { label: "Wishlist deals", value: formatNum(wlDeals) },
    { label: "Itch games", value: formatNum(itchGameCount) },
    { label: "Stores", value: stores },
  ];
  document.getElementById("dashboardKpis").innerHTML = kpis.map(k => `
    <div class="dash-kpi">
      <div class="dash-kpi-label">${escapeHtml(k.label)}</div>
      <div class="dash-kpi-value">${escapeHtml(String(k.value))}</div>
    </div>`).join("");
}

function renderDashboardLists(games) {
  const topRated = games
    .filter(g => getPersonal(g).status === "backlog" && ratingValue(g) > 0 && hasEnoughReviews(g))
    .sort((a, b) => ratingValue(b) - ratingValue(a))
    .slice(0, 10);
  const quickWins = games
    .filter(g => getPersonal(g).status === "backlog" && (hltbMain(g) || 999) <= (state.prefs.quickWinMaxHours || 15) && ratingValue(g) >= 80)
    .sort((a, b) => ratingValue(b) - ratingValue(a))
    .slice(0, 10);
  const listHtml = (items, scoreFn) => items.length
    ? items.map(g => {
      const cover = g.library_image || coverFallbackFor(g);
      const score = scoreFn(g);
      return `<div class="dash-list-row"><img class="dash-list-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" onerror="window.coverFallback(this)" /><span class="truncate flex-1">${escapeHtml(g.name)}</span><span class="text-slate-400">${score}</span></div>`;
    }).join("")
    : '<p class="text-xs text-slate-500 italic">No matches yet.</p>';
  document.getElementById("dashTopRated").innerHTML = listHtml(topRated, g => `${ratingValue(g)}%`);
  document.getElementById("dashQuickWins").innerHTML = listHtml(quickWins, g => `${hltbMain(g) || "?"}h`);
}

function renderDashboardWishlistStats() {
  const wl = state.wishlistGames;
  const onSale = wl.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
  const lows = wl.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; });
  const cuts = onSale.map(g => effectiveDiscountPercent(g)).filter(c => c > 0);
  const avgDisc = cuts.length ? Math.round(cuts.reduce((s, c) => s + c, 0) / cuts.length) : 0;
  const pctLow = wl.length ? Math.round((lows.length / wl.length) * 100) : 0;
  const tiers = { lt25: 0, m25: 0, m50: 0, m75: 0 };
  onSale.forEach(g => {
    const c = effectiveDiscountPercent(g);
    if (c >= 75) tiers.m75++;
    else if (c >= 50) tiers.m50++;
    else if (c >= 25) tiers.m25++;
    else tiers.lt25++;
  });
  document.getElementById("dashboardWishlistStats").innerHTML = `
    <div class="dash-card"><div class="dash-kpi-label">Avg discount (on sale)</div><div class="dash-kpi-value mt-1">${avgDisc}%</div><div class="text-xs text-slate-500 mt-1">${onSale.length} of ${wl.length} on sale</div></div>
    <div class="dash-card"><div class="dash-kpi-label">Historical low</div><div class="dash-kpi-value mt-1">${pctLow}%</div><div class="text-xs text-slate-500 mt-1">${lows.length} titles at all-time low</div></div>
    <div class="dash-card"><div class="dash-kpi-label">Deal tiers</div><div class="text-xs text-slate-300 mt-2" style="display:grid;gap:0.15rem;"><div>&lt;25%: ${tiers.lt25}</div><div>25–49%: ${tiers.m25}</div><div>50–74%: ${tiers.m50}</div><div>75%+: ${tiers.m75}</div></div></div>`;
}

function renderDashboardItchRecap() {
  const el = document.getElementById("dashItchRecap");
  const chartWrap = document.getElementById("dashItchChartWrap");
  if (!el) return;
  const total = state.itchGames.length;
  if (!total) {
    el.innerHTML = `<p>No itch.io data loaded. Run <code style="color:#e2e8f0">fetch_itch.py</code>, then reload.</p>`;
    if (chartWrap) chartWrap.style.display = "none";
    if (dashboardCharts.chartItchStatus) {
      dashboardCharts.chartItchStatus.destroy();
      delete dashboardCharts.chartItchStatus;
    }
    return;
  }
  const gamesOnly = state.itchGames.filter(itchIsGame);
  const rated = gamesOnly.filter(g => ratingValue(g) > 0).length;
  const withStatus = gamesOnly.filter(g => chipStatusKey(g) !== "__none__").length;
  const recent = [...gamesOnly].sort((a, b) => (b.release_date || "").localeCompare(a.release_date || "")).slice(0, 5);
  el.innerHTML = `
    <p><strong>${formatNum(gamesOnly.length)}</strong> videogames of <strong>${formatNum(total)}</strong> owned keys · <strong>${formatNum(rated)}</strong> with review scores · <strong>${formatNum(withStatus)}</strong> with a status</p>
    ${recent.length ? `<p class="dash-itch-muted">Recent: ${recent.map(g => escapeHtml(g.name)).join(" · ")}</p>` : ""}
    <p class="dash-itch-muted mt-2"><button type="button" class="summary-jump-chip px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs border border-slate-600 cursor-pointer" data-jump-view="itch">Open itch.io tab →</button></p>`;
  const counts = {};
  STATUS_CHIP_DEFS.forEach(d => { counts[d.key] = 0; });
  gamesOnly.forEach(g => { counts[chipStatusKey(g)] = (counts[chipStatusKey(g)] || 0) + 1; });
  const statusEntries = STATUS_CHIP_DEFS.filter(d => (counts[d.key] || 0) > 0);
  if (chartWrap) chartWrap.style.display = statusEntries.length ? "" : "none";
  if (!statusEntries.length) return;
  const labels = statusEntries.map(d => d.label);
  const data = statusEntries.map(d => counts[d.key]);
  const colors = statusEntries.map(d => DASH_STATUS_COLORS[d.key] || "#64748b");
  setDashboardChart("chartItchStatus", {
    type: "doughnut",
    data: { labels, datasets: [{ data, backgroundColor: colors, borderWidth: 0 }] },
    options: dashChartOptions({
      plugins: {
        legend: {
          position: "bottom",
          labels: { color: "#ffffff", font: { size: 11 }, boxWidth: 10 },
        },
      },
    }),
  });
}

function renderDashboardCharts(games) {
  const storeCounts = {};
  games.forEach(g => {
    const s = normalizeGame(g).store;
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
  games.forEach(g => { statusCounts[chipStatusKey(g)]++; });
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
  games.forEach(g => gameGenresCanonical(g).forEach(c => {
    genreCounts[c] = (genreCounts[c] || 0) + 1;
  }));
  const topGenres = Object.entries(genreCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  setDashboardChart("chartGenresBar", {
    type: "bar",
    data: {
      labels: topGenres.map(([g]) => g),
      datasets: [{ label: "Games", data: topGenres.map(([, n]) => n), backgroundColor: "#38bdf8" }],
    },
    options: dashChartOptions({
      indexAxis: "y",
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onClick(_evt, elements) { if (elements.length) dashDrillGenre(topGenres[elements[0].index][0]); },
    }),
  });

  const stores = [...new Set(games.map(g => normalizeGame(g).store))].sort();
  const backlogByStore = { backlog: {}, playing: {}, finished: {} };
  stores.forEach(s => { backlogByStore.backlog[s] = 0; backlogByStore.playing[s] = 0; backlogByStore.finished[s] = 0; });
  games.forEach(g => {
    const st = getPersonal(g).status;
    const store = normalizeGame(g).store;
    const hrs = hltbMain(g) || 0;
    if (st === "backlog") backlogByStore.backlog[store] += hrs;
    else if (st === "playing") backlogByStore.playing[store] += hrs;
    else if (st === "finished") backlogByStore.finished[store] += hrs;
  });
  const storeBrandColors = stores.map(s => DASH_STORE_COLORS[s] || "#64748b");
  setDashboardChart("chartBacklogStore", {
    type: "bar",
    data: {
      labels: stores.map(s => DASH_STORE_LABELS[s] || s),
      datasets: [
        { label: "Backlog",  data: stores.map(s => backlogByStore.backlog[s]),  backgroundColor: storeBrandColors.map(c => c + "FF"), borderColor: storeBrandColors, borderWidth: 1 },
        { label: "Playing",  data: stores.map(s => backlogByStore.playing[s]),  backgroundColor: "#38bdf8",                             borderColor: "#0ea5e9",       borderWidth: 2 },
        { label: "Finished", data: stores.map(s => backlogByStore.finished[s]), backgroundColor: storeBrandColors.map(c => c + "55"), borderColor: storeBrandColors, borderWidth: 1 },
      ],
    },
    options: dashChartOptions({
      indexAxis: "y",
      plugins: {
        legend: {
          labels: {
            color: "#ffffff",
            boxWidth: 14,
            font: { size: 12, weight: "500" },
            generateLabels() {
              return [
                { text: "Backlog",  fillStyle: "#94a3b8FF", strokeStyle: "#cbd5e1", lineWidth: 1, fontColor: "#ffffff", hidden: false },
                { text: "Playing",  fillStyle: "#38bdf8",   strokeStyle: "#0ea5e9", lineWidth: 2, fontColor: "#ffffff", hidden: false },
                { text: "Finished", fillStyle: "#94a3b855", strokeStyle: "#cbd5e1", lineWidth: 1, fontColor: "#ffffff", hidden: false },
              ];
            },
          },
          onClick: () => {},
        },
      },
      scales: { x: { stacked: true, ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { stacked: true, ticks: { color: "#94a3b8" }, grid: { display: false } } },
    }),
  });

  const buckets = ["0–2h", "2–5h", "5–10h", "10–20h", "20–40h", "40h+"];
  const bucketCounts = [0, 0, 0, 0, 0, 0];
  games.filter(g => getPersonal(g).status === "backlog").forEach(g => {
    const h = hltbMain(g);
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
    options: dashChartOptions({ plugins: { legend: { display: false } }, scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } } } }),
  });

  const reviewBuckets = {
    "Overwhelmingly Positive": 0, "Very Positive": 0, "Mostly Positive": 0,
    "Mixed": 0, "Mostly Negative": 0, "Negative": 0, "Unreviewed": 0,
  };
  games.forEach(g => {
    const d = g.steam_review_desc;
    if (d && reviewBuckets[d] !== undefined) reviewBuckets[d]++;
    else if (ratingValue(g) > 0) reviewBuckets.Mixed++;
    else reviewBuckets.Unreviewed++;
  });
  const revEntries = Object.entries(reviewBuckets).filter(([, n]) => n > 0);
  setDashboardChart("chartReviewDonut", {
    type: "doughnut",
    data: {
      labels: revEntries.map(([k]) => k),
      datasets: [{ data: revEntries.map(([, n]) => n), backgroundColor: ["#22c55e", "#34d399", "#86efac", "#fbbf24", "#f97316", "#ef4444", "#475569"].slice(0, revEntries.length), borderWidth: 0 }],
    },
    options: dashChartOptions({ plugins: { legend: { position: "right" } } }),
  });

  const yearCounts = {};
  games.forEach(g => {
    const y = (g.release_date || "").slice(0, 4);
    if (y && /^\d{4}$/.test(y) && +y >= 1990) yearCounts[y] = (yearCounts[y] || 0) + 1;
  });
  const years = Object.keys(yearCounts).sort();
  setDashboardChart("chartReleases", {
    type: "bar",
    data: { labels: years, datasets: [{ label: "Games", data: years.map(y => yearCounts[y]), backgroundColor: "#0ea5e9" }] },
    options: dashChartOptions({ scales: { x: { ticks: { color: "#94a3b8", maxRotation: 45 }, grid: { display: false } }, y: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } } } }),
  });

  const scatterPts = games.filter(g => ratingValue(g) > 0 && hltbMain(g) != null && hltbMain(g) > 0).map(g => ({
    x: hltbMain(g),
    y: ratingValue(g),
    label: g.name,
  }));
  setDashboardChart("chartScatter", {
    type: "scatter",
    data: {
      datasets: [{
        label: "Games",
        data: scatterPts.map(p => ({ x: p.x, y: p.y })),
        backgroundColor: "rgba(56, 189, 248, 0.5)",
        borderColor: "rgba(56, 189, 248, 0.85)",
        borderWidth: 0.5,
        pointRadius: 3,
        pointHoverRadius: 6,
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
        tooltip: {
          callbacks: {
            label(ctx) {
              const pt = scatterPts[ctx.dataIndex];
              return pt ? `${pt.label}: ${pt.x}h · ${pt.y}%` : "";
            },
          },
        },
      },
    }),
  });

  const tagCounts = {};
  games.forEach(g => (getPersonal(g).tags || []).forEach(t => { tagCounts[t] = (tagCounts[t] || 0) + 1; }));
  const topTags = Object.entries(tagCounts).sort((a, b) => b[1] - a[1]).slice(0, 12);
  setDashboardChart("chartTagsBar", {
    type: "bar",
    data: { labels: topTags.map(([t]) => t), datasets: [{ label: "Games", data: topTags.map(([, n]) => n), backgroundColor: "#f59e0b" }] },
    options: dashChartOptions({
      indexAxis: "y",
      scales: { x: { ticks: { color: "#94a3b8" }, grid: { color: "#334155" } }, y: { ticks: { color: "#94a3b8" }, grid: { display: false } } },
      onClick(_evt, elements) { if (elements.length) dashDrillTag(topTags[elements[0].index][0]); },
    }),
  });
}

function renderDashboard() {
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
  renderDashboardKPIs(games);
  renderDashboardItchRecap();
  try {
    renderDashboardCharts(games);
  } catch (err) {
    console.error("Dashboard charts error:", err);
  }
  renderDashboardWishlistStats();
  try {
    renderDashboardLists(games);
  } catch (err) {
    console.error("Dashboard lists error:", err);
  }
}

function scheduleDashboardRender() {
  if (state.activeView !== "dashboard") return;
  clearTimeout(_dashboardRenderTimer);
  _dashboardRenderTimer = setTimeout(renderDashboard, 80);
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
    const wl = state.wishlistGames;
    const onSale = wl.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; });
    const lows = wl.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; });
    const owned = wl.filter(g => isOwnedByTitle(g.name)).length;
    const cuts = onSale.map(g => effectiveDiscountPercent(g)).filter(c => c > 0);
    const avgDisc = cuts.length ? Math.round(cuts.reduce((s, c) => s + c, 0) / cuts.length) : null;
    const prices = wl.map(g => effectiveSortPrice(g)).filter(p => p != null);
    const avgPrice = prices.length ? (prices.reduce((s, p) => s + p, 0) / prices.length).toFixed(2) : null;
    el.innerHTML = `
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Wishlist <span class="text-slate-100 font-semibold ml-1">${wl.length}</span></div>
      <div class="px-3 py-2 rounded-full bg-emerald-900/40 border border-emerald-700/50 text-xs">On sale <span class="text-emerald-200 font-semibold ml-1">${onSale.length}</span></div>
      <div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Historical low <span class="text-amber-300 font-semibold ml-1">${lows.length}</span></div>
      ${avgDisc != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg discount <span class="text-slate-100 font-semibold ml-1">${avgDisc}%</span></div>` : ""}
      ${avgPrice != null ? `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">Avg price <span class="text-slate-100 font-semibold ml-1">$${avgPrice}</span></div>` : ""}
      ${owned ? `<div class="px-3 py-2 rounded-full bg-amber-900/30 border border-amber-700/40 text-xs">Already owned <span class="text-amber-200 font-semibold ml-1">${owned}</span></div>` : ""}`;
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
      return `<div class="px-3 py-2 rounded-full bg-slate-800 text-xs">${s.label} <span class="text-slate-100 font-semibold ml-1">${s.count}</span></div>`;
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
  return (p.tags || []).map(t => `<span class="row-tag inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-amber-700/40 border border-amber-500/40 text-[11px] text-amber-100">${escapeHtml(t)}<button type="button" class="row-tag-remove text-amber-200 hover:text-white" data-game-key="${escapeAttr(key)}" data-tag="${escapeAttr(t)}" title="Remove tag" aria-label="Remove tag">×</button></span>`).join("") + `<button type="button" class="row-tag-add text-[11px] px-1.5 py-0.5 rounded-full border border-dashed border-slate-500 text-slate-400 hover:text-slate-100 hover:border-slate-300" data-game-key="${escapeAttr(key)}" title="Add a tag">+ tag</button>`;
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
    const cut = itad.cut ? ` (-${itad.cut}%)` : "";
    const low = itad.is_historical_low ? " 🔥" : "";
    const shop = itad.shop ? ` @ ${itad.shop}` : "";
    return `${itad.price_str}${cut}${low}${shop}`;
  }
  if (!g.price && g.discount_percent == null) return "—";
  const base = g.price || "N/A";
  if ((g.discount_percent || 0) > 0) {
    return `${base} (-${g.discount_percent}%)`;
  }
  return base;
}

function focusGame(key) {
  state.pickedKey = key;
  const targetIsWishlist = String(key).startsWith("wishlist:");
  const targetIsItch = String(key).startsWith("itch:");
  if (targetIsWishlist && state.activeView !== "wishlist") {
    switchView("wishlist");
  } else if (targetIsItch && state.activeView !== "itch") {
    switchView("itch");
  } else if (!targetIsWishlist && !targetIsItch && state.activeView !== "library") {
    switchView("library");
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
  if (idx >= 0) state.focusedRowIndex = idx;
  renderTable();
  scrollFocusedRow();
}

function scrollRowToCenter(row) {
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
}

function scrollFocusedRow() {
  const scrollEl = document.getElementById("tableWrap");
  if (state._virtualActive && scrollEl && state.focusedRowIndex >= 0) {
    const targetTop = state.focusedRowIndex * 56 - scrollEl.clientHeight / 2 + 28;
    scrollEl.scrollTop = Math.max(0, targetTop);
    renderTable({ virtualOnly: true });
    const row = document.querySelector("tr.row-focused");
    if (row) return;
  }
  scrollRowToCenter(document.querySelector("tr.row-focused"));
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
    gen: state.prefs.genreFilters || [],
    gm: state.prefs.genreFilterMode,
    tags: state.prefs.tagFilters || [],
    tm: state.prefs.tagFilterMode,
    deal: [state.prefs.dealOnSaleOnly, state.prefs.dealHistoricalLowOnly, state.prefs.dealHideOwned, state.prefs.dealMinDiscount, state.prefs.dealMaxPrice],
    unp: !!state.prefs.unplayedOnly,
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
      <td class="p-2 text-center">${state.activeView === "library" ? `<input type="checkbox" class="row-select rounded" data-game-key="${escapeAttr(key)}" ${selected ? "checked" : ""} />` : ""}</td>
      <td class="p-2"><img class="cover" src="${g.library_image || headerFallback}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" /></td>
      <td class="p-2">
        <div class="flex items-center gap-1.5">
          ${storeLinkHtml(g, "text-sky-400 hover:underline font-medium game-name", escapeHtml(g.name))}
          ${hiddenGem ? '<span class="text-purple-400" title="Hidden gem: 90%+ rated and unplayed">✦</span>' : ""}
          ${ownedWish ? '<span class="text-amber-400 text-xs" title="You already own this (matched by title)">owned</span>' : ""}
        </div>
        <div class="mt-1">
          ${state.activeView === "wishlist" ? wishlistBadgeHtml(g) : storeBadgeHtml(g)}
        </div>
        ${lowConf && g.hltb_name ? `<div class="text-xs text-amber-400">HLTB match: ${escapeHtml(g.hltb_name)}</div>` : ""}
      </td>
      ${isWish ? `<td class="p-2">${wishlistStatusSelectHtml(g, p)}</td>` : `<td class="p-2">${buildStatusSelect(key, p.status)}</td>`}
      <td class="p-2 text-center">${buildPrioritySelect(key, p.priority)}</td>
      <td class="col-score p-2 text-right">${priorityScore(g).toFixed(1)}</td>
      <td class="p-2 text-right text-slate-300">${formatHours(g.playtime_minutes)}</td>
      <td class="p-2 text-right">
        <button data-hltb-edit="${escapeAttr(key)}" class="bg-slate-700 hover:bg-slate-600 px-2 py-1 rounded text-xs">${hltbLabel(g)}</button>
      </td>
      <td class="p-2 text-right">${g.steam_review_percent != null ? `${g.steam_review_percent}%` : "—"}</td>
      <td class="p-2 text-right">${g.metacritic_score ?? "—"}</td>
      <td class="p-2 text-right">${formatPrice(g)}</td>
      <td class="p-2 text-slate-300">${g.release_date || "—"}</td>
      <td class="p-2 text-slate-300">${formatDate(g.last_played)}</td>
      <td class="p-2 text-slate-400 text-xs max-w-[120px] truncate" title="${(g.genres || []).filter(x => !isPlatformToken(x)).join(", ")}">${(g.genres || []).filter(x => !isPlatformToken(x)).slice(0, 2).join(", ") || "—"}</td>
      <td class="p-2 min-w-[180px]">
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
    const range = virtualRange(scrollEl.scrollTop, scrollEl.clientHeight, list.length);
    ({ start, end, topPad, bottomPad } = range);
  } else if (opts.resetScroll && scrollEl) {
    scrollEl.scrollTop = 0;
  }
  state._virtualStart = start;
  const parts = [];
  parts.push(`<tr class="virtual-spacer" aria-hidden="true"><td colspan="${colSpan}" style="height:${topPad}px;padding:0;border:0"></td></tr>`);
  for (let i = start; i < end; i++) {
    parts.push(tableRowHtml(list[i], i, { isWish, showScore }));
  }
  parts.push(`<tr class="virtual-spacer" aria-hidden="true"><td colspan="${colSpan}" style="height:${bottomPad}px;padding:0;border:0"></td></tr>`);
  tbody.innerHTML = parts.join("");
}

async function renderTable(opts) {
  const force = !!opts?.force;
  const virtualOnly = !!opts?.virtualOnly;
  const fp = tableFingerprint();
  if (!force && !virtualOnly && fp === _tableFingerprint && _lastRenderedView === state.activeView) {
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
    selectAll.disabled = state.activeView === "wishlist" || state.activeView === "itch";
    selectAll.checked = state.activeView === "library" && list.length > 0 && list.every(g => state.selectedKeys.has(gameKey(g)));
  }

  if (state.focusedRowIndex >= list.length) state.focusedRowIndex = list.length - 1;
  if (state.focusedRowIndex < 0 && list.length) state.focusedRowIndex = 0;

  paintTableBody(list, { resetScroll: force && !virtualOnly });

  let base;
  if (state.activeView === "wishlist") {
    const onSale = list.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
    const lows = list.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; }).length;
    const dealBits = [];
    if (onSale) dealBits.push(`${onSale} on sale`);
    if (lows) dealBits.push(`${lows} at historical low`);
    const tail = dealBits.length ? ` · ${dealBits.join(", ")}` : "";
    base = `Wishlist: ${list.length} of ${state.wishlistGames.length}${tail}`;
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
}

// === Drawer + active pills ===
const NON_GENRE_TOKENS = new Set([
  "ps3", "ps4", "ps5", "psp", "ps vita", "psvita", "vita",
  "xbox", "xbox 360", "xbox one", "xbox series x", "xbox series s", "xbox series x|s", "xbox series x/s", "xbox series",
  "nintendo switch", "switch", "wii", "wii u", "ds", "3ds", "nintendo ds", "nintendo 3ds",
  "pc", "windows", "mac", "macos", "osx", "linux", "steamos",
  "ios", "android", "browser", "stadia", "google stadia",
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
  for (const g of state.prefs.genreFilters || []) pills.push({ kind: "genre", value: g, label: g });
  for (const t of state.prefs.tagFilters || []) pills.push({ kind: "tag", value: t, label: `#${t}` });
  if (document.getElementById("unplayedOnly").checked) pills.push({ kind: "unplayed", value: "1", label: "Unplayed only" });
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
    case "genre":
      state.prefs.genreFilters = (state.prefs.genreFilters || []).filter(x => x !== value);
      savePrefs();
      break;
    case "tag":
      state.prefs.tagFilters = (state.prefs.tagFilters || []).filter(x => x !== value);
      savePrefs();
      break;
    case "unplayed": document.getElementById("unplayedOnly").checked = false; break;
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
  document.getElementById("minRating").value = "0";
  document.getElementById("minRatingVal").textContent = "0";
  document.getElementById("maxHours").value = "200";
  document.getElementById("maxHoursVal").textContent = "200+";
  state.prefs.storeFilter = "";
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
  updateWishlistDrawerVisibility();
  updatePickTabsVisibility();
  updatePicksChrome();
  document.getElementById("picksSection")?.classList.toggle("hidden", isDash);
  document.getElementById("toolbarSection")?.classList.toggle("hidden", isDash);
  document.getElementById("tableShell")?.classList.toggle("hidden", isDash);
  document.getElementById("rowCount")?.classList.toggle("hidden", isDash);
  document.getElementById("alphaNav")?.classList.toggle("dashboard-hidden", isDash);
  document.getElementById("dashboardContainer")?.classList.toggle("hidden", !isDash);
  document.getElementById("libraryStatusSection")?.classList.toggle("hidden", isWish || isDash);
  document.getElementById("itchFilterSection")?.classList.toggle("hidden", !isItch);
  document.getElementById("libraryStoreSection")?.classList.toggle("hidden", isWish || isItch || isDash);
  document.getElementById("libraryMiscSection")?.classList.toggle("hidden", isWish || isItch || isDash);
  if (isDash) scheduleDashboardRender();
  else destroyDashboardCharts();
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
  const label = view === "dashboard" ? "Loading dashboard…" : view === "wishlist" ? "Loading wishlist…" : view === "itch" ? "Loading itch.io…" : "Loading library…";
  if (useOverlay) showViewLoading(label);
  const doSwitch = () => {
    if (fromView === "dashboard") {
      clearTimeout(_dashboardRenderTimer);
      destroyDashboardCharts();
    }
    invalidateTableCache();
    state.activeView = view;
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
      if (state.prefs.wishlistSortVersion !== 2) {
        state.sortKey = "deal_price";
        state.sortDir = 1;
        state.prefs.wishlistSortInitialized = true;
        state.prefs.wishlistSortVersion = 2;
      }
    } else if (view === "itch") {
      state.cleanupModeActive = false;
      if (fromView === "library" && state.prefs.picksTab && state.prefs.picksTab !== "topRated") {
        state.prefs.libraryPicksTab = state.prefs.picksTab;
      }
      state.prefs.picksTab = "topRated";
    } else {
      state.prefs.picksTab = state.prefs.libraryPicksTab || "topRated";
    }
    savePrefs();
    updateCleanupBtnState();
    updateBulkBar();
    updateViewChrome();
    refreshFilterUI();
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

function exportCsv() {
  const list = sortedGames(filteredGames());
  const isWish = state.activeView === "wishlist";
  const headers = isWish
    ? ["store", "wishlist_store", "id", "name", "tracking_status", "priority", "deal_price", "deal_discount_pct", "deal_shop", "historical_low", "steam_review_percent", "metacritic", "hltb_main", "release_date", "genres", "tags", "notes", "store_url"]
    : ["store", "id", "name", "status", "priority", "score", "playtime_hours", "hltb_main", "hltb_main_extra", "hltb_completionist", "steam_review_percent", "metacritic", "price", "discount_percent", "release_date", "genres", "tags", "notes"];
  const rows = list.map(g => {
    const p = getPersonal(g);
    const ng = normalizeGame(g);
    const d = getDealInfo(g);
    if (isWish) {
      return [
        ng.store, g.wishlist_store ?? "", ng.id, g.name, p.status, p.priority,
        d?.price != null ? d.price.toFixed(2) : "", effectiveDiscountPercent(g) || "",
        d?.shop ?? "", d?.isHistoricalLow ? "yes" : "",
        g.steam_review_percent ?? "", g.metacritic_score ?? "", hltbMain(g) ?? "",
        g.release_date ?? "", (g.genres || []).join("; "), (p.tags || []).join("; "), p.notes,
        g.store_url ?? d?.url ?? "",
      ];
    }
    return [
      ng.store, ng.id, g.name, p.status, p.priority, priorityScore(g).toFixed(2), (g.playtime_minutes / 60).toFixed(1),
      hltbMain(g) ?? "", g.hltb_main_extra_hours ?? "", g.hltb_completionist_hours ?? "", g.steam_review_percent ?? "", g.metacritic_score ?? "",
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
  try {
    const data = await fetchLibraryJson("itad_prices.json");
    state.itadByKey = data?.by_key || {};
  } catch {
    state.itadByKey = {};
  }
}

function applyMergedLibrary() {
  window._dataVersion = (window._dataVersion || 0) + 1;
  personalMemo.bump();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  buildOwnedNormNames();
  const parts = [];
  if (state.libraryMeta.steam) parts.push(`Steam ${state.libraryMeta.steam.game_count} (${new Date(state.libraryMeta.steam.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.gog) parts.push(`GOG ${state.libraryMeta.gog.game_count} (${new Date(state.libraryMeta.gog.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.psn) parts.push(`PSN ${state.libraryMeta.psn.game_count} (${new Date(state.libraryMeta.psn.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.epic) parts.push(`Epic ${state.libraryMeta.epic.game_count} (${new Date(state.libraryMeta.epic.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.amazon) parts.push(`Amazon ${state.libraryMeta.amazon.game_count} (${new Date(state.libraryMeta.amazon.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.xbox) parts.push(`Xbox ${state.libraryMeta.xbox.game_count} (${new Date(state.libraryMeta.xbox.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.battlenet) parts.push(`Battle.net ${state.libraryMeta.battlenet.game_count} (${new Date(state.libraryMeta.battlenet.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.ubisoft) parts.push(`Ubisoft ${state.libraryMeta.ubisoft.game_count} (${new Date(state.libraryMeta.ubisoft.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.nintendo) parts.push(`Nintendo ${state.libraryMeta.nintendo.game_count} (${new Date(state.libraryMeta.nintendo.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.itch) parts.push(`itch.io ${state.libraryMeta.itch.game_count} (${new Date(state.libraryMeta.itch.fetched_at).toLocaleString()})`);
  if (state.libraryMeta.wishlist) parts.push(`Wishlist ${state.libraryMeta.wishlist.game_count}`);
  if (state.libraryMeta.wishlistGog) parts.push(`Wishlist GOG ${state.libraryMeta.wishlistGog.game_count}`);
  if (Object.keys(state.itadByKey).length) parts.push(`ITAD prices ${Object.keys(state.itadByKey).length}`);
  document.getElementById("meta").textContent = parts.length ? parts.join(" · ") : "No library data loaded";
  renderStoreChips();
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
  const steamData = steam;
  if (!steamData && !gog && !psn && !epic && !amazon && !nintendo && !itch && !xbox && !battlenet && !ubisoft) throw new Error("No library files found");
  state.libraryMeta.steam = steamData;
  state.libraryMeta.gog = gog;
  state.libraryMeta.psn = psn;
  state.libraryMeta.epic = epic;
  state.libraryMeta.amazon = amazon;
  state.libraryMeta.nintendo = nintendo;
  state.libraryMeta.itch = itch;
  state.libraryMeta.xbox = xbox;
  state.libraryMeta.battlenet = battlenet;
  state.libraryMeta.ubisoft = ubisoft;
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualLibrary = allManual.filter(g => !g.wishlist);
  const manualWishlist = allManual.filter(g => !!g.wishlist);
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
  const wishlist = await fetchLibraryJson("games_wishlist.json");
  const wishlistGog = await fetchLibraryJson("games_wishlist_gog.json");
  state.libraryMeta.wishlist = wishlist;
  state.libraryMeta.wishlistGog = wishlistGog;
  const fetchedWishlist = [
    ...((wishlist?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? g.appid }))),
    ...((wishlistGog?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: `gog-${g.id ?? g.gog_id}`, wishlist_store: "gog" }))),
  ];
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
  await loadItadPrices();
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
  document.querySelectorAll(".store-chip").forEach(chip => {
    chip.classList.toggle("active", chip.dataset.store === (state.prefs.storeFilter || ""));
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
    metacritic_score: null,
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
    metacritic_score: null,
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
    state.focusedRowIndex = Math.min((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex + 1), list.length - 1);
    renderTable();
    scrollFocusedRow();
    return;
  }
  if (e.key === "ArrowUp") {
    e.preventDefault();
    state.focusedRowIndex = Math.max((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex - 1), 0);
    renderTable();
    scrollFocusedRow();
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
  if (e.key >= "1" && e.key <= "5") {
    e.preventDefault();
    const g = list[state.focusedRowIndex] || list[0];
    if (g) { setPersonal(g, "priority", +e.key); renderTable(); }
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
  const tableWrap = document.getElementById("tableWrap");
  tableWrap?.addEventListener("scroll", () => {
    if (!state._virtualActive) return;
    cancelAnimationFrame(_virtualScrollRaf);
    _virtualScrollRaf = requestAnimationFrame(() => renderTable({ virtualOnly: true }));
  }, { passive: true });

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
  ["search", "statusFilter", "unplayedOnly", "minRating", "maxHours"].forEach(id => {
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
  document.getElementById("storeChips").addEventListener("click", e => {
    const chip = e.target.closest(".store-chip");
    if (!chip) return;
    if (chip.dataset.store === "itch") { switchView("itch"); return; }
    state.prefs.storeFilter = chip.dataset.store || "";
    savePrefs();
    renderStoreChips();
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
    setPersonal(g, field, field === "priority" ? +t.value : t.value);
    const tr = t.closest("tr");
    if (tr) updateRowInPlace(tr, g);
    const statusFilterActive = !!document.getElementById("statusFilter").value;
    const sortAffected = state.sortKey === field || state.sortKey === "priority_score" || state.sortKey === "status";
    if ((field === "status" && (statusFilterActive || state.cleanupModeActive)) || sortAffected) {
      scheduleTableRerender();
    }
  });
  document.getElementById("selectAllVisible").addEventListener("change", e => {
    const list = state._visibleList || sortedGames(filteredGames());
    if (e.target.checked) list.forEach(g => state.selectedKeys.add(gameKey(g)));
    else list.forEach(g => state.selectedKeys.delete(gameKey(g)));
    updateBulkBar();
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
  document.querySelectorAll(".bulk-status").forEach(btn => {
    btn.addEventListener("click", () => bulkSetStatus(btn.dataset.status));
  });
  document.getElementById("bulkApplyPriority").addEventListener("click", () => {
    const v = document.getElementById("bulkPriority").value;
    if (v === "") return;
    bulkSetPriority(+v);
  });
  document.getElementById("bulkClear").addEventListener("click", () => {
    state.selectedKeys.clear();
    updateBulkBar();
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
    const existing = getPersonal(g).hltb_override ?? "";
    const next = prompt("Override HLTB main hours (blank to reset):", existing);
    if (next === null) return;
    const value = String(next).trim();
    setPersonal(g, "hltb_override", value === "" ? null : Number(value));
    renderTable();
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
  document.getElementById("exportNotes").addEventListener("click", () => download("steam-backlog-notes.json", JSON.stringify(state.personal, null, 2), "application/json"));
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
  migrateV3();
  state.prefs.genreFilters = (state.prefs.genreFilters || []).map(aliasCanonicalGenre);
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
    document.getElementById("meta").innerHTML = '<span class="text-amber-400">Run fetch scripts (<code class="bg-slate-700 px-1 rounded">fetch_games.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_gog.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_wishlist.py</code>, <code class="bg-slate-700 px-1 rounded">fetch_itad.py</code>, …), then reload.</span>';
  }
  if (state.activeView === "dashboard") scheduleDashboardRender();
}
hydrateState();
bootstrap();
