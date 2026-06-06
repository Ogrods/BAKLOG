import {
  state,
  STATUS_CHIP_DEFS,
  ITCH_NON_GAME_CLASSIFICATIONS,
  isCleanupCandidateFromParts,
} from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { isEarlyAccess } from './table-query.js';
import { STATUS_LABELS, WISHLIST_STATUS_LABELS } from './row-templates.js';
import { getPersonal, hasPersonalEntry } from './personal-storage.js';
import { COOP_NAME_OVERRIDES } from './coop-overrides.js';
import { formatMoney, displayCurrency } from './currency.js';
import { storeLogoHtml, storeLetter } from './store-logos.js';

export { storeLetter };

// === Constants & config ===
export const STORE_PRIORITY = ["steam", "psn", "gog", "epic", "amazon", "nintendo", "itch", "xbox", "battlenet", "ubisoft", "humble", "ea", "other", "manual"];

// --- The blacklist ---------------------------------------------------------
// JUNK_NAMES + JUNK_NAME_PATTERNS are the "blacklist": entries that are not
// games at all (store apps, DLC skins, soundtracks, internal entitlement
// slugs). isJunkEntry() drops them unconditionally — they are never shown and
// users cannot restore them. This is distinct from the "hidden list" (see
// js/hidden-defaults.js), which is real games a user has chosen to hide and can
// restore from the Hidden games panel. Blacklist = noise, hardcoded; hidden
// list = user-editable. Python fetchers carry mirror blacklists at the source
// (e.g. _is_entitlement_slug in fetch_epic.py, psn_client.py, gog_filters.py).
export const JUNK_NAMES = new Set([
  "live",
  "hbo max",
  "hbo go",
  "shadow costume for sonic",
  "sonic holiday costume",
  "lego sonic skin",
]);
const JUNK_NAME_PATTERNS = [
  /\btech beta\b/i,
  /\b(pre[- ]game )?editor\b/i,
  /\bresource archiver\b/i,
  /\bbeta\b$/i,
  // "<Character> Costume for <Game>" pattern — Nintendo eShop lists these as
  // full SKUs alongside real games. "Costume Quest" is a legit title so we
  // require the "for" form to avoid false positives.
  /\bcostume for\b/i,
  // Epic ships PTR/public-testing branches as separate library entries
  // (e.g. "Chivalry 2 - Public Testing"). Drop them so they don't shadow
  // the real release.
  /\bpublic testing\b/i,
  // Cosmetic wallpaper SKUs (e.g. Epic "HD Wallpaper", "Death Stranding — HD
  // Wallpaper") get listed as standalone library entries and can pick up a
  // mismatched Steam score. Match a trailing "wallpaper" only, so legit titles
  // like "Wallpaper Engine" are unaffected. Mirrors psn_client.py.
  /\bwallpaper$/i,
  // Epic internal entitlement slugs leak in as titles (e.g.
  // "Fortnite_StWContent", "Fortnite_Studio"): a single token with no spaces
  // joined by an underscore. Real titles use spaces ("Aerial_Knight's Never
  // Yield" has a space, so it is unaffected). Mirrors _is_entitlement_slug in
  // fetch_epic.py.
  /^\S*_\S*$/,
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

/**
 * Resolved at first call to keep startup ordering simple. Map<normalizedName, { coop_online?, coop_local? }>.
 */
let _coopOverrideMap = null;

function coopOverrideMap() {
  if (_coopOverrideMap) return _coopOverrideMap;
  _coopOverrideMap = new Map();
  for (const o of COOP_NAME_OVERRIDES) {
    const norm = normalizeNameForDedup(o.name);
    if (!norm) continue;
    _coopOverrideMap.set(norm, o);
  }
  return _coopOverrideMap;
}

/**
 * Applies COOP_NAME_OVERRIDES to a freshly-loaded library row.
 *
 * Mutates the row in place. Steam rows are skipped — fetch_games.py is
 * authoritative for Steam co-op flags. Override flags only ever turn co-op
 * ON (never clear an existing true), so a future Steam category change can't
 * silently override our hand-set non-Steam flags.
 */
export function applyCoopOverrides(g) {
  if (!g) return g;
  const store = (g.store || "").toLowerCase();
  if (store === "steam") return g;
  const norm = normalizeNameForDedup(g.name);
  if (!norm) return g;
  const o = coopOverrideMap().get(norm);
  if (!o) return g;
  if (o.coop_online) g.coop_online = true;
  if (o.coop_local) g.coop_local = true;
  return g;
}

/**
 * Blacklist check: true when an entry is not a real game (store apps, DLC
 * skins, soundtracks, entitlement slugs) and should be dropped silently. This
 * is the hardcoded blacklist — not the user-editable hidden list. See the
 * JUNK_NAMES comment above and js/hidden-defaults.js.
 */
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
  state.crossStorePlaytimeByKey = new Map();
  state.playedTitleNorms = new Set();
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
    let groupTotal = 0;
    for (const g of list) {
      groupTotal += Math.max(0, Number(g.playtime_minutes) || 0);
    }
    if (groupTotal > 0) {
      const playedNorm = normalizeNameForDedup(list[0].name);
      if (playedNorm) state.playedTitleNorms.add(playedNorm);
    }
    if (state.sessionPrefs.crossStoreDedup) {
      const repKey = gameKey(list[0]);
      let total = 0;
      const perStore = [];
      for (const g of list) {
        const minutes = Math.max(0, Number(g.playtime_minutes) || 0);
        total += minutes;
        perStore.push({ store: normalizeGame(g).store, minutes });
      }
      // Only record an aggregate when at least one sibling has playtime;
      // otherwise combinedPlaytime() can short-circuit to the raw value.
      if (total > 0) {
        state.crossStorePlaytimeByKey.set(repKey, { total, perStore });
      }
      for (let i = 1; i < list.length; i++) {
        state.crossStoreHiddenKeys.add(gameKey(list[i]));
      }
    }
  }
  recomputeWishlistCrossStore();
}

