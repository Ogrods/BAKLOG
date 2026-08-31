/** Fetcher source metadata, coverage helpers, manifest loading. */
import { baklogFetch } from '../api-client.js';
import { state, ITCH_NON_GAME_CLASSIFICATIONS } from '../state.js';
import { formatNum } from '../dom-util.js';
import { fetcherSources, setFetcherSources } from '../fetcher-health-shared.js';

export const ENRICH_KEYS = new Set(['hltb', 'steamReviews', 'steamCovers', 'steamTags', 'protondb']);
/** Cache JSON loaded after library files in reloadGames — avoid "missing" flash during boot. */
export const BOOT_DEFERRED_FETCHER_KEYS = new Set([...ENRICH_KEYS, 'itad', 'claims']);
export const MAX_SSE_HINT = 'max 8 live streams';
export const GROUP_ORDER = ['library', 'wishlist', 'prices', 'enrich'];
export const GROUP_LABELS = {
  library: 'Library',
  wishlist: 'Wishlist',
  prices: 'Prices',
  enrich: 'Enrichment',
};
export const GROUP_LABEL_TIPS = {
  library: 'Library/store sources',
  wishlist: 'Wishlist sources',
  prices: 'Price sources',
  enrich: 'Enrichment sources',
};
export const COUNT_PILL_TITLES = {
  stale: 'Fetchers whose cached data is past its freshness window - re-run to refresh',
  missing: 'Data sources never fetched yet (no local cache) - click the chip to run them',
  fresh: "Every fetcher's cache is up to date",
};
// Fixed order within the Enrichment group: keep the three Steam-derived
// enrichers (orange edge) adjacent, then HLTB. Overrides the status/label
// sort so they always render next to each other.
export const ENRICH_ORDER = ['steamReviews', 'steamTags', 'steamCovers', 'protondb', 'hltb'];

export const COUNT_FNS = {
  itad: m => Object.keys(m?.by_key || {}).length,
  claims: m => (m?.items || []).length,
  hltb: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
  steamReviews: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
  steamCovers: m => (m?.last_updated != null ? m.last_updated : null),
  steamTags: m => (m?.rows_updated != null ? m.rows_updated : null),
  protondb: m => Object.keys(m || {}).filter(k => k !== 'fetched_at').length,
};

// Plain-English description of what a normal click does for each fetcher.
// Falls back to a generic per-group hint if a key isn't listed here.
const CLICK_HINTS = {
  steam: 'Sync your Steam library - picks up new purchases & updated playtime',
  gog: 'Sync your GOG library - picks up new purchases & metadata',
  psn: 'Sync your PlayStation library',
  epic: 'Sync your Epic library',
  amazon: 'Sync your Amazon Prime Gaming library',
  xbox: 'Sync your Xbox library',
  battlenet: 'Sync your Battle.net library',
  ubisoft: 'Sync your Ubisoft Connect library',
  nintendo: 'Sync your Nintendo Switch library',
  humble: 'Sync your Humble Bundle library (games only)',
  ea: 'Sync your EA App library (PC titles)',
  itch: 'Sync your itch.io library',
  wishlistSteam: 'Sync your Steam wishlist',
  wishlistGog: 'Sync your GOG wishlist',
  wishlistEpic: 'Sync your Epic wishlist',
  wishlistPsn: 'Sync your PlayStation Store wishlist',
  wishlistUbisoft: 'Sync your Ubisoft Store wishlist',
  wishlistXbox: 'Sync your Xbox Store wishlist',
  wishlistNintendo: 'Sync your Nintendo Store wishlist',
  wishlistHumble: 'Sync your Humble Store wishlist',
  itad: 'Refresh wishlist price quotes from IsThereAnyDeal',
  claims: 'Download free claimable games (aggregated via Epic, GamerPower, IsThereAnyDeal)',
  hltb: "Look up HowLongToBeat hours for games we haven't checked yet",
  steamReviews: 'Pull missing Steam review scores for non-Steam games',
  steamCovers: 'Generate covers for non-Steam games missing artwork',
  steamTags: 'Backfill co-op tags + missing genres on non-Steam games using Steam category data',
  protondb: 'Pull ProtonDB Linux / Steam Deck compatibility tiers for Steam-matched games',
};

