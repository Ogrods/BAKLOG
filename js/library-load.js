import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import {
  normalizeGame,
  dedupeWithinStore,
  recomputeCrossStoreHidden,
  applyCoopOverrides,
  gameKey,
  rebuildGameKeyIndex,
} from './game-core.js';
import { personalStore } from './personal-store.js';
import {
  LIBRARY_STORE_JSON,
  WISHLIST_FETCHER_JSON,
  WISHLIST_FETCHER_META_KEY,
  ENRICH_FETCHER_KEYS,
  ENRICH_RELOAD_WISHLIST_KEYS,
} from './fetcher-registry.js';
import { noteFetcherReload, noteLibraryMerge } from './propagation-trace.js';
import {
  applyItadPriceSnapshot,
  slimItadSnapshot,
  buildOwnedNormNames,
} from './deals.js';
import {
  loadManualGames,
  saveLibraryFirstSeen,
  bumpPersonalMemo,
  canonicalizeNotesAcrossTitles,
  applyHiddenTitleNorms,
  filterOutHidden,
  filterCounted,
  libraryGamesBase,
} from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { isDebugEnabled } from './debug-overlay.js';
import { invalidateTableCache } from './table-ui.js';
import {
  refreshFilterUI,
  renderSummary,
  renderGenreChips,
  renderStoreChips,
  renderWishlistStoreChips,
  switchView,
  updateWishlistDrawerVisibility,
  applyItchTabVisibility,
} from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
import { consumeItadAutoRunFlag, diffItadDeals, maybeAutoEnrichNewAdditions } from './fetcher-health.js';
import {
  loadClaimableNow,
  consumeClaimsAutoRunFlag,
  diffClaims,
  loadClaimsSnapshotKeys,
  showClaimableBanner,
  saveClaimsSnapshot,
  refreshClaimableUi,
} from './claimable.js';
import { loadSponsoredDeals } from './sponsored-deals.js';
import { fireLibraryCountFlash } from './library-count-animation.js';
import { itadSnapshotStorageKey } from './profiles.js';
import { dataFetch } from './api-client.js';
import {
  deferPicksRender,
  deferSummaryRender,
  deferTableRender,
} from './render-gate.js';

async function refreshLibraryChromeAfterMerge() {
  if (state.activeView === 'dashboard') {
    scheduleDashboardRender();
    return;
  }
  if (state.activeView === 'connections') {
    deferPicksRender();
    deferSummaryRender();
    deferTableRender();
    return;
  }
  // refreshFilterUI paints summary + picks + table — avoid duplicate chrome paints.
  await refreshFilterUI({ force: true });
  if (state.activeView === 'wishlist') {
    updateWishlistDrawerVisibility();
    refreshClaimableUi();
  }
}

// Module-scoped previous counts so we only animate real fetch-driven jumps.
// Null sentinels mean "first paint" — no popups on cold start, just the
// initial roll handled inside applyMegaHeroCounters.
let _prevLibraryCount = null;
let _prevWishlistCount = null;

