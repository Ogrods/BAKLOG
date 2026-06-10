/**
 * Sponsored / house deal slots across the dashboard and library surfaces.
 *
 * Honest by design: every sponsored slot carries a visible "Sponsored" (or
 * "House") disclosure, is ownership-aware (a slot whose `match_title` you
 * already own is skipped), and can be dismissed. The slot is part of the free
 * tier; the paid (pro) tier removes it via the server-resolved entitlement
 * (`isPro()`). There is no free-tier ad opt-out — paying is the only way to
 * remove sponsored slots.
 *
 * Feed shape (sponsors.json / curated/sponsors.json):
 *   { version, generated_at, items: [{ id, kind, title, tagline, cta, url,
 *     cover?, match_title?, priority?, enabled?, starts?, ends?, placements? }] }
 *   kind: "house" -> "House" disclosure; anything else -> "Sponsored".
 *   placements: comma string or list — deal-rail, dash-deal-rail, spotlight, picks, table,
 *     dash-picks, dash-versus, coop-online, coop-couch, claimable (default deal-rail).
 */
import { state } from './state.js';
import { escapeHtml, escapeAttr, isSafeHttpUrl } from './dom-util.js';
import { normalizeNameForDedup } from './game-core.js';
import { isOwnedByTitle } from './deals.js';
import { dataFetch } from './api-client.js';
import { isPro } from './auth-gate.js';
import { noteSponsoredImpression } from './anon-metrics.js';

const SPONSORS_LOCAL_PATH = 'sponsors.json';
const SPONSORS_FALLBACK_PATH = 'curated/sponsors.json';
export const SPONSORS_HOSTED_URL = 'https://baklog.app/sponsors.json';
const SPONSORS_REMOTE_TIMEOUT_MS = 3000;

export function getSponsorsEndpoint() {
  return (document.querySelector('meta[name="baklog-sponsors-endpoint"]')?.content)
    || window.__BAKLOG_SPONSORS_ENDPOINT
    || SPONSORS_HOSTED_URL;
}

export const SPONSOR_PLACEMENTS = [
  'deal-rail',
  'dash-deal-rail',
  'spotlight',
  'picks',
  'table',
  'dash-picks',
  'dash-feature-banner',
  'dash-versus',
  'coop-online',
  'coop-couch',
  'claimable',
];

const SPONSOR_PLACEMENT_SET = new Set(SPONSOR_PLACEMENTS);

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

export async function loadSponsoredDeals() {
  let doc = await fetchJson(SPONSORS_LOCAL_PATH);
  if (doc?.items?.length) {
    state.sponsoredDeals = normalizeSponsorsItems(doc);
    return state.sponsoredDeals;
  }
  doc = await fetchHostedSponsors();
  if (doc?.items?.length) {
    state.sponsoredDeals = normalizeSponsorsItems(doc);
    return state.sponsoredDeals;
  }
  doc = await fetchJson(SPONSORS_FALLBACK_PATH);
  state.sponsoredDeals = normalizeSponsorsItems(doc);
  return state.sponsoredDeals;
}

export function itemPlacements(item) {
  const raw = item?.placements;
  if (raw == null || raw === '') return ['deal-rail'];
  const list = Array.isArray(raw) ? raw : String(raw).split(',');
  const parsed = list.map(s => String(s).trim().toLowerCase()).filter(Boolean);
  const valid = parsed.filter(p => SPONSOR_PLACEMENT_SET.has(p));
  return valid.length ? valid : ['deal-rail'];
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
    : 'Paid placement. Disclosed sponsored slot — funds the free tier.';
}

function sponsorHouseClass(item) {
  return String(item?.kind || '').toLowerCase() === 'house' ? ' sponsored-deal-house' : '';
}

function sponsorActionAttrs(item, { house } = {}) {
  const url = isSafeHttpUrl(item.url) ? escapeAttr(item.url) : '';
  const isHouse = house ?? String(item?.kind || '').toLowerCase() === 'house';
  const houseAttr = isHouse ? ' data-sponsor-house="1"' : '';
  return `data-action="sponsored-deal" data-sponsor-id="${escapeAttr(item.id)}" data-sponsor-url="${url}"${houseAttr}`;
}

function sponsorDismissHtml(item) {
  return `<span class="sponsored-deal-dismiss" role="button" tabindex="0" data-action="sponsored-dismiss" data-sponsor-id="${escapeAttr(item.id)}" title="Dismiss this slot" aria-label="Dismiss sponsored slot">&times;</span>`;
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
 * Eligible sponsored items for a placement, sorted by priority (lower first).
 */
export function getEligibleSponsors(placement) {
  if (isPro()) return [];
  const want = String(placement || 'deal-rail').toLowerCase();
  const now = Date.now();
  const eligible = (state.sponsoredDeals || []).filter(item => {
    if (item.enabled === false) return false;
    if (isDismissed(item.id)) return false;
    if (!withinWindow(item, now)) return false;
    if (!itemPlacements(item).includes(want)) return false;
    if (item.match_title) {
      const norm = normalizeNameForDedup(item.match_title);
      if (norm && (isOwnedByTitle(item.match_title) || state.ownedNormNames?.has(norm))) return false;
    }
    return true;
  });
  eligible.sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99));
  return eligible;
}