// What Shift+click (--refresh) actually changes, per fetcher.
const REFRESH_HINTS = {
  steam: 'Re-fetch every game from Steam, ignoring local cache (slower, full rebuild)',
  gog: 'Re-fetch every game from GOG, ignoring local cache (slower, full rebuild)',
  psn: 'Re-fetch every PlayStation entry, ignoring local cache',
  epic: 'Re-fetch every Epic entry, ignoring local cache',
  wishlistGog: 'Re-fetch every wishlist entry from GOG, ignoring cached details',
  hltb: 'Also retry titles previously cached as "no HLTB match" - use after an API outage or client bump',
  steamReviews:
    'Also retry titles previously cached as "no Steam app match" - use after Steam lists the game',
  steamCovers: 'Also retry rows previously cached as "no Steam match" - use after Steam adds new entries',
  steamTags: 'Re-fetch Steam appdetails ignoring the local cache - picks up newly-added Steam categories',
  protondb:
    'Also retry appids previously cached as "no reports" and re-fetch rows that already have a tier',
};

// Pending breakdown for the enrichment chips so the tooltip can say
// "nothing to look up" vs "X new lookups pending" — turns a misleading
// 76% data-coverage number into clear messaging about what a click will
// actually do.
//
// Three states per missing row:
//   unchecked → never tried by the fetcher; click will produce fresh work.
//   retry    → tried before, the upstream returned nothing useful, but the
//              fetcher will keep retrying. Click does work, but probably
//              won't change the numbers much.
//   noMatch  → cached as "no match" so the fetcher skips on a normal click.
//              Only Shift+click (HLTB) can revisit.
export function pendingForEnrich(key) {
  if (key === 'hltb') {
    const cache = state.libraryMeta.hltb || {};
    const rows = allLibraryRows();
    let unchecked = 0;
    let retry = 0;
    let noMatch = 0;
    for (const g of rows) {
      if (g.hltb_main_hours != null) continue;
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      if (v === false) noMatch++;
      else unchecked++;
    }
    return { unchecked, retry, noMatch };
  }
  if (key === 'steamReviews') {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = reviewableRows();
    let unchecked = 0;
    let retry = 0;
    let noMatch = 0;
    for (const g of rows) {
      if (g.steam_review_percent != null) continue;
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      if (v === 0) noMatch++;
      else if (v == null) unchecked++;
      else retry++;
    }
    return { unchecked, retry, noMatch };
  }
  if (key === 'steamCovers') {
    const meta = state.libraryMeta.steamCovers || {};
    const skipped = new Set(meta.no_steam_match || []);
    const rows = coverableRows();
    let unchecked = 0;
    let noMatch = 0;
    for (const g of rows) {
      const lib = g.library_image || '';
      const hdr = g.header_image || '';
      const ok = (lib || hdr) && !String(lib).endsWith('.eprt') && !String(hdr).endsWith('.eprt');
      if (ok) continue;
      if (skipped.has(`${g.store || 'steam'}:${g.id}`)) noMatch++;
      else unchecked++;
    }
    return { unchecked, retry: 0, noMatch };
  }
  if (key === 'steamTags') {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = nonSteamRows();
    let unchecked = 0;
    let noMatch = 0;
    for (const g of rows) {
      const v = cache[`${g.store || 'steam'}:${g.id}`];
      // No appid match → nothing this enricher can do.
      if (!v) {
        noMatch++;
        continue;
      }
      // coop_online/coop_local is the canonical "have we run this" signal.
      if (g.coop_online === undefined && g.coop_local === undefined) unchecked++;
    }
    return { unchecked, retry: 0, noMatch };
  }
  if (key === 'protondb') {
    const reviewCache = state.libraryMeta.steamReviews || {};
    const protonCache = state.libraryMeta.protondb || {};
    const rows = protondbEligibleRows();
    let unchecked = 0;
    let noMatch = 0;
    for (const g of rows) {
      if (g.protondb_tier != null) continue;
      const appid = protonAppIdForRow(g, reviewCache);
      if (!appid) {
        noMatch++;
        continue;
      }
      if (protonCache[String(appid)] === false) noMatch++;
      else unchecked++;
    }
    return { unchecked, retry: 0, noMatch };
  }
  return null;
}