/**
 * Returns the playtime to display for a row. For cross-store dedup
 * representatives this is the SUM across every store in the group; otherwise
 * the row's own `playtime_minutes`. Always returns a finite number (0 when no
 * data). Read-only — there is no UI for editing this value.
 */
export function combinedPlaytime(g) {
  if (!g) return 0;
  const entry = state.crossStorePlaytimeByKey?.get(gameKey(g));
  if (entry) return entry.total;
  return Math.max(0, Number(g.playtime_minutes) || 0);
}

/** Title-attribute breakdown like "Steam: 12.3h · PSN: 4.7h". Empty when no aggregate. */
export function combinedPlaytimeTooltip(g) {
  const entry = state.crossStorePlaytimeByKey?.get(gameKey(g));
  if (!entry) return "";
  const parts = entry.perStore
    .filter(p => p.minutes > 0)
    .map(p => `${p.store.toUpperCase()}: ${(p.minutes / 60).toFixed(1)}h`);
  if (parts.length < 2) return "";
  return `Combined across stores - ${parts.join(" · ")}`;
}

export function isCleanupCandidate(g) {
  const p = getPersonal(g);
  const explicitBacklog = hasPersonalEntry(g) && p.status === "backlog";
  const norm = normalizeNameForDedup(g.name);
  const played = combinedPlaytime(g) > 0 || !!(norm && state.playedTitleNorms?.has(norm));
  const rating = ratingValue(g);
  const releaseMs = parseReleaseForSort(g.release_date);
  return isCleanupCandidateFromParts({ explicitBacklog, played, rating, releaseMs });
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
  const id = g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id ?? g.humble_id ?? g.ea_id;
  return { ...g, store, id };
}

export function gameStore(g) {
  return g.store || "steam";
}

export function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id ?? g.humble_id ?? g.ea_id;
}

export function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}

export function gameNumericId(g) {
  return gameId(g);
}

export function sanitizeCoverUrl(url) {
  if (!url) return "";
  const u = String(url).trim();
  return u.replace("://images-eds.xboxlive.com/", "://images-eds-ssl.xboxlive.com/");
}

export function coverFallbackFor(g) {
  const ng = normalizeGame(g);
  if (ng.header_image) return sanitizeCoverUrl(ng.header_image);
  if (ng.store === "steam") return `https://cdn.akamai.steamstatic.com/steam/apps/${ng.id}/header.jpg`;
  return "";
}

/** Primary library cover URL with CDN hostname fixes applied. */
export function libraryCoverFor(g) {
  return sanitizeCoverUrl(g?.library_image) || coverFallbackFor(g);
}

const STEAM_CDN = "https://cdn.akamai.steamstatic.com/steam/apps";

