import { state, STATUS_CHIP_DEFS, ITCH_NON_GAME_CLASSIFICATIONS } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { isEarlyAccess } from './table-query.js';
import { STATUS_LABELS, WISHLIST_STATUS_LABELS } from './row-templates.js';
import { getPersonal, hasPersonalEntry } from './personal-storage.js';

// === Constants & config ===
export const STORE_PRIORITY = ["steam", "psn", "gog", "epic", "amazon", "nintendo", "itch", "xbox", "battlenet", "ubisoft", "other", "manual"];
export const JUNK_NAMES = new Set(["live", "fortnite", "hbo max", "hbo go"]);
const JUNK_NAME_PATTERNS = [
  /\btech beta\b/i,
  /\b(pre[- ]game )?editor\b/i,
  /\bresource archiver\b/i,
  /\bbeta\b$/i,
];

const MIN_REVIEW_COUNT = 50;

const RELEASE_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// === Game normalization & dedup ===
export function storePriority(store) {
  const idx = STORE_PRIORITY.indexOf(store);
  return idx === -1 ? STORE_PRIORITY.length : idx;
}

export function normalizeNameForDedup(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/[\u2122\u00ae\u00a9]/g, "")
    .replace(/[^a-z0-9]+/g, " ")
    .replace(/\b(remastered|edition|complete|gold|definitive|enhanced|classic|goty|of the year|game of the year|special|standard|deluxe|collection|anthology|pack|the)\b/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function isJunkEntry(g) {
  const raw = String(g.name || "").trim();
  if (!raw) return true;
  const lower = raw.toLowerCase();
  if (JUNK_NAMES.has(lower)) return true;
  return JUNK_NAME_PATTERNS.some(re => re.test(raw));
}

export function dedupeWithinStore(games) {
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

export function scoreEntry(g) {
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

export function recomputeCrossStoreHidden() {
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
    if (state.sessionPrefs.crossStoreDedup) {
      for (let i = 1; i < list.length; i++) {
        state.crossStoreHiddenKeys.add(gameKey(list[i]));
      }
    }
  }
  recomputeWishlistCrossStore();
}

export function wishlistEntryStore(g) {
  return g.wishlist_store || g.store_target || (g.manual ? "manual" : "steam");
}

export function recomputeWishlistCrossStore() {
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
    if (state.sessionPrefs.crossStoreDedup) {
      for (let i = 1; i < list.length; i++) {
        state.wishlistCrossStoreHiddenKeys.add(gameKey(list[i]));
      }
    }
  }
}

export function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  const store = g.store || "steam";
  const id = g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
  return { ...g, store, id };
}

export function gameStore(g) {
  return g.store || "steam";
}

export function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
}

export function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}

export function gameNumericId(g) {
  return gameId(g);
}

