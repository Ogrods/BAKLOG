/**
 * Sponsored / house deal slots across the dashboard and library surfaces.
 *
 * Honest by design: every sponsored slot carries a visible "Sponsored" (or
 * "House") disclosure, is ownership-aware (a slot whose `match_title` you
 * already own is skipped). The paid (pro) tier removes every slot via the
 * server-resolved entitlement (`isPro()`).
 *
 * Closeable vs permanent: paid sponsor cards always carry a dismiss (X), and
 * house promos opt in with `dismissible: true`. Permanent house promos (the
 * dash Pro upsell + the three Pro spotlight slides) have no dismiss affordance
 * and are only removed by upgrading to Pro. All dismissals are session-scoped
 * (in-memory) so closed slots return on the next launch — paying is the only
 * durable way to remove slots.
 *
 * Feed shape v2 (sponsors.json / curated/sponsors.json):
 *   { version: 2, generated_at, ads: { id: { kind, title, dismissible?, art_mode?, ... } },
 *     locations: { "lib-pick": ["ad-id", ...], ... } }
 *   Each physical slot is a location key; ads cycle round-robin per location
 *   (cursor persisted in localStorage across reloads).
 *   kind: "house" -> no badge; anything else -> "Sponsored".
 *   dismissible: house promos opt in to a close (X); sponsors are always closeable.
 *   art_mode: "logo" renders the BAKLOG mark in the dash-spotlight (no cover art).
 *
 * WHERE THE FEED COMES FROM (read this before "my ad edit isn't showing"):
 *   loadSponsoredDeals() resolves in strict order and the FIRST non-empty wins:
 *     1. local  GET /sponsors.json    -> active profile's sponsors.json (seeded via
 *                                          admin console; usually absent in dev)
 *     2. hosted https://baklog.app/sponsors.json (deployed from landing/sponsors.json
 *                                          via Vercel) -- THIS is what most machines use
 *     3. bundled curated/sponsors.json  -- last resort, only when 1 AND 2 are empty/offline
 *   So editing curated/sponsors.json alone changes NOTHING on a machine with internet:
 *   the hosted feed shadows it. To ship a feed-driven banner change you MUST edit
 *   landing/sponsors.json (mirror curated/), commit, push, and let Vercel redeploy
 *   baklog.app. Verify live: GET https://baklog.app/sponsors.json.
 *   Sync pairs: HOUSE_DEFAULTS (below) <-> curated/sponsors.json <-> landing/sponsors.json
 *   <-> scripts/migrate_sponsors_v2.py HOUSE_DEFAULTS <-> admin/admin.js HOUSE_MIGRATION_DEFAULTS.
 *   NOTE: hardcoded banners (proPromoBannerHtml, the wishlist house banner here, and
 *   js/pro-view.js renderConnectionsProLink) are NOT feed-driven -- they update by
 *   editing js/ source + reload (dev raw ESM) or `npm run build` (frozen/built mode).
 */
import { state } from './state.js';
import { escapeHtml, escapeAttr, isSafeHttpUrl } from './dom-util.js';
import { normalizeNameForDedup } from './game-core.js';
import { isOwnedByTitle } from './deals.js';
import { dataFetch } from './api-client.js';
import { isPro } from './auth-gate.js';
import { noteSponsoredImpression } from './anon-metrics.js';
import { PRO_CHECKOUT_MONTHLY } from './pro-checkout.js';
import { affiliateUrl } from './affiliate.js';

const SPONSORS_LOCAL_PATH = 'sponsors.json';
const SPONSORS_FALLBACK_PATH = 'curated/sponsors.json';
export const SPONSORS_HOSTED_URL = 'https://baklog.app/sponsors.json';
const SPONSORS_REMOTE_TIMEOUT_MS = 3000;

export function getSponsorsEndpoint() {
  return (document.querySelector('meta[name="baklog-sponsors-endpoint"]')?.content)
    || window.__BAKLOG_SPONSORS_ENDPOINT
    || SPONSORS_HOSTED_URL;
}

/** Sync pair: AD_LOCATIONS ↔ admin/admin.js AD_LOCATIONS */
export const AD_LOCATIONS = [
  'dash-spotlight',
  'dash-feature-banner',
  'dash-coop-online',
  'dash-coop-couch',
  'dash-versus-rated',
  'dash-versus-fast',
  'dash-pick',
  'dash-house',
  'lib-pick',
  'lib-row',
  'lib-house',
  'wish-pick',
  'wish-row',
  'wish-deal-hero',
  'wish-deal-portrait',
  'wish-house',
  'deals-pick',
  'deals-row',
  'itch-pick',
  'itch-row',
  'itch-house',
  'claim-cards',
];

export const LOCATION_GROUPS = [
  { label: 'Dashboard', keys: ['dash-spotlight', 'dash-feature-banner', 'dash-coop-online', 'dash-coop-couch', 'dash-versus-rated', 'dash-versus-fast', 'dash-pick', 'dash-house'] },
  { label: 'Library', keys: ['lib-pick', 'lib-row', 'lib-house'] },
  { label: 'Wishlist', keys: ['wish-pick', 'wish-row', 'wish-deal-hero', 'wish-deal-portrait', 'wish-house'] },
  { label: 'Deals tab', keys: ['deals-pick', 'deals-row'] },
  { label: 'Itch', keys: ['itch-pick', 'itch-row', 'itch-house'] },
  { label: 'Claimable Now', keys: ['claim-cards'] },
];

/** Per-location max ads shown at once (admin hint + render cap). */
export const LOCATION_CAPACITY = {
  'claim-cards': 3,
  'wish-deal-portrait': 2,
};

const AD_LOCATION_SET = new Set(AD_LOCATIONS);

/** @deprecated use AD_LOCATIONS — kept for tests migrating off placement strings */
export const SPONSOR_PLACEMENTS = AD_LOCATIONS;

const CURSOR_STORAGE_KEY = 'baklog-ad-cursors';
/** @type {Map<string, { start: number, eligibleLen: number }>} */
const sessionLocationPicks = new Map();

const LEGACY_PLACEMENT_TO_LOCATION = {
  'deal-rail': 'wish-house',
  'dash-deal-rail': 'dash-house',
  spotlight: 'dash-spotlight',
  picks: 'lib-pick',
  table: 'lib-row',
  'dash-picks': 'dash-pick',
  'dash-feature-banner': 'dash-feature-banner',
  'dash-versus': 'dash-versus-rated',
  'coop-online': 'dash-coop-online',
  'coop-couch': 'dash-coop-couch',
  claimable: 'claim-cards',
};

// Session-scoped: dismissals live only in memory so a page refresh (a fresh
// module import) restores every sponsored slot. Ads should reappear each
// session rather than persist via personal.json.
const dismissedThisSession = new Set();

export function dismissSponsoredDeal(id) {
  if (!id) return;
  dismissedThisSession.add(id);
}

function isDismissed(id) {
  return dismissedThisSession.has(id);
}

/** Test-only: clear session dismissals between vitest cases. */
export function __resetDismissedSponsorsForTest() {
  dismissedThisSession.clear();
  sessionLocationPicks.clear();
  try { localStorage.removeItem(CURSOR_STORAGE_KEY); } catch (_) { /* noop */ }
}

export function __resetLocationCursorsForTest() {
  sessionLocationPicks.clear();
  try { localStorage.removeItem(CURSOR_STORAGE_KEY); } catch (_) { /* noop */ }
}

/** Test helper: apply v1 items[] or v2 doc into state. */
export function __setSponsorsForTest(doc) {
  if (Array.isArray(doc)) applySponsorsDoc({ items: doc });
  else applySponsorsDoc(doc || {});
}

/** Test-only: exercise v1→v2 migration without loading feeds. */
export function __migrateV1ForTest(doc) {
  return migrateV1ToV2(doc || {});
}