export async function loadItadPrices() {
  let prevByKey = {};
  try {
    const raw = localStorage.getItem(itadSnapshotStorageKey());
    if (raw) prevByKey = JSON.parse(raw)?.by_key || {};
  } catch (_) {}
  try {
    const data = await fetchLibraryJson("itad_prices.json");
    state.libraryMeta.itad = data || null;
    const nextByKey = data?.by_key || {};
    applyItadPriceSnapshot(prevByKey, nextByKey);
    state.itadByKey = nextByKey;
    try {
      localStorage.setItem(itadSnapshotStorageKey(), JSON.stringify({
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
      <span><strong>Prices refreshed</strong> - ${escapeHtml(parts.join(" · "))}.
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
    const res = await dataFetch(`${url}?t=${Date.now()}`);
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

export async function loadProtondbCache() {
  await loadCacheMeta("cache/protondb_map.json", "protondb");
}

/** Stamp first-seen timestamps for library keys (silent seed on first load).
 *  Returns count of keys newly stamped with a real timestamp (0 on first seed). */
export function recordLibraryFirstSeen() {
  if (!state.libraryFirstSeenByKey || typeof state.libraryFirstSeenByKey !== 'object') {
    state.libraryFirstSeenByKey = {};
  }
  const mapWasEmpty = Object.keys(state.libraryFirstSeenByKey).length === 0;
  const seeded = !!state.prefs.librarySeenSeeded;
  // If the persisted map is empty but seeding already happened, the first-seen
  // data was lost upstream (server doc reset, or the migration path skipped
  // applyServerDoc, leaving the in-memory map empty while the prefs flag stayed
  // true). Re-seed as baseline rather than flooding "Recently added" with the
  // entire library stamped at the current time.
  const effectiveSeeded = seeded && !mapWasEmpty;
  let changed = false;
  let newlyStamped = 0;
  const debugNewKeys = isDebugEnabled() && effectiveSeeded ? [] : null;
  // itch games live in state.itchGames (their own tab), not state.allGames.
  // Stamp them too so itch additions get a first-seen timestamp and can
  // surface in recents / the +N added flash instead of vanishing silently.
  const itchGames = Array.isArray(state.itchGames) ? state.itchGames : [];
  for (const g of [...state.allGames, ...itchGames]) {
    const key = gameKey(g);
    if (key in state.libraryFirstSeenByKey) continue;
    state.libraryFirstSeenByKey[key] = effectiveSeeded ? Date.now() : 0;
    changed = true;
    if (effectiveSeeded) {
      newlyStamped += 1;
      debugNewKeys?.push(key);
    }
  }
  if (isDebugEnabled()) {
    console.debug('[baklog-recents] recordLibraryFirstSeen', {
      mapWasEmpty,
      seeded,
      effectiveSeeded,
      totalKeys: Object.keys(state.libraryFirstSeenByKey).length,
      newlyStamped,
      newlyStampedKeys: debugNewKeys ?? [],
    });
  }
  if (!state.prefs.librarySeenSeeded) {
    state.prefs.librarySeenSeeded = true;
    changed = true;
  }
  if (changed) {
    saveLibraryFirstSeen(state.libraryFirstSeenByKey);
    personalStore.notify();
  }
  return effectiveSeeded ? newlyStamped : 0;
}

function countLibraryVisible() {
  return filterCounted(libraryGamesBase()).length;
}
function countWishlistVisible() {
  return state.wishlistGames.filter(g => !state.wishlistCrossStoreHiddenKeys.has(gameKey(g))).length;
}

/** When reloadGames fails (no JSON files), still mark data ready and paint empty UI. */
export async function finishEmptyLibraryLoad() {
  if (state.dashboardDataReady) return;
  window._dataVersion = (window._dataVersion || 0) + 1;
  invalidateTableCache();
  recomputeCrossStoreHidden();
  rebuildGameKeyIndex();
  state.dashboardDataReady = true;
  buildOwnedNormNames();
  _prevLibraryCount = countLibraryVisible();
  _prevWishlistCount = countWishlistVisible();
  renderStoreChips();
  renderWishlistStoreChips();
  renderGenreChips();
  await refreshLibraryChromeAfterMerge();
}

export async function applyMergedLibrary(mergeKey = null) {
  noteLibraryMerge(mergeKey);
  window._dataVersion = (window._dataVersion || 0) + 1;
  bumpPersonalMemo();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  // Refresh the gameKey lookup before any findGameByKey consumers run — the
  // length-based fingerprint can't see same-size content swaps after a merge.
  rebuildGameKeyIndex();
  state._lastNewlyAddedCount = recordLibraryFirstSeen();
  canonicalizeNotesAcrossTitles();
  applyHiddenTitleNorms({ silent: true });
  state.dashboardDataReady = true;
  buildOwnedNormNames();
  const banner = document.getElementById("bootErrorBanner");
  if (banner) {
    banner.classList.add("hidden");
    banner.innerHTML = "";
  }

  // Diff before render so the UI repaints AND we know what delta to flash.
  const libNow = countLibraryVisible();
  const wlNow = countWishlistVisible();
  const libPrev = _prevLibraryCount;
  const wlPrev = _prevWishlistCount;
  _prevLibraryCount = libNow;
  _prevWishlistCount = wlNow;

  renderStoreChips();
  renderWishlistStoreChips();
  renderGenreChips();
  await refreshLibraryChromeAfterMerge();

  // Fire after the render so popup hosts exist in the DOM. Wrapped in
  // try/catch — this is pure polish; never let it break a real merge.
  // Gate the library burst on genuinely-new keys (recordLibraryFirstSeen),
  // not the raw visible-count delta: un-hiding a game, a cross-store dedup
  // change, or a wishlist->library move all bump libNow by 1 without adding a
  // real acquisition, which would flash a celebratory +1 that never shows up
  // in "Recently added".
  try {
    const newlyAdded = state._lastNewlyAddedCount ?? 0;
    if (libPrev != null && libNow > libPrev && newlyAdded > 0) {
      fireLibraryCountFlash('library', libPrev, libNow);
    }
    if (wlPrev != null && wlNow > wlPrev) {
      fireLibraryCountFlash('wishlist', wlPrev, wlNow);
    }
  } catch (err) {
    console.warn('[library-count-anim]', err);
  }

  applyItchTabVisibility();
}

export async function fetchLibraryJson(path) {
  const res = await dataFetch(`${path}?t=${Date.now()}`);
  if (!res.ok) return null;
  return res.json();
}

export { LIBRARY_STORE_JSON };

export function rebuildAllGamesFromMetas() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const nonWishlistManual = allManual.filter(g => !g.wishlist);
  const manualItch = nonWishlistManual.filter(g => g.store === "itch");
  const manualLibrary = nonWishlistManual.filter(g => g.store !== "itch");
  const { steam: steamData, gog, psn, epic, amazon, nintendo, xbox, battlenet, ubisoft, itch, humble, ea } = state.libraryMeta;
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
    (humble?.games || []).map(g => normalizeGame({ ...g, store: "humble", id: g.id ?? `humble-${g.humble_id}` })),
    (ea?.games || []).map(g => normalizeGame({ ...g, store: "ea", id: g.id ?? g.ea_id })),
    manualLibrary,
  ];
  state.allGames = sources.flatMap(dedupeWithinStore).map(applyCoopOverrides);
  state.itchGames = dedupeWithinStore([
    ...(itch?.games || []).map(g => normalizeGame({ ...g, store: "itch", id: g.id ?? g.itch_id })),
    ...manualItch,
  ]).map(applyCoopOverrides);
}

export function rebuildWishlistFromMetas() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const { wishlist, wishlistGog, wishlistEpic, wishlistPsn, wishlistUbisoft, wishlistXbox, wishlistNintendo, wishlistHumble } = state.libraryMeta;
  const fetchedWishlist = [
    ...((wishlist?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? g.appid }))),
    ...((wishlistGog?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: `gog-${g.id ?? g.gog_id}`, wishlist_store: "gog" }))),
    ...((wishlistEpic?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `epic-${g.epic_namespace}:${g.epic_offer_id}`, wishlist_store: "epic" }))),
    ...((wishlistPsn?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `psn-${g.psn_product_id}`, wishlist_store: "psn" }))),
    ...((wishlistUbisoft?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `ubisoft-${g.ubisoft_product_id}`, wishlist_store: "ubisoft" }))),
    ...((wishlistXbox?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `xbox-${g.xbox_product_id}`, wishlist_store: "xbox" }))),
    ...((wishlistNintendo?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `nintendo-${g.nintendo_product_id}`, wishlist_store: "nintendo" }))),
    ...((wishlistHumble?.games || []).map(g => normalizeGame({ ...g, store: "wishlist", id: g.id ?? `humble-${g.humble_product_id}`, wishlist_store: "humble" }))),
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