/** Steam app id from store/id or from a steamstatic image URL on the row. */
export function steamAppIdFromGame(g) {
  const ng = normalizeGame(g);
  if (ng.store === "steam" && ng.id != null && ng.id !== "") return String(ng.id);
  for (const url of [ng.header_image, ng.library_image]) {
    const u = sanitizeCoverUrl(url);
    if (!u) continue;
    const m = u.match(/steamstatic\.com\/steam\/apps\/(\d+)\//);
    if (m) return m[1];
  }
  return null;
}

export function steamLibraryHeroUrl(appId) {
  if (appId == null || appId === "") return "";
  return `${STEAM_CDN}/${appId}/library_hero.jpg`;
}

/** Spotlight art URLs, best-first: hero → 600×900 portrait → header/square → other covers. */
export function spotlightArtCandidates(g) {
  const ng = normalizeGame(g);
  const seen = new Set();
  const out = [];
  const push = (url) => {
    const u = sanitizeCoverUrl(url);
    if (!u || seen.has(u)) return;
    seen.add(u);
    out.push(u);
  };
  const appId = steamAppIdFromGame(ng);
  if (appId) {
    push(steamLibraryHeroUrl(appId));
    push(`${STEAM_CDN}/${appId}/library_600x900_2x.jpg`);
    push(`${STEAM_CDN}/${appId}/library_600x900.jpg`);
  }
  push(ng.library_image);
  push(ng.header_image);
  const lib = libraryCoverFor(ng);
  if (lib) push(lib);
  return out;
}

export function spotlightArtUrl(g) {
  const c = spotlightArtCandidates(g);
  return c[0] || "";
}

/** object-fit / object-position for dashboard spotlight from loaded aspect ratio. */
export function spotlightCropForAspect(ratio) {
  if (!Number.isFinite(ratio) || ratio <= 0) {
    return { fit: "cover", pos: "35% center", portrait: false };
  }
  if (ratio >= 2) return { fit: "cover", pos: "50% 40%", portrait: false };
  if (ratio >= 1.4) return { fit: "cover", pos: "35% center", portrait: false };
  return { fit: "contain", pos: "center", portrait: true };
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
  // PSN: prefer the store concept page over the cached store_url. Historical
  // data on disk often has a psnprofiles trophy URL even when a concept_id is
  // present (cross-platform dedup inherited concept_id but kept the
  // trophy-fallback URL). Skip the generic store_url short-circuit for PSN so
  // the resolver below can pick the concept page first.
  if (ng.store === "psn") {
    if (ng.concept_id) {
      return `https://store.playstation.com/en-us/concept/${ng.concept_id}`;
    }
    // No concept_id — send users to PSN store search instead of the cached
    // trophy URL, which isn't a store link at all.
    if (ng.name) {
      return `https://store.playstation.com/en-us/search/${encodeURIComponent(ng.name)}`;
    }
    return "https://store.playstation.com/en-us/";
  }
  // Amazon: entitlement titles — ignore cached retail /dp/ or /s?k= store_url.
  if (ng.store === "amazon") {
    if (ng.name && ng.steam_review_percent != null) {
      return `https://store.steampowered.com/search/?term=${encodeURIComponent(ng.name)}`;
    }
    return "https://luna.amazon.com/";
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
  if (ng.store === "epic") {
    return `https://store.epicgames.com/en-US/browse?q=${encodeURIComponent(ng.name || "")}`;
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
  if (ng.store === "humble") {
    if (url && url.startsWith("http")) return url;
    const slug = ng.humble_id || (typeof ng.id === "string" && ng.id.startsWith("humble-") ? ng.id.slice(7) : null);
    if (slug) return `https://www.humblebundle.com/store/${encodeURIComponent(slug)}`;
    return `https://www.humblebundle.com/store/search?search=${encodeURIComponent(ng.name || "")}`;
  }
  if (ng.store === "ea") {
    if (url && url.startsWith("http")) return url;
    const slug = ng.ea_game_slug;
    if (slug) return `https://www.ea.com/games/${encodeURIComponent(slug)}`;
    return `https://www.ea.com/search?q=${encodeURIComponent(ng.name || "")}`;
  }
  return url && url.startsWith("http") && !isGenericStoreUrl(url) ? url : null;
}

export function storeLinkHtml(g, className, labelHtml) {
  const url = storeUrlForGame(g);
  const store = normalizeGame(g).store || 'store';
  const tip = `Open on ${store}`;
  if (!url) return `<span class="${className}" title="${escapeAttr(tip)}">${labelHtml}</span>`;
  return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener" class="${className}" title="${escapeAttr(tip)}">${labelHtml}</a>`;
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

export function trophyProgressPillHtml(g) {
  if (!g || g.trophy_progress == null) return "";
  const pct = Math.round(g.trophy_progress);
  const store = (g.store || "").toLowerCase();
  const label = store === "psn"
    ? "PSN trophy completion"
    : store === "xbox"
      ? "Xbox achievement completion"
      : "Completion";
  const gsCur = g.xbox_gamerscore_current;
  const gsTotal = g.xbox_gamerscore_total;
  const gsCurAttr = gsCur != null ? ` data-gs-cur="${gsCur}"` : "";
  const gsTotalAttr = gsTotal != null ? ` data-gs-total="${gsTotal}"` : "";
  const tip = `${label}: ${pct}%`;
  return `<button type="button" class="trophy-pill" data-trophy-pop data-store="${escapeAttr(store)}" data-pct="${pct}" data-label="${escapeAttr(label)}"${gsCurAttr}${gsTotalAttr} aria-label="${escapeAttr(tip)}" aria-haspopup="true" aria-expanded="false" title="${escapeAttr(tip)}">&#127942; ${pct}%</button>`;
}

export function singleStoreBadgeHtml(s, title) {
  return storeLogoHtml(s, { size: 'sm', title: title || s.toUpperCase() });
}

export function storeBadgeHtml(g) {
  // When a manual row shares an id with a fetched row, each catalog entry keeps
  // its own badge: manual rows show the dashed custom outline; fetched rows show
  // cross-store ownership when applicable.
  const primary = normalizeGame(g).store;
  const owned = state.crossStoreOwnedStores.get(gameKey(g));
  if (!owned || owned.length < 2) {
    if (g.manual) {
      const tip = `${primary.toUpperCase()} (custom)`;
      return storeLogoHtml(primary, { size: 'sm', title: tip, manual: true });
    }
    return singleStoreBadgeHtml(primary);
  }
  const tip = `Owned on: ${owned.map(s => s.toUpperCase()).join(", ")}`;
  return `<span class="inline-flex items-center gap-0.5 align-middle" title="${tip}">${owned.map(s => singleStoreBadgeHtml(s, tip)).join("")}</span>`;
}

export function wishlistStatusSelectHtml(g, p) {
  const key = gameKey(g);
  return `<select data-game-key="${escapeAttr(key)}" data-field="status" class="row-ctl rounded text-xs py-1" title="Wishlist tracking">
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
    ({ status, label }) => `<button type="button" class="bulk-status px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-xs" data-status="${escapeAttr(status)}" title="Set selected games to ${escapeAttr(label)}">${escapeHtml(label)}</button>`,
  ).join("");
}

export function tableColSpan() {
  return state.prefs.showScoreColumn ? 14 : 13;
}

export function wishlistBadgeHtml(g) {
  const target = wishlistEntryStore(g);
  const owned = state.wishlistCrossStoreOwnedStores.get(gameKey(g));
  if (owned && owned.length > 1) {
    const tip = `Wishlisted on: ${owned.map(s => s.toUpperCase()).join(", ")}`;
    return `<span class="inline-flex items-center gap-0.5 align-middle" title="${tip}">${owned.map(s => singleStoreBadgeHtml(s, tip)).join("")}</span>`;
  }
  const tip = `Wishlist · ${target.toUpperCase()}${g.manual ? " (manual)" : ""}`;
  return storeLogoHtml(target, { size: 'sm', title: tip, manual: !!g.manual });
}

export function formatHours(minutes) {
  return !minutes ? "0h" : `${(minutes / 60).toFixed(1)}h`;
}

export function formatDate(unixOrStr) {
  if (!unixOrStr) return " - ";
  if (typeof unixOrStr === "number") {
    if (unixOrStr === 0) return " - ";
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
  if (!d) return " - ";
  const s = String(d).trim();
  if (!s) return " - ";
  if (/^to\s+be\s+announced$/i.test(s) || /^to\s+be\s+determined$/i.test(s)) return "TBA";
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
  return formatMoney(n, displayCurrency());
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

/** norm title → gameKey[] across library + wishlist + itch catalogs. */
let _titleKeyIndexVer = -1;
let _titleKeyIndex = null;

function catalogGamesFingerprint() {
  return (state.allGames?.length || 0)
    + (state.wishlistGames?.length || 0) * 1e6
    + (state.itchGames?.length || 0) * 1e9;
}

export function buildTitleKeyIndex() {
  const index = new Map();
  const all = [...(state.allGames || []), ...(state.wishlistGames || []), ...(state.itchGames || [])];
  for (const g of all) {
    const norm = normalizeNameForDedup(g.name);
    if (!norm) continue;
    const key = gameKey(g);
    if (!index.has(norm)) index.set(norm, []);
    const list = index.get(norm);
    if (!list.includes(key)) list.push(key);
  }
  return index;
}

export function getTitleKeyIndex() {
  const ver = catalogGamesFingerprint();
  if (!_titleKeyIndex || _titleKeyIndexVer !== ver) {
    _titleKeyIndex = buildTitleKeyIndex();
    _titleKeyIndexVer = ver;
  }
  return _titleKeyIndex;
}

/** Every store copy of the same normalized title (canonical tag group). */
export function getSameTitleKeys(g) {
  const norm = normalizeNameForDedup(g?.name);
  if (!norm) return [gameKey(g)];
  return getTitleKeyIndex().get(norm) || [gameKey(g)];
}

export function invalidateTitleKeyIndex() {
  _titleKeyIndex = null;
  _titleKeyIndexVer = -1;
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