export function clickHintFor(src) {
  const base = CLICK_HINTS[src.key] || `Run ${src.label} fetcher`;
  const pending = pendingForEnrich(src.key);
  if (!pending) return base;
  if (pending.unchecked > 0) {
    return `${base} (${formatNum(pending.unchecked)} pending)`;
  }
  if (pending.retry > 0) {
    return `Re-tries ${formatNum(pending.retry)} previously-attempted rows that didn't return data. Usually won't change the score - safe to skip.`;
  }
  if (pending.noMatch > 0) {
    const note = src.supportsRefresh
      ? ' Use Shift+click to retry them.'
      : '';
    return `Nothing new to look up - the remaining ${formatNum(pending.noMatch)} are cached as "no match".${note}`;
  }
  return 'Everything is enriched - nothing to do.';
}

export function refreshHintFor(src) {
  if (!src.supportsRefresh) return null;
  const base = REFRESH_HINTS[src.key] || 'Re-fetch ignoring local cache (slower, full rebuild)';
  if (src.key === 'hltb' || src.key === 'steamReviews') {
    const pending = pendingForEnrich(src.key);
    if (pending?.noMatch > 0) {
      return `${base} (~${formatNum(pending.noMatch)} cached misses would be retried)`;
    }
  }
  return base;
}

function itchIsGame(g) {
  const c = g.classification;
  if (!c || c === 'game') return true;
  return !ITCH_NON_GAME_CLASSIFICATIONS.has(c);
}

function allLibraryRows() {
  const itchGames = (state.itchGames || []).filter(itchIsGame);
  return [...(state.allGames || []), ...itchGames];
}

function nonSteamRows() {
  return (state.allGames || []).filter(g => (g.store || 'steam') !== 'steam');
}

function reviewableRows() {
  return [...nonSteamRows(), ...(state.itchGames || []).filter(itchIsGame)];
}

function protonAppIdForRow(g, reviewCache) {
  const store = g.store || 'steam';
  if (store === 'steam') return g.id;
  const v = reviewCache[`${store}:${g.id}`];
  return v || null;
}

function protondbEligibleRows() {
  const reviewCache = state.libraryMeta.steamReviews || {};
  return allLibraryRows().filter(g => protonAppIdForRow(g, reviewCache));
}

export function coverableRows() {
  const itch = (state.itchGames || []).filter(itchIsGame);
  return [...nonSteamRows(), ...(state.wishlistGames || []), ...itch];
}

function coverageOf(rows, pred) {
  const total = rows.length;
  if (!total) return { covered: 0, total: 0, pct: null };
  const covered = rows.filter(pred).length;
  const pct = covered >= total ? 100 : Math.floor((covered / total) * 100);
  return { covered, total, pct };
}

const COVERAGE_FNS = {
  hltb: () => coverageOf(allLibraryRows(), g => g.hltb_main_hours != null),
  steamReviews: () => coverageOf(reviewableRows(), g => g.steam_review_percent != null),
  steamCovers: () => coverageOf(
    coverableRows(),
    g => {
      const lib = g.library_image || '';
      const hdr = g.header_image || '';
      if (!lib && !hdr) return false;
      return !String(lib).endsWith('.eprt') && !String(hdr).endsWith('.eprt');
    },
  ),
  // Universe = non-Steam rows where we have a Steam appid match. Covered =
  // rows the enricher has touched (coop fields are the canonical signal).
  steamTags: () => {
    const cache = state.libraryMeta.steamReviews || {};
    const rows = nonSteamRows().filter(
      g => cache[`${g.store || 'steam'}:${g.id}`],
    );
    return coverageOf(
      rows,
      g => g.coop_online !== undefined || g.coop_local !== undefined,
    );
  },
  protondb: () => coverageOf(
    protondbEligibleRows(),
    g => g.protondb_tier != null,
  ),
};