export async function reloadAllWishlistStoreFiles() {
  const entries = await Promise.all(
    Object.entries(WISHLIST_FETCHER_JSON).map(async ([fetcherKey, file]) => {
      const metaKey = WISHLIST_FETCHER_META_KEY[fetcherKey];
      try {
        return [metaKey, await fetchLibraryJson(file)];
      } catch {
        return [metaKey, state.libraryMeta[metaKey] ?? null];
      }
    }),
  );
  for (const [metaKey, data] of entries) state.libraryMeta[metaKey] = data;
  rebuildWishlistFromMetas();
}

export async function reloadAfterFetcher(key) {
  noteFetcherReload(key);
  if (key === "itad") {
    const prevByKey = { ...state.itadByKey };
    const wasAuto = consumeItadAutoRunFlag();
    await loadItadPrices();
    await reloadAllWishlistStoreFiles();
    if (wasAuto) {
      const diff = diffItadDeals(prevByKey, state.itadByKey);
      if (diff.newSales > 0 || diff.newHistoricalLows > 0) {
        showItadAlertBanner(diff);
      }
    }
  } else if (ENRICH_FETCHER_KEYS.has(key)) {
    await reloadAllLibraryStoreFiles();
    if (ENRICH_RELOAD_WISHLIST_KEYS.has(key)) {
      await reloadAllWishlistStoreFiles();
    }
    if (key === "hltb") await loadHltbCache();
    if (key === "steamReviews") await loadSteamReviewCache();
    if (key === "steamCovers") await loadSteamCoversMeta();
    if (key === "steamTags") await loadSteamTagsMeta();
    if (key === "protondb") await loadProtondbCache();
  } else if (key === 'claims') {
    const wasAuto = consumeClaimsAutoRunFlag();
    const prevKeys = loadClaimsSnapshotKeys();
    await loadClaimableNow();
    const { newCount } = diffClaims(prevKeys, state.claimableFeed?.items || []);
    if (wasAuto && newCount > 0) showClaimableBanner(newCount);
    saveClaimsSnapshot(state.claimableFeed?.items || []);
    refreshClaimableUi();
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
  await applyMergedLibrary(key);
  const newCount = state._lastNewlyAddedCount ?? 0;
  if (LIBRARY_STORE_JSON[key] && !ENRICH_FETCHER_KEYS.has(key)) {
    void maybeAutoEnrichNewAdditions(newCount);
  }
  if (key === 'steam') {
    void import('./library-watch.js').then(m => m.onSteamCatalogReloaded());
  }
}

export async function reloadGames() {
  const [
    steam,
    gog,
    psn,
    epic,
    amazon,
    nintendo,
    itch,
    xbox,
    battlenet,
    ubisoft,
    humble,
    ea,
    wishlist,
    wishlistGog,
    wishlistEpic,
    wishlistPsn,
    wishlistUbisoft,
    wishlistXbox,
    wishlistNintendo,
    wishlistHumble,
  ] = await Promise.all([
    fetchLibraryJson("games_steam.json"),
    fetchLibraryJson("games_gog.json"),
    fetchLibraryJson("games_psn.json"),
    fetchLibraryJson("games_epic.json"),
    fetchLibraryJson("games_amazon.json"),
    fetchLibraryJson("games_nintendo.json"),
    fetchLibraryJson("games_itch.json"),
    fetchLibraryJson("games_xbox.json"),
    fetchLibraryJson("games_battlenet.json"),
    fetchLibraryJson("games_ubisoft.json"),
    fetchLibraryJson("games_humble.json"),
    fetchLibraryJson("games_ea.json"),
    fetchLibraryJson("games_wishlist.json"),
    fetchLibraryJson("games_wishlist_gog.json"),
    fetchLibraryJson("games_wishlist_epic.json"),
    fetchLibraryJson("games_wishlist_psn.json"),
    fetchLibraryJson("games_wishlist_ubisoft.json"),
    fetchLibraryJson("games_wishlist_xbox.json"),
    fetchLibraryJson("games_wishlist_nintendo.json"),
    fetchLibraryJson("games_wishlist_humble.json"),
  ]);
  if (!steam && !gog && !psn && !epic && !amazon && !nintendo && !itch && !xbox && !battlenet && !ubisoft && !humble && !ea) throw new Error("No library files found");
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
  state.libraryMeta.humble = humble;
  state.libraryMeta.ea = ea;
  rebuildAllGamesFromMetas();
  state.libraryMeta.wishlist = wishlist;
  state.libraryMeta.wishlistGog = wishlistGog;
  state.libraryMeta.wishlistEpic = wishlistEpic;
  state.libraryMeta.wishlistPsn = wishlistPsn;
  state.libraryMeta.wishlistUbisoft = wishlistUbisoft;
  state.libraryMeta.wishlistXbox = wishlistXbox;
  state.libraryMeta.wishlistNintendo = wishlistNintendo;
  state.libraryMeta.wishlistHumble = wishlistHumble;
  rebuildWishlistFromMetas();
  await Promise.all([
    loadItadPrices(),
    loadSponsoredDeals(),
    loadHltbCache(),
    loadSteamReviewCache(),
    loadSteamCoversMeta(),
    loadSteamTagsMeta(),
    loadProtondbCache(),
  ]);
  await applyMergedLibrary();
  // Load claimables after buildOwnedNormNames() so owned-library games are
  // filtered on the first paint, not briefly shown until merge completes.
  await loadClaimableNow();
  saveClaimsSnapshot(state.claimableFeed?.items || []);
  if (state.activeView === 'wishlist') refreshClaimableUi();
  void import('./library-watch.js').then(m => m.onSteamCatalogReloaded());
}

export function refreshAfterManualChange() {
  const allManual = loadManualGames().map(g => normalizeGame(g));
  const manualWishlist = allManual.filter(g => !!g.wishlist);
  const nonWishlistManual = allManual.filter(g => !g.wishlist);
  // Manual entries added under the itch.io platform belong in the itch tab
  // (state.itchGames), matching where fetched store === "itch" rows live.
  // Without this they leak into the Library catalog and never show on the itch tab.
  const manualItch = nonWishlistManual.filter(g => g.store === "itch");
  const manualLibrary = nonWishlistManual.filter(g => g.store !== "itch");
  const nonManualLibrary = state.allGames.filter(g => !g.manual);
  state.allGames = [...nonManualLibrary, ...dedupeWithinStore(manualLibrary).map(applyCoopOverrides)];
  const fetchedWishlist = state.wishlistGames.filter(g => !g.manual);
  state.wishlistGames = [...fetchedWishlist, ...manualWishlist];
  const fetchedItch = state.itchGames.filter(g => !g.manual);
  state.itchGames = [...fetchedItch, ...dedupeWithinStore(manualItch).map(applyCoopOverrides)];
  void applyMergedLibrary();
}