/** Highest-priority eligible deal-rail slot, or null. */
export function getEligibleSponsoredDeal() {
  const list = getEligibleSponsors('deal-rail');
  return list[0] || null;
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
  const now = Date.now();
  const candidates = (state.sponsoredDeals || []).filter(item => {
    if (item.enabled === false) return false;
    if (!withinWindow(item, now)) return false;
    if (!itemPlacements(item).includes('dash-versus')) return false;
    if (item.match_title) {
      const norm = normalizeNameForDedup(item.match_title);
      if (norm && (isOwnedByTitle(item.match_title) || state.ownedNormNames?.has(norm))) return false;
    }
    return true;
  });
  candidates.sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99));
  const ratedItem = candidates[0] || null;
  const fastItem = candidates[1] || null;
  return {
    rated: ratedItem && !isDismissed(ratedItem.id) ? ratedItem : null,
    fast: fastItem && !isDismissed(fastItem.id) ? fastItem : null,
    ratedReserved: !!ratedItem,
    fastReserved: !!fastItem,
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

// Promo columns for the house banner — info-rich pitch pulled from the landing
// copy so the in-app message stays in sync with baklog.app. Each fills one of
// the three feature columns that span the full-width deal-radar row.
// Sync pair: HOUSE_BANNER_FEATURES ↔ landing/index.html trust + hero pillars.
const HOUSE_BANNER_FEATURES = [
  {
    title: 'Local-first',
    desc: 'Your library never leaves your machine. Nothing to breach, sell, or subpoena.',
  },
  {
    title: 'Every store, one list',
    desc: '12 libraries and 8 wishlists, deduped across Steam, Epic, GOG, and more.',
  },
  {
    title: 'Open & honest',
    desc: 'No telemetry. Full source on GitHub (MIT) — audit every line.',
  },
];

// Homepage Pro upsell — pulled from landing/index.html paid-tier copy.
// Sync pair: PRO_PROMO ↔ landing/index.html paid tier + FAQ pricing answers.
const PRO_PROMO = {
  label: 'BAKLOG Pro',
  title: 'Power-user conveniences',
  price: '$5/mo ($50/yr) — planned',
  tagline: 'Nothing you use today moves behind paywall. The optional tier layers on bulk refresh, sync, and fewer distractions.',
  cta: "$5/mo — see what's planned",
  url: 'https://baklog.app/',
  features: [
    {
      title: 'Queued bulk refresh',
      desc: 'Queue every stale store at once and let them refresh back-to-back instead of one at a time.',
    },
    {
      title: 'Cloud sync',
      desc: 'Keep your library and personal data aligned across machines without manual exports.',
    },
    {
      title: 'No sponsored cards',
      desc: 'Paid tier drops sponsored deal slots so your deal radar stays yours.',
    },
  ],
};

/** Hard-coded wishlist deal-rail house banner (not driven by sponsors.json). */
export const HOUSE_DEAL_ITEM = {
  id: 'house-support-baklog',
  kind: 'house',
  title: 'Back BAKLOG',
  tagline: 'Local-first, no server to breach. Help fund development.',
  cta: 'Join the waitlist',
  url: 'https://baklog.app/#waitlist',
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
export function houseDealBannerHtml(item) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = item.cta || 'Learn more';
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
    class="dash-card deal-rail-card sponsored-deal-card sponsored-deal-house sponsored-deal-banner text-left w-full"
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
    ${sponsorDismissHtml(item)}
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
  const discTitle = 'House promotion from BAKLOG — optional paid tier (planned)';
  const title = item.title || PRO_PROMO.title;
  const taglineText = item.tagline ?? PRO_PROMO.tagline;
  const cta = item.cta || PRO_PROMO.cta;
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
            <span class="sponsored-badge sponsored-badge--inline" title="${escapeAttr(discTitle)}">Planned</span>
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

/** Markup for the hard-coded dash-deal-rail Pro upsell, or "" when none should show. */
export function proPromoSlotHtml() {
  if (isPro()) return '';
  return proPromoBannerHtml(PRO_PROMO_ITEM);
}

export function sponsoredDealCardHtml(item) {
  if (!item) return '';
  if (String(item.kind || '').toLowerCase() === 'house') {
    return houseDealBannerHtml(item);
  }
  const discTitle = sponsorDiscTitle(item);
  const cta = item.cta || 'Learn more';
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

/** Markup for the hard-coded wishlist deal-rail house banner, or "" when hidden. */
export function sponsoredDealSlotHtml() {
  if (isPro() || isDismissed(HOUSE_DEAL_ITEM.id)) return '';
  return houseDealBannerHtml(HOUSE_DEAL_ITEM);
}

export function sponsoredPickCardHtml(item) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = item.cta || 'Learn more';
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

export function sponsoredPickSlotHtml() {
  const item = getEligibleSponsors('picks')[0];
  return item ? sponsoredPickCardHtml(item) : '';
}

/** Wishlist-deals picks tab: mirror dealCardHtml's 3-row info block. */
export function sponsoredDealPickCardHtml(item) {
  if (!item) return '';
  const discTitle = sponsorDiscTitle(item);
  const cta = item.cta || 'Learn more';
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

export function sponsoredDealPickSlotHtml() {
  const item = getEligibleSponsors('picks')[0];
  if (item) noteSponsoredImpression('picks', item.id);
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
  const sale = (baseNum * (1 - disc / 100)).toFixed(2);
  const base = baseNum.toFixed(2);
  const score = (steam / Math.log2(hltb + 2)).toFixed(1);
  const genres = item.genres
    ? (Array.isArray(item.genres) ? item.genres.join(', ') : String(item.genres))
    : SPONSOR_FAKE_GENRES[seed % SPONSOR_FAKE_GENRES.length];
  return { steam, mc, hltb, year, disc, sale, base, score, genres };
}

const SP_DASH = '<span class="text-slate-600">-</span>';

export function sponsoredTableRowHtml(item, { isWish } = {}) {
  if (!item) return '';
  noteSponsoredImpression('table', item.id);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  const cta = item.cta || 'Learn more';
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
export function sponsoredVersusRowHtml(item, { metric = 'rating' } = {}) {
  if (!item) return '';
  noteSponsoredImpression('dash-versus', item.id);
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
export function sponsoredCoopPickRowHtml(item) {
  if (!item) return '';
  noteSponsoredImpression(itemPlacements(item)[0] || 'coop-online', item.id);
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
  const cta = item.cta || 'Learn more';
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
  noteSponsoredImpression('dash-picks', item.id);
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
  noteSponsoredImpression('claimable', item.id);
  return `<div class="sponsored-claim-feature">${sponsoredFeatureAdHtml(item)}</div>`;
}

/** Synthetic spotlight slide from a sponsor feed item. */
export function sponsorToSpotlightGame(item) {
  if (item?.id) noteSponsoredImpression('spotlight', item.id);
  const cover = sponsorCoverUrl(item.cover);
  const isHouse = String(item?.kind || '').toLowerCase() === 'house';
  const disclosure = sponsorDisclosure(item);
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  return {
    store: 'sponsored',
    id: item.id,
    name: item.title,
    header_image: cover,
    library_image: cover,
    _spotlightReason: {
      eyebrow: isHouse ? 'Featured' : disclosure,
      score: 100 - (item.priority ?? 50),
      metaParts: tagline ? [tagline] : [],
      isSponsored: true,
    },
    _spotlightAd: {
      id: item.id,
      url: item.url,
      disclosure,
      kind: item.kind,
    },
  };
}

/** Placements to re-render after dismissing a sponsor (all surfaces when id unknown). */
export function placementsForDismissRefresh(sponsorId) {
  if (!sponsorId) return [...SPONSOR_PLACEMENTS];
  if (sponsorId === HOUSE_DEAL_ITEM.id) return ['deal-rail'];
  const item = (state.sponsoredDeals || []).find(it => it.id === sponsorId);
  if (!item) return [...SPONSOR_PLACEMENTS];
  return itemPlacements(item);
}

/** Re-render only the surfaces that showed the dismissed sponsor. */
export function refreshSponsoredSurfaces(sponsorId) {
  const placements = new Set(placementsForDismissRefresh(sponsorId));
  const jobs = [];
  if (placements.has('deal-rail') || placements.has('dash-deal-rail') || placements.has('dash-picks') || placements.has('dash-feature-banner')) {
    jobs.push(import('./dashboard-cards.js').then(m => {
      if (placements.has('deal-rail') || placements.has('dash-deal-rail')) {
        m.renderDashboardWishlistStats();
      }
      if (placements.has('dash-picks')) m.renderDashboardSponsoredPick?.();
      if (placements.has('dash-feature-banner')) m.renderDashboardFeatureBanner?.();
    }));
  }
  if (placements.has('picks')) {
    jobs.push(import('./picks-ui.js').then(m => m.renderPicks()));
  }
  if (placements.has('claimable')) {
    jobs.push(import('./claimable.js').then(m => m.renderClaimableModule()));
  }
  if (placements.has('table')) {
    jobs.push(import('./table-ui.js').then(m => {
      // Click handler already removed the row synchronously; idempotent fallback
      // for programmatic dismiss + bust virtual-window cache (no full re-query).
      if (state.activeView === 'library' || state.activeView === 'wishlist') {
        m.syncSponsoredTableAfterDismiss();
      }
    }));
  }
  if (placements.has('spotlight')) {
    jobs.push(import('./dashboard.js').then(m => m.refreshSpotlightAfterSponsorChange?.()));
  }
  if (placements.has('dash-versus')) {
    jobs.push(import('./dashboard.js').then(m => m.refreshPicksVersusAfterSponsorChange?.()));
  }
  if (placements.has('coop-online') || placements.has('coop-couch')) {
    jobs.push(import('./dashboard.js').then(m => m.refreshCoopSpotlightAfterSponsorChange?.(sponsorId)));
  }
  return Promise.all(jobs);
}