export function coverageLabel(key) {
  const fn = COVERAGE_FNS[key];
  if (!fn) return null;
  const { total, pct } = fn();
  if (!total) return ' - ';
  let label = `${pct != null ? pct : 0}%`;
  const pending = pendingForEnrich(key);
  if (pending && pending.unchecked > 0) label += ` · ${formatNum(pending.unchecked)} new`;
  return label;
}

export function coverageTooltipLine(key) {
  const fn = COVERAGE_FNS[key];
  if (!fn) return null;
  const { covered, total } = fn();
  if (!total) return null;
  const pending = pendingForEnrich(key);
  const verb = key === 'hltb'
    ? 'have HowLongToBeat hours'
    : key === 'steamReviews'
      ? 'have Steam review scores'
      : key === 'steamTags'
        ? 'have Steam-derived co-op tags'
        : key === 'protondb'
          ? 'have ProtonDB compatibility tiers'
          : 'have artwork';
  let line = `${formatNum(covered)} of ${formatNum(total)} ${verb}.`;
  if (!pending) return line;
  if (pending.unchecked > 0) {
    line += ` ${formatNum(pending.unchecked)} still to try.`;
  } else if (pending.retry > 0 && key === 'steamReviews') {
    line += ` ${formatNum(pending.retry)} were tried before with no review score - clicking will re-check but rarely changes the number.`;
  } else if (pending.noMatch > 0) {
    const src = key === 'hltb' ? 'HowLongToBeat' : 'Steam';
    line += ` Remaining ${formatNum(pending.noMatch)} have no match on ${src} - clicking won't add more.`;
  } else {
    line += ' Nothing pending.';
  }
  return line;
}

export let reloadGamesFn = async () => {};
export let reloadAfterFetcherFn = null;
export const batchRunCooldowns = { staleUntil: 0, failedUntil: 0 };


export function configureFetcherHealth({ reloadGames, reloadAfterFetcher }) {
  reloadGamesFn = reloadGames;
  reloadAfterFetcherFn = reloadAfterFetcher || null;
}

async function manifestRefreshKeys() {
  try {
    const res = await fetch('fetchers/manifest.json');
    if (!res.ok) return {};
    const data = await res.json();
    const keys = {};
    for (const entry of data.fetchers || []) {
      if ((entry.refreshArgs || []).length) keys[entry.key] = true;
    }
    return keys;
  } catch (_) {
    return {};
  }
}

export async function loadFetcherSources(force = false) {
  const refreshByKey = await manifestRefreshKeys();
  try {
    const res = await baklogFetch('/api/fetchers');
    if (res.ok) {
      const data = await res.json();
      setFetcherSources((data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: entry.cmd ? `python ${entry.cmd}` : '',
        countFn: COUNT_FNS[entry.key] || null,
        requires: entry.requires || [],
        missingRequirements: entry.missing_requirements || [],
        supportsRefresh: !!(entry.supports_refresh || refreshByKey[entry.key]),
        available: entry.available !== false,
        platforms: entry.platforms || [],
      })));
      return fetcherSources;
    }
  } catch (_) {}
  if (fetcherSources.length && !force) return fetcherSources;
  try {
    const res = await fetch('fetchers/manifest.json');
    if (res.ok) {
      const data = await res.json();
      setFetcherSources((data.fetchers || []).map(entry => ({
        key: entry.key,
        label: entry.label,
        group: entry.group || 'library',
        color: entry.color || '#94a3b8',
        metaKey: entry.metaKey || entry.key,
        cmd: `python ${entry.script}${(entry.args || []).length ? ` ${(entry.args || []).join(' ')}` : ''}`,
        countFn: COUNT_FNS[entry.key] || null,
        requires: entry.requires || [],
        missingRequirements: [],
        supportsRefresh: !!refreshByKey[entry.key],
      })));
    }
  } catch (_) {}
  return fetcherSources;
}