function readCursors() {
  try {
    const raw = localStorage.getItem(CURSOR_STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch (_) {
    return {};
  }
}

function writeCursors(cursors) {
  try {
    localStorage.setItem(CURSOR_STORAGE_KEY, JSON.stringify(cursors));
  } catch (_) { /* noop */ }
}

function advanceCursorForLocation(locationKey, eligibleLen) {
  if (!eligibleLen) return 0;
  const cursors = readCursors();
  const cur = Number(cursors[locationKey]) || 0;
  const idx = cur % eligibleLen;
  cursors[locationKey] = cur + 1;
  writeCursors(cursors);
  return idx;
}

function sessionStartForLocation(locationKey, eligibleLen) {
  if (!sessionLocationPicks.has(locationKey)) {
    sessionLocationPicks.set(locationKey, {
      start: advanceCursorForLocation(locationKey, eligibleLen),
      eligibleLen,
    });
  }
  return sessionLocationPicks.get(locationKey).start;
}

/**
 * Drop the cached session pick for a location so the next getAdsForLocation()
 * advances the round-robin cursor to the next eligible creative. Used by the
 * table so each drill-in / filter shows a fresh row ad instead of pinning the
 * same one for the whole session.
 * @param {string} locationKey
 */
export function rotateLocationAd(locationKey) {
  const key = String(locationKey || '').toLowerCase();
  if (key) sessionLocationPicks.delete(key);
}

export function pickLocationForView(view, kind = 'pick') {
  const v = String(view || 'library').toLowerCase();
  if (kind === 'row') {
    if (v === 'wishlist') return 'wish-row';
    if (v === 'itch') return 'itch-row';
    if (v === 'deals') return 'deals-row';
    return 'lib-row';
  }
  if (v === 'wishlist') return 'wish-pick';
  if (v === 'itch') return 'itch-pick';
  if (v === 'deals') return 'deals-pick';
  return 'lib-pick';
}

export function houseLocationForView(view) {
  const v = String(view || 'library').toLowerCase();
  if (v === 'dashboard') return 'dash-house';
  if (v === 'wishlist') return 'wish-house';
  if (v === 'itch') return 'itch-house';
  return 'lib-house';
}

function withinWindow(item, now = Date.now()) {
  const start = item.starts ? Date.parse(item.starts) : null;
  const end = item.ends ? Date.parse(item.ends) : null;
  if (start != null && Number.isFinite(start) && now < start) return false;
  if (end != null && Number.isFinite(end) && now > end) return false;
  return true;
}

async function fetchJson(path) {
  try {
    const res = await dataFetch(`${path}?t=${Date.now()}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  }
}

function normalizeSponsorsItems(doc) {
  const items = Array.isArray(doc?.items) ? doc.items : [];
  return items.filter(it => it && typeof it === 'object' && it.id && it.title);
}

/** Sync pair: placementMap + HOUSE_DEFAULTS ↔ admin/admin.js migrateSponsorsV1 + scripts/migrate_sponsors_v2.py */
const V1_PLACEMENT_MAP = {
  spotlight: ['dash-spotlight'],
  'dash-feature-banner': ['dash-feature-banner'],
  'coop-online': ['dash-coop-online'],
  'coop-couch': ['dash-coop-couch'],
  'dash-picks': ['dash-pick'],
  picks: ['lib-pick', 'wish-pick', 'deals-pick', 'itch-pick'],
  table: ['lib-row', 'wish-row', 'deals-row', 'itch-row'],
  claimable: ['claim-cards'],
  'deal-rail': ['wish-deal-hero'],
  'dash-deal-rail': ['dash-house'],
};

// Permanent (Pro-only removal): house-pro-promo + the three house-spotlight-pro-*
// creatives. Closeable (dismissible: true, session-scoped): support / backlog /
// privacy house promos. Sync pair: HOUSE_DEFAULTS ↔ curated/sponsors.json +
// scripts/migrate_sponsors_v2.py HOUSE_DEFAULTS.
const HOUSE_DEFAULTS = {
  'house-support-baklog': {
    kind: 'house',
    title: 'Upgrade to BAKLOG Pro',
    tagline: 'Bulk refresh, cloud sync, and no sponsored cards.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    dismissible: true,
    enabled: true,
  },
  'house-pro-promo': {
    kind: 'house',
    title: 'Refresh faster. See fewer ads.',
    tagline: 'Queue stale stores, sync across machines, and remove sponsored deal cards. Nothing you use today moves behind paywall.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    enabled: true,
  },
  'house-lib-backlog': {
    kind: 'house',
    title: 'You own 600 games. You\'ve played 40.',
    tagline: 'One honest backlog across every store. Private, Steam-ready.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    dismissible: true,
    enabled: true,
  },
  'house-itch-privacy': {
    kind: 'house',
    title: 'Upgrade to BAKLOG Pro',
    tagline: 'Background refresh, cloud sync, and no sponsored cards.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    dismissible: true,
    enabled: true,
  },
  'house-spotlight-pro-logo': {
    kind: 'house',
    title: 'BAKLOG Pro',
    slogan: 'One honest backlog across every store.',
    tagline: 'Leveled up with bulk refresh, cloud sync, and no ads.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    art_mode: 'logo',
    scheme: 'ember',
    enabled: true,
  },
  'house-spotlight-pro-sync': {
    kind: 'house',
    title: 'Sync every machine',
    slogan: 'Keep your library and personal data aligned across machines - no manual exports.',
    tagline: 'Cloud sync for library JSON and personal prefs.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    art_mode: 'logo',
    scheme: 'sapphire',
    enabled: true,
  },
  'house-spotlight-pro-noads': {
    kind: 'house',
    title: 'Fewer distractions',
    slogan: 'Paid tier drops sponsored deal slots so your deal radar stays yours.',
    tagline: 'Nothing you use today moves behind paywall.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    art_mode: 'logo',
    scheme: 'emerald',
    enabled: true,
  },
  'house-spotlight-pro-alerts': {
    kind: 'house',
    title: 'Never miss a free game again',
    slogan: 'Alerts when giveaways and sales land.',
    tagline: 'Deal & watchlist alerts - coming soon with Pro.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    art_mode: 'logo',
    scheme: 'amber',
    enabled: true,
  },
  'house-spotlight-library': {
    kind: 'house',
    title: 'It\'s just your library',
    slogan: 'Your library, every store, one place.',
    tagline: 'Every game you own, deduped across stores. Local-first.',
    cta: 'Support BAKLOG',
    url: PRO_CHECKOUT_MONTHLY,
    cover: '',
    art_mode: 'logo',
    scheme: 'sapphire',
    enabled: true,
  },
};

/** Test-only: guaranteed Pro spotlight slides default off under Vitest (game-pool tests). */
const IN_VITEST = typeof import.meta !== 'undefined' && !!import.meta.env?.VITEST;
/** @type {boolean | null} null = auto (off in Vitest, on in app) */
let _spotlightHouseAdsForceForTest = null;
export function setSpotlightHouseAdsForTest(enabled) {
  _spotlightHouseAdsForceForTest = enabled !== false;
}
export function __resetSpotlightHouseAdsForTest() {
  _spotlightHouseAdsForceForTest = null;
}
function spotlightHouseAdsLive() {
  if (isPro()) return false;
  if (_spotlightHouseAdsForceForTest != null) return _spotlightHouseAdsForceForTest;
  return !IN_VITEST;
}

// The permanent Pro spotlight slides, in display order. The large-logo slide is
// first so the dashboard opens on the brand/Pro pitch. Always present in the
// spotlight rotation for free users; removed entirely for Pro (isPro()).
const SPOTLIGHT_PRO_AD_IDS = [
  'house-spotlight-pro-logo',
  'house-spotlight-pro-sync',
  'house-spotlight-pro-noads',
  'house-spotlight-pro-alerts',
  'house-spotlight-library',
];

function placementsForMigration(item) {
  const raw = item?.placements;
  if (raw == null || raw === '') return ['deal-rail'];
  const list = Array.isArray(raw) ? raw : String(raw).split(',');
  return list.map(s => String(s).trim().toLowerCase()).filter(Boolean);
}

function seedHouseDefaults(ads, locations) {
  for (const [hid, creative] of Object.entries(HOUSE_DEFAULTS)) {
    if (!ads[hid]) ads[hid] = creative;
  }
  const houseLocs = {
    'dash-house': 'house-pro-promo',
    'wish-house': 'house-support-baklog',
    'lib-house': 'house-lib-backlog',
    'itch-house': 'house-itch-privacy',
  };
  for (const [loc, hid] of Object.entries(houseLocs)) {
    if (!locations[loc]?.length && ads[hid]) locations[loc] = [hid];
  }
}

function migrateV1ToV2(doc) {
  const items = normalizeSponsorsItems(doc);
  const ads = {};
  const locations = Object.fromEntries(AD_LOCATIONS.map(k => [k, []]));
  const versus = [];
  for (const item of items) {
    const id = item.id;
    const { placements: _placements, priority, ...rest } = item;
    ads[id] = rest;
    for (const p of placementsForMigration(item)) {
      if (p === 'dash-versus') {
        versus.push({ priority: priority ?? 99, id });
        continue;
      }
      for (const loc of V1_PLACEMENT_MAP[p] || []) {
        if (!locations[loc].includes(id)) locations[loc].push(id);
      }
    }
  }
  versus.sort((a, b) => a.priority - b.priority);
  if (versus[0]) locations['dash-versus-rated'].push(versus[0].id);
  if (versus[1]) locations['dash-versus-fast'].push(versus[1].id);
  seedHouseDefaults(ads, locations);
  return {
    version: 2,
    generated_at: doc?.generated_at ?? null,
    ads,
    locations: Object.fromEntries(Object.entries(locations).filter(([, v]) => v.length)),
  };
}

function patchHousePromoCopy(adsMap) {
  for (const [id, defaults] of Object.entries(HOUSE_DEFAULTS)) {
    const ad = adsMap[id];
    if (!ad || typeof ad !== 'object') continue;
    for (const key of ['title', 'tagline', 'slogan', 'cta']) {
      if (defaults[key] != null) ad[key] = defaults[key];
    }
  }
  for (const ad of Object.values(adsMap)) {
    if (!ad || typeof ad !== 'object' || String(ad.kind || '').toLowerCase() !== 'house') continue;
    ad.cta = houseDisplayCta(ad);
    if (typeof ad.tagline === 'string') {
      ad.tagline = ad.tagline
        .replace(/\s*[\u2014\-]\s*\$5\s*\/\s*mo\.?/gi, '')
        .replace(/\s*\(\$50\s*\/\s*yr\)/gi, '')
        .trim();
    }
  }
}

/** House-promo CTA: always "Support BAKLOG" (never legacy "$5/mo" feed copy). */
export function houseDisplayCta(item, fallback = 'Support BAKLOG') {
  const raw = String(item?.cta || '').trim();
  if (!raw || /\$5\s*\/\s*mo/i.test(raw) || /\$50\s*\/\s*yr/i.test(raw) || /get pro/i.test(raw)) {
    return fallback;
  }
  return raw;
}

function sponsorCta(item) {
  const isHouse = String(item?.kind || '').toLowerCase() === 'house';
  if (isHouse) return houseDisplayCta(item);
  return item?.cta || 'Learn more';
}

function applySponsorsDoc(doc) {
  const v2 = doc?.version === 2 ? doc : migrateV1ToV2(doc || {});
  const adsMap = v2.ads && typeof v2.ads === 'object' ? v2.ads : {};
  patchHousePromoCopy(adsMap);
  const locMap = v2.locations && typeof v2.locations === 'object' ? v2.locations : {};
  state.sponsoredAds = adsMap;
  state.adLocations = locMap;
  const flat = [];
  for (const [id, creative] of Object.entries(adsMap)) {
    if (!creative || typeof creative !== 'object') continue;
    flat.push({ ...creative, id });
  }
  state.sponsoredDeals = flat;
  return flat;
}

function resolveAd(id) {
  const creative = state.sponsoredAds?.[id];
  if (!creative || typeof creative !== 'object') return null;
  return { ...creative, id };
}

function isEligibleAd(item, now = Date.now()) {
  if (!item || item.enabled === false) return false;
  if (isDismissed(item.id)) return false;
  if (!withinWindow(item, now)) return false;
  if (item.match_title) {
    const norm = normalizeNameForDedup(item.match_title);
    if (norm && (isOwnedByTitle(item.match_title) || state.ownedNormNames?.has(norm))) return false;
  }
  return true;
}

async function fetchHostedSponsors() {
  const url = getSponsorsEndpoint();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), SPONSORS_REMOTE_TIMEOUT_MS);
  try {
    const res = await fetch(url, { cache: 'no-store', signal: controller.signal });
    if (!res.ok) return null;
    return await res.json();
  } catch (_) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function docHasSponsors(doc) {
  if (!doc || typeof doc !== 'object') return false;
  if (doc.version === 2) {
    return Object.keys(doc.ads || {}).length > 0;
  }
  return Array.isArray(doc.items) && doc.items.length > 0;
}

export async function loadSponsoredDeals() {
  let doc = await fetchJson(SPONSORS_LOCAL_PATH);
  if (docHasSponsors(doc)) return applySponsorsDoc(doc);
  doc = await fetchHostedSponsors();
  if (docHasSponsors(doc)) return applySponsorsDoc(doc);
  doc = await fetchJson(SPONSORS_FALLBACK_PATH);
  return applySponsorsDoc(doc);
}

export function itemPlacements(item) {
  const raw = item?.placements;
  if (raw == null || raw === '') return ['lib-pick'];
  const list = Array.isArray(raw) ? raw : String(raw).split(',');
  return list.map(s => String(s).trim().toLowerCase()).filter(Boolean);
}

/** Locations that reference this ad id (v2 feed). */
export function locationsForAdId(adId) {
  if (!adId) return [];
  const out = [];
  for (const [loc, ids] of Object.entries(state.adLocations || {})) {
    if (Array.isArray(ids) && ids.includes(adId)) out.push(loc);
  }
  return out;
}

export function sponsorCoverUrl(cover) {
  const c = String(cover || '').trim();
  if (!c) return '';
  if (isSafeHttpUrl(c)) return c;
  if (c.startsWith('/') && !c.startsWith('//')) return c;
  return '';
}

function sponsorDisclosure(item) {
  return String(item?.kind || '').toLowerCase() === 'house' ? 'House' : 'Sponsored';
}

function sponsorDiscTitle(item) {
  const isHouse = String(item?.kind || '').toLowerCase() === 'house';
  return isHouse
    ? 'House promotion from BAKLOG (not a paid placement)'
    : 'Paid placement. Disclosed sponsored slot - funds the free tier.';
}

function sponsorHouseClass(item) {
  return String(item?.kind || '').toLowerCase() === 'house' ? ' sponsored-deal-house' : '';
}

export function sponsorActionAttrs(item, { house } = {}) {
  const raw = isSafeHttpUrl(item.url) ? item.url : '';
  const tagged = raw && String(item?.kind || '').toLowerCase() !== 'house'
    ? affiliateUrl(raw)
    : raw;
  const url = tagged ? escapeAttr(tagged) : '';
  const isHouse = house ?? String(item?.kind || '').toLowerCase() === 'house';
  const houseAttr = isHouse ? ' data-sponsor-house="1"' : '';
  return `data-action="sponsored-deal" data-sponsor-id="${escapeAttr(item.id)}" data-sponsor-url="${url}"${houseAttr}`;
}

function sponsorDismissHtml(item) {
  return `<span class="sponsored-deal-dismiss" role="button" tabindex="0" data-action="sponsored-dismiss" data-sponsor-id="${escapeAttr(item.id)}" title="Dismiss this slot" aria-label="Dismiss sponsored slot">&times;</span>`;
}

/** House promos are never dismissible — only Pro tier hides all sponsored slots. */
function houseDismissHtml(_item) {
  return '';
}

/**
 * Disclosure pill for a slot. House promos are BAKLOG's own branded content,
 * so they carry no badge; only genuine paid placements show "Sponsored".
 */
function sponsorBadgeHtml(item, extraClass = '') {
  if (String(item?.kind || '').toLowerCase() === 'house') return '';
  const cls = `sponsored-badge${extraClass ? ` ${extraClass}` : ''}`;
  return `<span class="${cls}" title="${escapeAttr(sponsorDiscTitle(item))}">${sponsorDisclosure(item)}</span>`;
}

/**
 * Eligible ads for a fixed location, cycling round-robin once per app load.
 * @param {string} locationKey
 * @param {{ count?: number }} [opts]
 */
export function getAdsForLocation(locationKey, { count = 1 } = {}) {
  if (isPro()) return [];
  const key = String(locationKey || '').toLowerCase();
  if (!AD_LOCATION_SET.has(key)) return [];
  const ids = state.adLocations?.[key] || [];
  const now = Date.now();
  const eligible = [];
  for (const id of ids) {
    const item = resolveAd(id);
    if (item && isEligibleAd(item, now)) eligible.push(item);
  }
  if (!eligible.length) return [];
  const cap = LOCATION_CAPACITY[key] ?? count;
  const want = Math.min(count, cap, eligible.length);
  const start = sessionStartForLocation(key, eligible.length);
  const out = [];
  for (let i = 0; i < want; i++) {
    out.push(eligible[(start + i) % eligible.length]);
  }
  return out;
}

/**
 * Permanent Pro house creatives for the dashboard spotlight, in display order
 * (large-logo slide first). These are guaranteed-present spotlight slides that
 * pump the Pro tier and carry no dismiss; only Pro removes them. Resolved from
 * the feed when present, falling back to HOUSE_DEFAULTS so they always show.
 * @returns {object[]} feed-shaped ad items (empty for Pro users)
 */
export function getSpotlightHouseAds() {
  if (!spotlightHouseAdsLive()) return [];
  const out = [];
  for (const id of SPOTLIGHT_PRO_AD_IDS) {
    const item = resolveAd(id) || (HOUSE_DEFAULTS[id] ? { ...HOUSE_DEFAULTS[id], id } : null);
    if (!item || item.enabled === false) continue;
    if (isDismissed(id)) continue;
    out.push(item);
  }
  return out;
}

/**
 * @deprecated use getAdsForLocation — maps legacy placement strings to a location.
 */
export function getEligibleSponsors(placement) {
  const loc = LEGACY_PLACEMENT_TO_LOCATION[String(placement || '').toLowerCase()] || placement;
  const count = loc === 'claim-cards' ? 3 : (LOCATION_CAPACITY[loc] ?? 1);
  return getAdsForLocation(loc, { count });
}

/** First eligible wish-deal-hero slot, or null. */
export function getEligibleSponsoredDeal() {
  return getAdsForLocation('wish-deal-hero')[0] || null;
}

/**
 * Stable per-column ad assignment for the dash-versus ("What to play next") card.
 * Columns are pinned by priority across the full candidate set (dismissal aside),
 * so dismissing one column's ad never promotes the other column's ad into its
 * slot. A column whose ad is dismissed returns null but stays "reserved" — the
 * caller fills that row with the next-ranked real game instead of the ad.
 * @returns {{rated: object|null, fast: object|null, ratedReserved: boolean, fastReserved: boolean}}
 */
export function getVersusColumnAds() {
  const empty = { rated: null, fast: null, ratedReserved: false, fastReserved: false };
  if (isPro()) return empty;
  const ratedIds = state.adLocations?.['dash-versus-rated'] || [];
  const fastIds = state.adLocations?.['dash-versus-fast'] || [];
  return {
    rated: getAdsForLocation('dash-versus-rated')[0] || null,
    fast: getAdsForLocation('dash-versus-fast')[0] || null,
    ratedReserved: ratedIds.length > 0,
    fastReserved: fastIds.length > 0,
  };
}

// Compact BAKLOG logo mark (mirrors landing/index.html hero mark) for the
// full-width house promo banner. Inline so the banner needs no extra asset.
function baklogBannerMarkHtml(maskId) {
  const safeId = String(maskId || 'houseBannerKnobs').replace(/[^\w-]/g, '');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" role="img" aria-label="BAKLOG logo" focusable="false">
  <defs>
    <mask id="${safeId}" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
      <rect width="100" height="100" fill="#fff"/>
      <circle cx="14" cy="64" r="8" fill="#000"/>
      <circle cx="64" cy="64" r="8" fill="#000"/>
      <circle cx="39" cy="36" r="8" fill="#000"/>
    </mask>
  </defs>
  <g fill="currentColor" mask="url(#${safeId})">
    <rect x="2"  y="52" width="46" height="24" rx="12" ry="12"/>
    <rect x="52" y="52" width="46" height="24" rx="12" ry="12"/>
    <rect x="27" y="24" width="46" height="24" rx="12" ry="12"/>
  </g>
</svg>`;
}

/** Large BAKLOG mark for the logo-layout dashboard spotlight slide. */
export function spotlightLogoMarkHtml() {
  return baklogBannerMarkHtml('spotlightProMark');
}

// Promo columns for the house banner — info-rich pitch pulled from the landing
// copy so the in-app message stays in sync with baklog.app. Each fills one of
// the three feature columns that span the full-width deal-radar row.
// Sync pair: HOUSE_BANNER_FEATURES ↔ landing/index.html trust + hero pillars.
const HOUSE_BANNER_FEATURES = [
  {
    title: 'Local-first',
    desc: 'Your library never leaves your machine. No BAKLOG server holds your data.',
  },
  {
    title: 'Every store, one list',
    desc: '12 libraries and 8 wishlists, deduped across Steam, Epic, GOG, and more.',
  },
  {
    title: 'Open source',
    desc: 'No telemetry. Full source on GitHub (MIT) - audit every line.',
  },
];

// Homepage Pro upsell — pulled from landing/index.html paid-tier copy.
// Sync pair: PRO_PROMO ↔ landing/index.html paid tier + FAQ pricing answers.
export const PRO_PROMO = {
  label: 'BAKLOG Pro',
  title: 'Refresh faster. See fewer ads.',
  price: '',
  tagline: 'Queue stale stores, sync across machines, and remove sponsored deal cards. Nothing you use today moves behind paywall.',
  cta: 'Support BAKLOG',
  ctaYearly: 'Support BAKLOG',
  url: PRO_CHECKOUT_MONTHLY,
  founderNote: 'Back the roadmap while Pro is early.',
  features: [
    {
      title: 'Queued bulk refresh',
      desc: 'Queue every stale store at once and let them refresh back-to-back instead of one at a time.',
      icon: '⚡',
    },
    {
      title: 'Scheduled refresh',
      desc: 'Stale-store refresh runs even when the app is closed (tray or OS scheduler).',
      icon: '⏱',
    },
    {
      title: 'No sponsored cards',
      desc: 'Paid tier drops sponsored deal slots so your deal radar stays yours.',
      icon: '✦',
    },
    {
      title: 'Cloud sync',
      desc: 'Keep your library and personal data aligned across machines without manual exports.',
      icon: '☁',
    },
    {
      title: 'Deep achievement sync',
      desc: 'Full on-demand trophy/achievement re-pull (free tier shows cached % only).',
      icon: '🏆',
    },
    {
      title: 'Bonus claimables feed',
      desc: 'DLC, add-ons, and in-game bonuses filtered out of the free feed, surfaced for Pro.',
      icon: '🎁',
    },
    {
      title: 'Deal/watchlist alerts',
      desc: 'Never miss a free game again - alerts when Epic, GOG, Steam, and Prime drops land, plus wishlist price targets.',
      icon: '🔔',
    },
  ],
  tierCompare: [
    { feature: 'Import & browse all stores', free: '✓', pro: '✓' },
    { feature: 'Manual store refresh', free: 'One at a time', pro: 'Queue all stale stores' },
    { feature: 'Auto-refresh while app is open', free: '✓ (one store / ~30 min)', pro: '✓' },
    { feature: 'Refresh while app is closed', free: '-', pro: '✓' },
    { feature: 'Claimable Now (full games)', free: '✓', pro: '✓ + bonus DLC/bonus feed' },
    { feature: 'Sponsored deal cards', free: 'Shown', pro: 'Removed' },
    { feature: 'Deep achievement/trophy sync', free: 'Cached % only', pro: 'Full re-pull' },
    { feature: 'Cloud sync', free: '-', pro: '✓' },
    { feature: 'Deal/watchlist alerts', free: '-', pro: '✓' },
  ],
  trustPoints: [
    'Local-first - your library stays on your machine',
    'Open source (MIT) - audit every fetcher path',
    'Polar.sh Merchant of Record (open source, like us) - cancel anytime',
    'Zero telemetry unless you opt in',
  ],
};

const PRO_PROMO_SPONSOR_IDS = new Set([
  'house-support-baklog',
  'house-pro-promo',
  'house-spotlight-pro-logo',
  'house-spotlight-pro-sync',
  'house-spotlight-pro-noads',
  'house-spotlight-pro-alerts',
  'house-lib-backlog',
  'house-spotlight-library',
  'house-itch-privacy',
  'house-table-every-store',
]);

/** True for in-app house promos that should open the Pro view tab (not Polar directly). */
export function isProPromoSponsorId(id) {
  return PRO_PROMO_SPONSOR_IDS.has(String(id || '').trim());
}

/** Hard-coded wishlist deal-rail house banner (not driven by sponsors.json). */
export const HOUSE_DEAL_ITEM = {
  id: 'house-support-baklog',
  kind: 'house',
  title: 'Upgrade to BAKLOG Pro',
  tagline: 'Bulk refresh, cloud sync, and no sponsored cards.',
  cta: 'Support BAKLOG',
  url: PRO_CHECKOUT_MONTHLY,
  dismissible: true,
};

/** Hard-coded dashboard Pro upsell (not driven by sponsors.json). */
export const PRO_PROMO_ITEM = {
  id: 'house-pro-promo',
  kind: 'house',
  title: PRO_PROMO.title,
  tagline: PRO_PROMO.tagline,
  cta: PRO_PROMO.cta,
  url: PRO_PROMO.url,
};

/**
 * Full-width house promo banner for the deal-rail slot. Spans the whole
 * deal-radar grid row (sm:col-span-3) and fills it with BAKLOG promo material
 * instead of the compact 1/3-width sponsor card. Internal layout: brand block
 * on the left, three info columns filling the middle, CTA on the right.
 */
export function houseDealBannerHtml(item, { accent = 'blue' } = {}) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const accentCls = accent === 'green' ? ' sponsored-deal-banner--green' : '';
  const tagline = item.tagline
    ? `<p class="house-banner-tagline">${escapeHtml(item.tagline)}</p>`
    : '';
  const features = HOUSE_BANNER_FEATURES
    .map(f => `<li class="house-banner-feature">
        <span class="house-banner-feature-title">${escapeHtml(f.title)}</span>
        <span class="house-banner-feature-desc">${escapeHtml(f.desc)}</span>
      </li>`)
    .join('');
  return `<button type="button"
    class="dash-card deal-rail-card sponsored-deal-card sponsored-deal-house sponsored-deal-banner${accentCls} text-left w-full"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    <div class="house-banner-grid">
      <div class="house-banner-brand">
        <span class="house-banner-mark" aria-hidden="true">${baklogBannerMarkHtml(`houseBannerKnobs-${item.id || 'house'}`)}</span>
        <div class="house-banner-copy min-w-0">
          <div class="house-banner-head">
            <span class="dash-kpi-label">Featured deal</span>
            ${sponsorBadgeHtml(item, 'sponsored-badge--inline')}
          </div>
          <div class="house-banner-title">${escapeHtml(item.title)}</div>
          ${tagline}
        </div>
      </div>
      <ul class="house-banner-features">${features}</ul>
      <span class="house-banner-cta">${escapeHtml(cta)} &rarr;</span>
    </div>
    ${houseDismissHtml(item)}
  </button>`;
}

/**
 * Full-width Pro tier upsell for the dashboard deal-rail slot only. Distinct
 * from the wishlist house waitlist banner; non-dismissible and hidden for Pro
 * subscribers (they already have the paid entitlement).
 * @param {object | null | undefined} item — dash-deal-rail feed row; title/tagline/cta/url override PRO_PROMO defaults.
 */
export function proPromoBannerHtml(item) {
  if (isPro()) return '';
  if (!item) return '';
  const discTitle = 'House promotion from BAKLOG - optional paid tier';
  const title = item.title || PRO_PROMO.title;
  const taglineText = item.tagline ?? PRO_PROMO.tagline;
  const cta = houseDisplayCta(item, PRO_PROMO.cta);
  const urlRaw = item.url || PRO_PROMO.url;
  const tagline = taglineText
    ? `<p class="house-banner-tagline">${escapeHtml(taglineText)}</p>`
    : '';
  const price = PRO_PROMO.price
    ? `<p class="house-banner-price">${escapeHtml(PRO_PROMO.price)}</p>`
    : '';
  const features = PRO_PROMO.features
    .map(f => `<li class="house-banner-feature">
        <span class="house-banner-feature-title">${escapeHtml(f.title)}</span>
        <span class="house-banner-feature-desc">${escapeHtml(f.desc)}</span>
      </li>`)
    .join('');
  const url = isSafeHttpUrl(urlRaw) ? escapeAttr(urlRaw) : '';
  const sponsorId = item.id || 'house-pro-promo';
  return `<button type="button"
    class="dash-card deal-rail-card sponsored-deal-card sponsored-deal-pro sponsored-deal-banner text-left w-full"
    data-action="sponsored-deal" data-sponsor-id="${escapeAttr(sponsorId)}" data-sponsor-url="${url}" data-sponsor-house="1"
    title="${escapeAttr(discTitle)}">
    <div class="house-banner-grid">
      <div class="house-banner-brand">
        <span class="house-banner-mark" aria-hidden="true">${baklogBannerMarkHtml(`houseBannerKnobs-${sponsorId}`)}</span>
        <div class="house-banner-copy min-w-0">
          <div class="house-banner-head">
            <span class="dash-kpi-label">${escapeHtml(PRO_PROMO.label)}</span>
          </div>
          <div class="house-banner-title">${escapeHtml(title)}</div>
          ${price}
          ${tagline}
        </div>
      </div>
      <ul class="house-banner-features">${features}</ul>
      <span class="house-banner-cta">${escapeHtml(cta)} &rarr;</span>
    </div>
  </button>`;
}

/** Markup for the dashboard house slot (dash-house — Pro upsell). */
export function proPromoSlotHtml() {
  if (isPro()) return '';
  const item = getAdsForLocation('dash-house')[0] || PRO_PROMO_ITEM;
  return proPromoBannerHtml(item);
}

/** Compact house stripe below picks (library / itch). */
export function houseStripeCardHtml(item, { variant = 'lib' } = {}) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const variantCls = variant === 'itch' ? ' house-stripe-card--itch' : ' house-stripe-card--lib';
  return `<button type="button"
    class="house-stripe-card${variantCls}${sponsorHouseClass(item)} text-left w-full"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    <span class="house-stripe-mark" aria-hidden="true">${baklogBannerMarkHtml(`houseStripe-${item.id || variant}`)}</span>
    <span class="house-stripe-copy min-w-0 flex-1">
      <span class="house-stripe-title">${escapeHtml(item.title)}</span>
      ${item.tagline ? `<span class="house-stripe-tagline">${escapeHtml(item.tagline)}</span>` : ''}
    </span>
    <span class="house-stripe-cta">${escapeHtml(cta)} &rarr;</span>
    ${houseDismissHtml(item)}
  </button>`;
}

export function renderHouseLocationSlot(locationKey, slotElId, { variant } = {}) {
  const el = document.getElementById(slotElId);
  if (!el) return;
  const item = getAdsForLocation(locationKey)[0];
  if (!item) {
    el.classList.add('hidden');
    el.innerHTML = '';
    return;
  }
  noteSponsoredImpression(locationKey, item.id);
  el.classList.remove('hidden');
  if (locationKey === 'wish-house') {
    el.innerHTML = houseDealBannerHtml(item, { accent: 'green' });
    return;
  }
  if (locationKey === 'dash-house') {
    const kind = String(item.kind || '').toLowerCase();
    el.innerHTML = kind === 'house'
      ? proPromoBannerHtml(item)
      : sponsoredDealCardHtml(item);
    return;
  }
  el.innerHTML = houseStripeCardHtml(item, { variant: variant || (locationKey.startsWith('itch') ? 'itch' : 'lib') });
}

export function sponsoredDealCardHtml(item) {
  if (!item) return '';
  if (String(item.kind || '').toLowerCase() === 'house') {
    return houseDealBannerHtml(item);
  }
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const tagline = item.tagline ? `<div class="sponsored-deal-tagline">${escapeHtml(item.tagline)}</div>` : '';
  const coverUrl = sponsorCoverUrl(item.cover);
  const cover = coverUrl
    ? `<img class="sponsored-deal-cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  return `<button type="button"
    class="deal-card-clickable dash-card deal-rail-card sponsored-deal-card${sponsorHouseClass(item)} text-left w-full"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    <div class="sponsored-deal-head">
      <span class="dash-kpi-label">Featured deal</span>
      ${sponsorBadgeHtml(item)}
    </div>
    <div class="sponsored-deal-body mt-2">
      ${cover}
      <div class="sponsored-deal-meta min-w-0 flex-1">
        <div class="sponsored-deal-name">${escapeHtml(item.title)}</div>
        ${tagline}
        <span class="sponsored-deal-cta">${escapeHtml(cta)} &rarr;</span>
      </div>
    </div>
    ${sponsorDismissHtml(item)}
  </button>`;
}

/** Markup for the wishlist house banner (wish-house location), green accent. */
export function sponsoredDealSlotHtml() {
  const item = getAdsForLocation('wish-house')[0];
  if (!item) return '';
  return houseDealBannerHtml(item, { accent: 'green' });
}

export function sponsoredPickCardHtml(item) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  // Mirror pickCardHtml exactly so the tile occupies one grid slot with identical
  // dimensions (fixed 2/3 cover box + name line + one-line meta row). Landscape
  // covers get the same letterbox handling as real pick covers via markLandscape.
  const ls = coverUrl ? (window.coverLandscapeAttr?.(coverUrl) || '') : '';
  const coverHtml = coverUrl
    ? `<img class="pick-cover${ls}" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onload="window.markLandscape&&window.markLandscape(this)" onerror="this.style.display='none'" />`
    : `<div class="pick-cover placeholder flex items-center justify-center text-slate-500 text-xs">Ad</div>`;
  return `<button type="button"
    class="pick-card sponsored-pick-card relative rounded p-2 text-left w-full${sponsorHouseClass(item)}"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    <div class="cover-wrap w-full block${ls}">${coverHtml}</div>
    <div class="text-xs text-slate-200 mt-1 flex items-center justify-between gap-1">
      <span class="truncate font-medium">${escapeHtml(item.title)}</span>
      ${sponsorBadgeHtml(item, 'sponsored-pick-badge')}
    </div>
    <div class="text-xs text-slate-400 flex justify-between gap-1">
      <span class="truncate">${escapeHtml(item.tagline || '')}</span>
      <span class="sponsored-deal-cta shrink-0" aria-label="${escapeAttr(cta)}">&rarr;</span>
    </div>
    ${sponsorDismissHtml(item)}
  </button>`;
}

export function sponsoredPickSlotHtml(locationKey = 'lib-pick') {
  const item = getAdsForLocation(locationKey)[0];
  if (item) noteSponsoredImpression(locationKey, item.id);
  return item ? sponsoredPickCardHtml(item) : '';
}

/** Wishlist-deals picks tab: mirror dealCardHtml's 3-row info block. */
export function sponsoredDealPickCardHtml(item) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const ls = coverUrl ? (window.coverLandscapeAttr?.(coverUrl) || '') : '';
  const coverHtml = coverUrl
    ? `<img class="pick-cover${ls}" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onload="window.markLandscape&&window.markLandscape(this)" onerror="this.style.display='none'" />`
    : `<div class="pick-cover placeholder flex items-center justify-center text-slate-500 text-xs">Ad</div>`;
  const s = sponsorFakeStats(item);
  const priceLabel = `$${s.sale}`;
  const cutLabel = `-${s.disc}%`;
  const cutClass = s.disc >= 75
    ? 'deal-flag-cut deal-flag-cut--huge'
    : s.disc >= 50
      ? 'deal-flag-cut deal-flag-cut--big'
      : 'deal-flag-cut';
  const rating = `${s.steam}%`;
  return `<button type="button"
    class="pick-card sponsored-pick-card relative rounded p-2 text-left w-full${sponsorHouseClass(item)}"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    <div class="cover-wrap w-full block${ls}">${coverHtml}</div>
    <div class="text-xs text-slate-200 mt-1 flex items-center justify-between gap-1">
      <span class="truncate font-medium">${escapeHtml(item.title)}</span>
      ${sponsorBadgeHtml(item, 'sponsored-pick-badge')}
    </div>
    <div class="text-xs text-slate-400 flex justify-between items-center gap-1">
      <span class="text-slate-100">${priceLabel}</span>
      <span class="flex items-center gap-1 shrink-0">
        <span class="${cutClass}">${cutLabel}</span>
      </span>
    </div>
    <div class="text-[10px] text-slate-500 flex justify-between gap-1 mt-0.5 min-w-0">
      <span class="truncate sponsored-deal-cta" aria-label="${escapeAttr(cta)}">${escapeHtml(cta)} &rarr;</span>
      <span class="flex items-center gap-1 shrink-0">${rating}</span>
    </div>
    ${sponsorDismissHtml(item)}
  </button>`;
}

export function sponsoredDealPickSlotHtml(locationKey = 'wish-pick') {
  const item = getAdsForLocation(locationKey)[0];
  if (item) noteSponsoredImpression(locationKey, item.id);
  return item ? sponsoredDealPickCardHtml(item) : '';
}

// FNV-1a-ish string hash → stable 32-bit seed for synthetic stats.
function sponsorHash(value) {
  const str = String(value || 'sponsor');
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const SPONSOR_FAKE_GENRES = ['Roguelike', 'Action', 'Indie', 'RPG', 'Strategy', 'Adventure'];

/**
 * Stable, plausible-looking stats so a sponsored table row reads like a real
 * game row instead of a bare banner. Values are seeded from the item id (so
 * they never flicker between renders) and any explicit feed field wins, letting
 * a real sponsor later pin its own numbers in sponsors.json.
 */
function sponsorFakeStats(item) {
  const seed = sponsorHash(item.id || item.title);
  const at = (shift, span, min) => min + ((seed >>> shift) % span);
  const steam = item.steam_review_percent ?? at(0, 16, 82); // 82-97%
  const mc = item.metacritic_score ?? at(4, 15, 78); // 78-92
  const hltb = item.hltb_hours ?? at(8, 19, 6); // 6-24h
  const year = item.release_year ?? at(16, 6, 2020); // 2020-2025
  const disc = item.discount ?? [20, 25, 33, 40, 50][seed % 5];
  const baseNum = item.price_base ?? [14.99, 19.99, 24.99, 29.99][(seed >>> 12) % 4];
  const sale = item.price_sale != null
    ? Number(item.price_sale).toFixed(2)
    : (baseNum * (1 - disc / 100)).toFixed(2);
  const base = baseNum.toFixed(2);
  const score = (steam / Math.log2(hltb + 2)).toFixed(1);
  const genres = item.genres
    ? (Array.isArray(item.genres) ? item.genres.join(', ') : String(item.genres))
    : SPONSOR_FAKE_GENRES[seed % SPONSOR_FAKE_GENRES.length];
  return { steam, mc, hltb, year, disc, sale, base, score, genres };
}

const SP_DASH = '<span class="text-slate-600">-</span>';

/** BAKLOG-branded table row (no faux game stats or Deal pill). */
export function houseTableRowHtml(item, { locationKey = 'lib-row' } = {}) {
  if (!item) return '';
  noteSponsoredImpression(locationKey, item.id);
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverCell = coverUrl
    ? `<span class="cover-wrap"><img class="cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" /></span>`
    : `<span class="house-table-mark" aria-hidden="true">${baklogBannerMarkHtml(`houseRow-${item.id || 'house'}`)}</span>`;
  const tagline = item.tagline
    ? `<span class="house-table-tagline">${escapeHtml(item.tagline)}</span>`
    : '';
  return `<tr class="sponsored-table-row sponsored-table-row--house sponsored-deal-house" data-sponsored-row="1"
    ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
    <td class="col-select p-2 text-center" aria-hidden="true"></td>
    <td class="col-cover p-2">${coverCell}</td>
    <td class="col-house-promo p-2" colspan="12">
      <span class="house-table-strip">
        <span class="house-table-copy min-w-0">
          <span class="house-table-kicker">From BAKLOG</span>
          <span class="house-table-title">${escapeHtml(item.title)}</span>
          ${tagline}
        </span>
        <span class="house-table-cta">${escapeHtml(cta)} &rarr;</span>
        ${houseDismissHtml(item)}
      </span>
    </td>
  </tr>`;
}

/** House promo rendered in the full-column sponsor shell (dismiss swap path). */
function houseTableRowInSponsorShellHtml(item, { locationKey = 'lib-row' } = {}) {
  if (!item) return '';
  noteSponsoredImpression(locationKey, item.id);
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  const coverCell = `<span class="cover-wrap"><span class="house-table-mark" aria-hidden="true">${baklogBannerMarkHtml(`houseRowShell-${item.id || 'house'}`)}</span></span>`;
  return `<tr class="sponsored-table-row sponsored-deal-house" data-sponsored-row="1"
    ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
    <td class="col-select p-2 text-center" aria-hidden="true"></td>
    <td class="col-cover p-2">${coverCell}</td>
    <td class="col-game p-2 game-name-cell">
      <button type="button" class="sponsored-table-name text-left w-full">
        <span class="flex items-center gap-1.5 min-w-0">
          <span class="sponsored-table-title game-name truncate min-w-0">${escapeHtml(item.title)}</span>
          <span class="sponsored-badge sponsored-table-badge shrink-0" title="${escapeAttr(discTitle)}">From BAKLOG</span>
        </span>
        ${tagline ? `<span class="sponsored-table-tagline-row">${tagline}</span>` : ''}
      </button>
    </td>
    <td class="col-status p-2">${SP_DASH}</td>
    <td class="col-score p-2 text-right">${SP_DASH}</td>
    <td class="col-played p-2 text-right text-slate-300">${SP_DASH}</td>
    <td class="col-hltb p-2 text-right text-slate-300">${SP_DASH}</td>
    <td class="col-steam p-2 text-right">${SP_DASH}</td>
    <td class="col-mc p-2 text-right text-slate-300">${SP_DASH}</td>
    <td class="col-price p-2 text-right">${SP_DASH}</td>
    <td class="col-released p-2 text-slate-300 whitespace-nowrap">${SP_DASH}</td>
    <td class="col-lastplayed p-2 text-slate-300">${SP_DASH}</td>
    <td class="col-genres p-2 text-slate-400 text-xs truncate"></td>
    <td class="col-notes p-2 sponsored-table-notes">
      <span class="sponsored-deal-cta">${escapeHtml(cta)} &rarr;</span>
    </td>
  </tr>`;
}

export function sponsoredTableRowHtml(item, { isWish: _isWish, locationKey = 'lib-row', tableLayout = 'auto' } = {}) {
  if (!item) return '';
  const isHouse = String(item.kind || '').toLowerCase() === 'house';
  if (isHouse && tableLayout === 'sponsor') {
    return houseTableRowInSponsorShellHtml(item, { locationKey });
  }
  if (isHouse) {
    return houseTableRowHtml(item, { locationKey });
  }
  noteSponsoredImpression(locationKey, item.id);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  const cta = sponsorCta(item);
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  const s = sponsorFakeStats(item);
  // The whole row is the click target (data-action on the <tr>); the focusable
  // name button gives keyboard users an Enter/Space activation that bubbles to
  // the same document-level sponsored-deal handler.
  return `<tr class="sponsored-table-row${sponsorHouseClass(item)}" data-sponsored-row="1"
    ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
    <td class="col-select p-2 text-center" aria-hidden="true"></td>
    <td class="col-cover p-2">${coverHtml ? `<span class="cover-wrap">${coverHtml}</span>` : ''}</td>
    <td class="col-game p-2 game-name-cell">
      <button type="button" class="sponsored-table-name text-left w-full">
        <span class="flex items-center gap-1.5 min-w-0">
          <span class="sponsored-table-title game-name truncate min-w-0">${escapeHtml(item.title)}</span>
          ${sponsorBadgeHtml(item, 'sponsored-table-badge shrink-0')}
        </span>
        ${tagline ? `<span class="sponsored-table-tagline-row">${tagline}</span>` : ''}
      </button>
    </td>
    <td class="col-status p-2"><span class="sponsored-table-status-pill">Deal</span></td>
    <td class="col-score p-2 text-right">${s.score}</td>
    <td class="col-played p-2 text-right text-slate-300">${SP_DASH}</td>
    <td class="col-hltb p-2 text-right text-slate-300">${s.hltb}h</td>
    <td class="col-steam p-2 text-right">${s.steam}%</td>
    <td class="col-mc p-2 text-right text-slate-300">${s.mc}</td>
    <td class="col-price p-2 text-right"><span class="sponsored-table-deal-pill">-${s.disc}% $${s.sale}</span></td>
    <td class="col-released p-2 text-slate-300 whitespace-nowrap">${s.year}</td>
    <td class="col-lastplayed p-2 text-slate-300">${SP_DASH}</td>
    <td class="col-genres p-2 text-slate-400 text-xs truncate" title="${escapeAttr(s.genres)}">${escapeHtml(s.genres)}</td>
    <td class="col-notes p-2 sponsored-table-notes">
      <span class="sponsored-deal-cta">${escapeHtml(cta)} &rarr;</span>
      ${sponsorDismissHtml(item)}
    </td>
  </tr>`;
}

/** Mimics dash-versus-row inside the "What to play next" card columns. */
export function sponsoredVersusRowHtml(item, { metric = 'rating', locationKey = 'dash-versus-rated' } = {}) {
  if (!item) return '';
  noteSponsoredImpression(locationKey, item.id);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="dash-list-cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : `<div class="dash-list-cover placeholder flex items-center justify-center text-slate-500 text-xs">Ad</div>`;
  const s = sponsorFakeStats(item);
  const scoreLabel = metric === 'hltb' ? `${s.hltb}h` : `${s.steam}%`;
  const accentCls = metric === 'hltb' ? 'dash-versus-row--fast' : 'dash-versus-row--rated';
  return `<button type="button"
    class="dash-list-row dash-versus-row ${accentCls} sponsored-versus-row${sponsorHouseClass(item)}"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    ${coverHtml}
    <span class="dash-row-title flex-1">
      <span class="flex items-center gap-1.5 min-w-0">
        <span class="truncate">${escapeHtml(item.title)}</span>
        ${sponsorBadgeHtml(item, 'sponsored-versus-badge')}
      </span>
    </span>
    <span class="text-slate-400 sponsored-versus-score">${escapeHtml(scoreLabel)}</span>
    ${sponsorDismissHtml(item)}
  </button>`;
}

/** Mimics coop-pick-row inside the Co-op spotlight card pick lists. */
export function sponsoredCoopPickRowHtml(item, locationKey = 'dash-coop-online') {
  if (!item) return '';
  noteSponsoredImpression(locationKey, item.id);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="coop-pick-cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : `<div class="coop-pick-cover placeholder flex items-center justify-center text-slate-500 text-xs">Ad</div>`;
  const s = sponsorFakeStats(item);
  return `<button type="button"
    class="coop-pick-row sponsored-coop-row${sponsorHouseClass(item)}"
    ${sponsorActionAttrs(item)}
    title="${escapeAttr(discTitle)}">
    ${coverHtml}
    <span class="coop-pick-name-wrap">
      <span class="coop-pick-name">${escapeHtml(item.title)}</span>
      ${sponsorBadgeHtml(item, 'sponsored-coop-badge')}
    </span>
    <span class="coop-pick-rating">${s.steam}%</span>
    ${sponsorDismissHtml(item)}
  </button>`;
}

// Sub-card stat chips for the full feature ad. Each is a backgrounded mini
// card; values come from sponsorFakeStats (authored fields win, otherwise a
// stable synthetic value seeded from the item id).
function sponsoredFeatureStatsHtml(s) {
  const chips = [
    { label: 'Steam', value: `${s.steam}%`, cls: ' is-rating' },
    { label: 'Metacritic', value: String(s.mc), cls: ' is-mc' },
    { label: 'Main story', value: `${s.hltb}h`, cls: '' },
    { label: 'Released', value: String(s.year), cls: '' },
  ];
  return chips
    .map(c => `<span class="sponsored-feature-stat${c.cls}">
        <span class="sponsored-feature-stat-value">${escapeHtml(c.value)}</span>
        <span class="sponsored-feature-stat-label">${escapeHtml(c.label)}</span>
      </span>`)
    .join('');
}

function isBundleFeatureAd(item) {
  return Number(item?.bundle_items) > 0;
}

function sponsoredBundleStatsHtml(item, s) {
  const items = Number(item.bundle_items) || 0;
  const creators = Number(item.bundle_creators) || 0;
  const chips = [
    { label: 'Items', value: String(items), cls: '' },
    { label: 'Creators', value: String(creators), cls: '' },
    { label: 'Off', value: `${s.disc}%`, cls: ' is-discount' },
    { label: 'Bundle', value: `$${s.sale}`, cls: ' is-price' },
  ];
  return chips
    .map(c => `<span class="sponsored-feature-stat${c.cls}">
        <span class="sponsored-feature-stat-value">${escapeHtml(c.value)}</span>
        <span class="sponsored-feature-stat-label">${escapeHtml(c.label)}</span>
      </span>`)
    .join('');
}

function sponsoredBundleTitlesHtml(item) {
  const titles = Array.isArray(item.featured_titles) ? item.featured_titles : [];
  if (!titles.length) return '';
  const rows = titles.slice(0, 5).map(title =>
    `<div class="sponsored-bundle-title-row">
        <span class="sponsored-bundle-title-dot" aria-hidden="true"></span>
        <span class="sponsored-bundle-title-text">${escapeHtml(String(title))}</span>
      </div>`,
  ).join('');
  return `<div class="sponsored-bundle-titles-label">Includes</div>
      <div class="sponsored-bundle-titles">${rows}</div>`;
}

/**
 * Elevated itch.io bundle variant for the dash-pick slot. Keeps the feature-card
 * art fade but swaps game stats for bundle metrics and a compact title list that
 * mirrors the sibling "Recently added" rows in the picks row.
 */
function sponsoredFeatureBundleAdHtml(item, { banner = false } = {}) {
  const discTitle = sponsorDiscTitle(item);
  const cta = item.cta || 'Grab the bundle';
  const coverUrl = sponsorCoverUrl(item.cover);
  const s = sponsorFakeStats(item);
  const network = item.network ? escapeHtml(String(item.network)) : '';
  const showWas = s.disc > 0 && s.base;
  const artLayers = coverUrl
    ? `<img class="sponsored-feature-art-bg" src="${escapeAttr(coverUrl)}" alt="" aria-hidden="true" loading="lazy" onerror="this.style.display='none'" />
      <img class="sponsored-feature-art" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />
      <span class="sponsored-feature-fade" aria-hidden="true"></span>`
    : '';
  const bannerCls = banner ? ' sponsored-feature-card--banner' : '';
  const noArtCls = coverUrl ? '' : ' no-art';
  const body = `<div class="sponsored-feature-body">
      <div class="sponsored-feature-head">
        <span class="dash-kpi-label">Featured bundle</span>
      </div>
      <div class="sponsored-feature-hero">
        <div class="sponsored-feature-title">${escapeHtml(item.title)}</div>
        ${item.tagline ? `<p class="sponsored-feature-blurb">${escapeHtml(item.tagline)}</p>` : ''}
        <div class="sponsored-feature-priceline">
          <span class="sponsored-feature-cut">-${s.disc}%</span>
          <span class="sponsored-feature-sale">$${s.sale}</span>
          ${showWas ? `<span class="sponsored-feature-was">$${s.base}</span>` : ''}
        </div>
      </div>
      <div class="sponsored-feature-panel">
        <div class="sponsored-feature-stats sponsored-feature-stats--bundle">
          ${sponsoredBundleStatsHtml(item, s)}
        </div>
      </div>
      ${sponsoredBundleTitlesHtml(item)}
      <div class="sponsored-feature-detail">
        ${network ? `<span class="sponsored-feature-by">${network}</span>` : ''}
      </div>
      <span class="sponsored-feature-cta">${escapeHtml(cta)} &rarr;</span>
    </div>`;
  return `<button type="button"
    class="dash-card sponsored-feature-card sponsored-feature-card--bundle${noArtCls}${bannerCls}${sponsorHouseClass(item)} text-left w-full"
    ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
    ${sponsorBadgeHtml(item, 'sponsored-badge--inline')}
    ${artLayers}${body}
    ${sponsorDismissHtml(item)}
  </button>`;
}

/**
 * Shared markup for the content-rich "feature" sponsor ad. Cover art bleeds in
 * from the right and fades right-to-left into the card background (mirrors the
 * spotlight fade), while the info and sponsor details sit in backgrounded
 * sub-cards on the left.
 *
 * `banner: true` keeps the identical aesthetic but lays the content out as a
 * full-width horizontal strip (used between the dashboard charts) instead of
 * the tall dash-picks card.
 */
function sponsoredFeatureAdHtml(item, { banner = false } = {}) {
  const discTitle = sponsorDiscTitle(item);
  const cta = sponsorCta(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const s = sponsorFakeStats(item);
  const network = item.network ? escapeHtml(String(item.network)) : '';
  const showWas = s.disc > 0 && s.base;
  // Portrait box art is shown as a contained poster inside the card (a left
  // column beside the copy) rather than the right-to-left bleed/fade used for
  // landscape key art, which would crop a tall cover to a sliver.
  const portrait = !!item.portrait && !!coverUrl;
  const artLayers = coverUrl && !portrait
    ? `<img class="sponsored-feature-art-bg" src="${escapeAttr(coverUrl)}" alt="" aria-hidden="true" loading="lazy" onerror="this.style.display='none'" />
      <img class="sponsored-feature-art" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />
      <span class="sponsored-feature-fade" aria-hidden="true"></span>`
    : '';
  const poster = portrait
    ? `<span class="sponsored-feature-poster" aria-hidden="true"><img class="sponsored-feature-poster-img" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.closest('.sponsored-feature-poster').style.display='none'" /></span>`
    : '';
  const bannerCls = banner ? ' sponsored-feature-card--banner' : '';
  const portraitCls = portrait ? ' sponsored-feature-card--portrait' : '';
  const noArtCls = coverUrl ? '' : ' no-art';
  const body = `<div class="sponsored-feature-body">
      <div class="sponsored-feature-head">
        <span class="dash-kpi-label">Featured</span>
      </div>
      <div class="sponsored-feature-hero">
        <div class="sponsored-feature-title">${escapeHtml(item.title)}</div>
        ${item.tagline ? `<p class="sponsored-feature-blurb">${escapeHtml(item.tagline)}</p>` : ''}
        <div class="sponsored-feature-priceline">
          <span class="sponsored-feature-cut">-${s.disc}%</span>
          <span class="sponsored-feature-sale">$${s.sale}</span>
          ${showWas ? `<span class="sponsored-feature-was">$${s.base}</span>` : ''}
        </div>
      </div>
      <div class="sponsored-feature-panel">
        <div class="sponsored-feature-stats">
          ${sponsoredFeatureStatsHtml(s)}
        </div>
      </div>
      <div class="sponsored-feature-detail">
        <span class="sponsored-feature-genre">${escapeHtml(s.genres)}</span>
        ${network ? `<span class="sponsored-feature-by">${network}</span>` : ''}
      </div>
      <span class="sponsored-feature-cta">${escapeHtml(cta)} &rarr;</span>
    </div>`;
  const inner = portrait
    ? `<div class="sponsored-feature-layout">${poster}${body}</div>`
    : `${artLayers}${body}`;
  return `<button type="button"
    class="dash-card sponsored-feature-card${noArtCls}${bannerCls}${portraitCls}${sponsorHouseClass(item)} text-left w-full"
    ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
    ${sponsorBadgeHtml(item, 'sponsored-badge--inline')}
    ${inner}
    ${sponsorDismissHtml(item)}
  </button>`;
}

/** Full "card ad" for the dashboard dash-picks slot (tall layout). */
export function sponsoredDashPicksCardHtml(item) {
  if (!item) return '';
  noteSponsoredImpression('dash-pick', item.id);
  if (isBundleFeatureAd(item)) {
    return sponsoredFeatureBundleAdHtml(item, { banner: false });
  }
  return sponsoredFeatureAdHtml(item, { banner: false });
}

/**
 * Same content-rich feature ad as the dash-picks card, laid out as a full-width
 * horizontal banner. Used for the standalone slot wedged between dashboard
 * charts (placement: dash-feature-banner).
 */
export function sponsoredFeatureBannerHtml(item) {
  if (!item) return '';
  noteSponsoredImpression('dash-feature-banner', item.id);
  return sponsoredFeatureAdHtml(item, { banner: true });
}

/**
 * Claimable-area sponsor slot. Renders the content-rich "feature" ad (cover-art
 * bleed, price line, stat chips, genre/network detail) wrapped in a
 * one-third-width column so it reads as a fleshed-out banner beside the
 * Claimable Now card rather than a flat full-width strip.
 */
export function sponsoredClaimCardHtml(item) {
  if (!item) return '';
  noteSponsoredImpression('claim-cards', item.id);
  return `<div class="sponsored-claim-feature">${sponsoredFeatureAdHtml(item)}</div>`;
}

/** Premium spotlight color schemes (theme-independent). Sync pair: app.css .dash-spotlight--scheme-* */
export const SPOTLIGHT_PREMIUM_SCHEMES = ['ember', 'sapphire', 'emerald'];

/** Synthetic spotlight slide from a sponsor feed item. */
export function sponsorToSpotlightGame(item) {
  if (item?.id) noteSponsoredImpression('dash-spotlight', item.id);
  const cover = sponsorCoverUrl(item.cover);
  const isHouse = String(item?.kind || '').toLowerCase() === 'house';
  const disclosure = sponsorDisclosure(item);
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  const artMode = String(item.art_mode || '').toLowerCase() === 'logo' ? 'logo' : '';
  const schemeRaw = String(item.scheme || '').toLowerCase();
  const scheme = SPOTLIGHT_PREMIUM_SCHEMES.includes(schemeRaw) ? schemeRaw : '';
  const slogan = item.slogan ? String(item.slogan) : '';
  return {
    store: 'sponsored',
    id: item.id,
    name: item.title,
    header_image: cover,
    library_image: cover,
    _spotlightArtMode: artMode,
    _spotlightReason: {
      eyebrow: isHouse ? 'BAKLOG Pro' : disclosure,
      score: 100 - (item.priority ?? 50),
      metaParts: tagline ? [tagline] : [],
      slogan,
      isSponsored: true,
    },
    _spotlightAd: {
      id: item.id,
      url: item.url,
      disclosure,
      kind: item.kind,
      cta: item.cta || '',
      artMode,
      scheme,
      slogan,
    },
  };
}

/** Location keys to re-render after dismissing a sponsor. */
export function locationsForDismissRefresh(sponsorId) {
  if (!sponsorId) return [...AD_LOCATIONS];
  const locs = locationsForAdId(sponsorId);
  return locs.length ? locs : [...AD_LOCATIONS];
}

/** @deprecated */
export function placementsForDismissRefresh(sponsorId) {
  return locationsForDismissRefresh(sponsorId);
}

function refreshJobsForLocation(loc, sponsorId, { skipTableRow = false } = {}) {
  const jobs = [];
  if (loc.startsWith('dash-') && loc !== 'dash-house') {
    if (loc === 'dash-spotlight') {
      jobs.push(import('./dashboard.js').then(m => m.refreshSpotlightAfterSponsorChange?.()));
    } else if (loc === 'dash-versus-rated' || loc === 'dash-versus-fast') {
      jobs.push(import('./dashboard.js').then(m => m.refreshPicksVersusAfterSponsorChange?.()));
    } else if (loc === 'dash-coop-online' || loc === 'dash-coop-couch') {
      jobs.push(import('./dashboard.js').then(m => m.refreshCoopSpotlightAfterSponsorChange?.(sponsorId)));
    } else {
      jobs.push(import('./dashboard-cards.js').then(m => {
        if (loc === 'dash-pick') m.renderDashboardSponsoredPick?.();
        if (loc === 'dash-feature-banner') m.renderDashboardFeatureBanner?.();
      }));
    }
  }
  if (loc === 'dash-house' || loc === 'wish-house' || loc.startsWith('wish-deal')) {
    jobs.push(import('./dashboard-cards.js').then(m => m.renderDashboardWishlistStats()));
  }
  if (loc === 'dash-house') {
    jobs.push(import('./dashboard-cards.js').then(m => m.renderDashboardHouseSlot?.()));
  }
  if (loc === 'lib-house' || loc === 'itch-house' || loc === 'wish-house') {
    jobs.push(import('./picks-ui.js').then(m => m.renderViewHouseSlot?.()));
  }
  if ((loc.endsWith('-pick') || loc.endsWith('-row')) && !loc.includes('versus')) {
    if (loc.endsWith('-pick')) jobs.push(import('./picks-ui.js').then(m => m.renderPicks()));
    if (loc.endsWith('-row') && !skipTableRow) {
      jobs.push(import('./table-ui.js').then(m => {
        if (state.activeView === 'library' || state.activeView === 'wishlist' || state.activeView === 'itch') {
          return m.renderTable({ force: true });
        }
      }));
    }
  }
  if (loc === 'claim-cards') {
    jobs.push(import('./claimable.js').then(m => m.renderClaimableModule()));
  }
  return jobs;
}

/**
 * Re-render only the surfaces that showed the dismissed sponsor.
 * @param {string} sponsorId
 * @param {{ skipTableRow?: boolean }} [opts] skipTableRow: the caller already
 *   swapped the row ad in place (syncSponsoredTableAfterDismiss), so skip the
 *   full table re-render that would otherwise re-rotate the slot and flicker.
 */
export function refreshSponsoredSurfaces(sponsorId, { skipTableRow = false } = {}) {
  const locations = new Set(locationsForDismissRefresh(sponsorId));
  const jobs = [];
  for (const loc of locations) {
    jobs.push(...refreshJobsForLocation(loc, sponsorId, { skipTableRow }));
  }
  return Promise.all(jobs);
}
