import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import {
  normalizeGame,
  dedupeWithinStore,
  recomputeCrossStoreHidden,
  applyCoopOverrides,
  gameKey,
} from './game-core.js';
import {
  applyItadPriceSnapshot,
  slimItadSnapshot,
  buildOwnedNormNames,
} from './deals.js';
import {
  loadManualGames,
  bumpPersonalMemo,
  canonicalizeNotesAcrossTitles,
  filterOutHidden,
} from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { invalidateTableCache } from './table-ui.js';
import {
  refreshFilterUI,
  renderSummary,
  renderGenreChips,
  renderStoreChips,
  renderWishlistStoreChips,
  switchView,
  updateWishlistDrawerVisibility,
} from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
import { consumeItadAutoRunFlag, diffItadDeals } from './fetcher-health.js';
import { fireLibraryCountFlash } from './library-count-animation.js';

export const ITAD_SNAPSHOT_KEY = "baklog-itad-snapshot";

// Module-scoped previous counts so we only animate real fetch-driven jumps.
// Null sentinels mean "first paint" — no popups on cold start.
let _prevLibraryCount = null;
let _prevWishlistCount = null;

export async function loadItadPrices() {
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

export function showItadAlertBanner({ newSales, newHistoricalLows }) {
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

export async function loadCacheMeta(url, metaKey) {
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

export async function loadHltbCache() {
  await loadCacheMeta("cache/hltb_map.json", "hltb");
}

export async function loadSteamReviewCache() {
  await loadCacheMeta("cache/steam_review_map.json", "steamReviews");
}

export async function loadSteamCoversMeta() {
  await loadCacheMeta("cache/cross_store_images_meta.json", "steamCovers");
}

export async function loadSteamTagsMeta() {
  await loadCacheMeta("cache/steam_tags_meta.json", "steamTags");
}

function countLibraryVisible() {
  return filterOutHidden(
    state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))),
  ).length;
}
function countWishlistVisible() {
  return state.wishlistGames.filter(g => !state.wishlistCrossStoreHiddenKeys.has(gameKey(g))).length;
}

export async function applyMergedLibrary() {
  window._dataVersion = (window._dataVersion || 0) + 1;
  bumpPersonalMemo();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  canonicalizeNotesAcrossTitles();
  state.dashboardDataReady = true;
  buildOwnedNormNames();
  const banner = document.getElementById("bootErrorBanner");
  if (banner) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
  }

  const libNow = countLibraryVisible();
  const wlNow = countWishlistVisible();
  const libPrev = _prevLibraryCount;
  const wlPrev = _prevWishlistCount;
  _prevLibraryCount = libNow;
  _prevWishlistCount = wlNow;

  renderStoreChips();
  renderWishlistStoreChips();
  renderGenreChips();
  renderSummary();
  if (state.activeView === "dashboard") scheduleDashboardRender();
  else {
    renderPicks();
    await refreshFilterUI({ force: true });
    if (state.activeView === "wishlist") {
      // dashboardDataReady just flipped true — re-evaluate the radar gate.
      updateWishlistDrawerVisibility();
    }
  }

  try {
    if (libPrev != null && libNow > libPrev) {
      fireLibraryCountFlash('library', libPrev, libNow);
    }
    if (wlPrev != null && wlNow > wlPrev) {
      fireLibraryCountFlash('wishlist', wlPrev, wlNow);
    }
  } catch (err) {
    console.warn('[library-count-anim]', err);
  }
}

export async function fetchLibraryJson(path) {
  const res = await fetch(`${path}?t=${Date.now()}`);
  if (!res.ok) return null;
  return res.json();
}

export const LIBRARY_STORE_JSON = {
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
  wishlistPsn: "games_wishlist_psn.json",
  wishlistUbisoft: "games_wishlist_ubisoft.json",
  wishlistXbox: "games_wishlist_xbox.json",
};
const WISHLIST_FETCHER_META_KEY = {
  wishlistSteam: "wishlist",
  wishlistGog: "wishlistGog",
  wishlistEpic: "wishlistEpic",
  wishlistPsn: "wishlistPsn",
  wishlistUbisoft: "wishlistUbisoft",
  wishlistXbox: "wishlistXbox",
};
const ENRICH_FETCHER_KEYS = new Set(["hltb", "steamReviews", "steamCovers", "steamTags"]);

export function rebuildAllGamesFromMetas() {
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
  state.allGames = sources.flatMap(dedupeWithinStore).map(applyCoopOverrides);
  state.itchGames = dedupeWithinStore(
    (itch?.games || []).map(g => normalizeGame({ ...g, store: "itch", id: g.id ?? g.itch_id })),
  ).map(applyCoopOverrides);
}

export function rebuildWishlistFromMetas() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const { wishlist, wishlistGog, wishlistEpic, wishlistPsn, wishlistUbisoft, wishlistXbox } = state.libraryMeta;
  const fetchedWishlist = [
    ...((wishlist?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? g.appid }))),
    ...((wishlistGog?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: `gog-${g.id ?? g.gog_id}`, wishlist_store: "gog" }))),
    ...((wishlistEpic?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `epic-${g.epic_namespace}:${g.epic_offer_id}`, wishlist_store: "epic" }))),
    ...((wishlistPsn?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `psn-${g.psn_product_id}`, wishlist_store: "psn" }))),
    ...((wishlistUbisoft?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `ubisoft-${g.ubisoft_product_id}`, wishlist_store: "ubisoft" }))),
    ...((wishlistXbox?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `xbox-${g.xbox_product_id}`, wishlist_store: "xbox" }))),
  ];
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
}

export async function reloadAllLibraryStoreFiles() {
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

export async function reloadAfterFetcher(key) {
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
    if (key === "steamTags") await loadSteamTagsMeta();
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
  await applyMergedLibrary();
}

export async function reloadGames() {
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
  const wishlistPsn = await fetchLibraryJson("games_wishlist_psn.json");
  const wishlistUbisoft = await fetchLibraryJson("games_wishlist_ubisoft.json");
  const wishlistXbox = await fetchLibraryJson("games_wishlist_xbox.json");
  state.libraryMeta.wishlist = wishlist;
  state.libraryMeta.wishlistGog = wishlistGog;
  state.libraryMeta.wishlistEpic = wishlistEpic;
  state.libraryMeta.wishlistPsn = wishlistPsn;
  state.libraryMeta.wishlistUbisoft = wishlistUbisoft;
  state.libraryMeta.wishlistXbox = wishlistXbox;
  rebuildWishlistFromMetas();
  await loadItadPrices();
  await loadHltbCache();
  await loadSteamReviewCache();
  await loadSteamCoversMeta();
  await loadSteamTagsMeta();
  await applyMergedLibrary();
}

export function refreshAfterManualChange() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualLibrary = allManual.filter(g => !g.wishlist);
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const nonManualLibrary = state.allGames.filter(g => !g.manual);
  state.allGames = [...nonManualLibrary, ...dedupeWithinStore(manualLibrary).map(applyCoopOverrides)];
  const fetchedWishlist = state.wishlistGames.filter(g => !g.manual);
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
  void applyMergedLibrary();
}