export function coverFallbackFor(g) {
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

export function isEpicPublicSlug(slug) {
  return EPIC_PUBLIC_SLUG.test(String(slug || "").trim());
}

export function isGenericStoreUrl(url) {
  if (!url) return true;
  const u = String(url).trim().replace(/\/$/, "");
  return GENERIC_STORE_URLS.has(u) || u === "https://gaming.amazon.com/home";
}

export function storeUrlForGame(g) {
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

export function storeLinkHtml(g, className, labelHtml) {
  const url = storeUrlForGame(g);
  if (!url) return `<span class="${className}">${labelHtml}</span>`;
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener" class="${className}">${labelHtml}</a>`;
}

export function hltbMain(g) {
  const p = getPersonal(g);
  if (p.hltb_override != null && p.hltb_override !== "") return +p.hltb_override;
  return g.hltb_main_hours;
}

export function ratingValue(g) {
  return g.steam_review_percent ?? 0;
}

export function hasEnoughReviews(g) {
  const pct = g.steam_review_percent;
  if (pct != null && pct > 0) return (g.steam_review_count || 0) >= MIN_REVIEW_COUNT;
  return false;
}

export function priorityScore(g) {
  const review = ratingValue(g);
  const h = hltbMain(g) || 20;
  return review / Math.log2(h + 2);
}

export function isHiddenGem(g) {
  const p = getPersonal(g);
  const rating = g.steam_review_percent ?? 0;
  return rating >= 90 && (g.playtime_minutes || 0) === 0 && p.status === "backlog";
}

export function earlyAccessRibbonHtml(g, { label = "EARLY ACCESS" } = {}) {
  return isEarlyAccess(g) ? `<span class="ea-ribbon" title="Early Access">${label}</span>` : "";
}

export function earlyAccessPillHtml(g) {
  return isEarlyAccess(g) ? '<span class="ea-pill" title="Early Access">EA</span>' : "";
}

export function coopPillsHtml(g) {
  if (!g) return "";
  const bits = [];
  if (g.coop_online) bits.push('<span class="coop-pill coop-pill-online" title="Online co-op">ONLINE CO-OP</span>');
  if (g.coop_local) bits.push('<span class="coop-pill coop-pill-local" title="Shared / split-screen co-op">COUCH CO-OP</span>');
  return bits.join("");
}

export function storeLetter(s) {
  return s === "gog" ? "G" : s === "psn" ? "P" : s === "epic" ? "E" : s === "amazon" ? "A" : s === "nintendo" ? "N" : s === "itch" ? "I" : s === "xbox" ? "X" : s === "battlenet" ? "B" : s === "ubisoft" ? "U" : s === "other" ? "?" : s === "manual" ? "M" : "S";
}

export function singleStoreBadgeHtml(s, title) {
  return `<span class="store-badge ${s}" title="${title || s.toUpperCase()}">${storeLetter(s)}</span>`;
}

export function storeBadgeHtml(g) {
  const primary = normalizeGame(g).store;
  const owned = state.crossStoreOwnedStores.get(gameKey(g));
  if (!owned || owned.length < 2) return singleStoreBadgeHtml(primary);
  const tip = `Owned on: ${owned.map(s => s.toUpperCase()).join(", ")}`;
  return `<span class="inline-flex items-center gap-0.5 align-middle" title="${tip}">${owned.map(s => singleStoreBadgeHtml(s, tip)).join("")}</span>`;
}

export function wishlistStatusSelectHtml(g, p) {
  const key = gameKey(g);
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="bg-slate-700 border border-slate-600 rounded text-xs py-1" title="Wishlist tracking">
    ${Object.entries(WISHLIST_STATUS_LABELS).map(([val, label]) => `<option value="${val}" ${p.status === val ? "selected" : ""}>${escapeHtml(label)}</option>`).join("")}
  </select>`;
}

export function bulkStatusOptsForView(view) {
  const labels = view === "wishlist" ? WISHLIST_STATUS_LABELS : STATUS_LABELS;
  return Object.entries(labels).map(([status, label]) => ({ status, label }));
}

export function renderBulkStatusButtons() {
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

export function tableColSpan() {
  return state.prefs.showScoreColumn ? 14 : 13;
}

export function wishlistBadgeHtml(g) {
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

export function formatHours(minutes) {
  return !minutes ? "0h" : `${(minutes / 60).toFixed(1)}h`;
}

export function formatDate(unixOrStr) {
  if (!unixOrStr) return "—";
  if (typeof unixOrStr === "number") {
    if (unixOrStr === 0) return "—";
    const dt = new Date(unixOrStr * 1000);
    return `${RELEASE_MONTHS[dt.getMonth()]} ${dt.getDate()}, ${dt.getFullYear()}`;
  }
  return formatReleaseDate(unixOrStr);
}

export function parseReleaseForSort(d) {
  const t = Date.parse(d || "");
  return isNaN(t) ? 0 : t;
}

export function formatReleaseDate(d) {
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

export function formatDollar(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "—";
  return num.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: num % 1 ? 2 : 0, maximumFractionDigits: 2 });
}

export function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === "game") return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

export function alphaBucket(name) {
  const ch = (name || "").trim().charAt(0);
  if (!ch || !/[A-Za-z]/.test(ch)) return "#";
  return ch.toUpperCase();
}

export function findGameByKey(key) {
  return state.allGames.find(g => gameKey(g) === key)
    || state.itchGames.find(g => gameKey(g) === key)
    || state.wishlistGames.find(g => gameKey(g) === key);
}

export function chipStatusKey(g) {
  if (!hasPersonalEntry(g)) return "backlog";
  return getPersonal(g).status || "backlog";
}

export function renderStatusChipsHtml(games, defs = STATUS_CHIP_DEFS) {
  const counts = Object.fromEntries(defs.map(d => [d.key, 0]));
  for (const g of games) {
    const k = chipStatusKey(g);
    if (k in counts) counts[k] = (counts[k] || 0) + 1;
  }
  const active = state.sessionPrefs?.statusFilter || "";
  return defs.map(def => {
    const n = counts[def.key] || 0;
    if (def.key === "__none__" && n === 0) return "";
    if (n === 0) return "";
    const isActive = active === def.key;
    const title = isActive ? `Clear ${def.label} filter` : `Filter: ${def.label}`;
    return `<button type="button" class="status-chip${isActive ? " active" : ""}" data-status-filter="${escapeAttr(def.key)}" title="${escapeAttr(title)}">${escapeHtml(def.label)} <span class="text-slate-100 font-semibold ml-1">${n}</span></button>`;
  }).join("");
}
