/**
 * Sponsored / house deal slots across the dashboard and library surfaces.
 *
 * Honest by design: every sponsored slot carries a visible "Sponsored" (or
 * "House") disclosure, is ownership-aware (a slot whose `match_title` you
 * already own is skipped), and can be dismissed. The slot is part of the free
 * tier; the paid (pro) tier removes it via the server-resolved entitlement
 * (`isPro()`), and the free `prefs.hideSponsoredDeals` toggle still hides it.
 *
 * Feed shape (sponsors.json / curated/sponsors.json):
 *   { version, generated_at, items: [{ id, kind, title, tagline, cta, url,
 *     cover?, match_title?, priority?, enabled?, starts?, ends?, placements? }] }
 *   kind: "house" -> "House" disclosure; anything else -> "Sponsored".
 *   placements: comma string or list — deal-rail, spotlight, picks, table,
 *     dash-picks, claimable (default deal-rail).
 */
import { state } from './state.js';
import { escapeHtml, escapeAttr, isSafeHttpUrl } from './dom-util.js';
import { normalizeNameForDedup } from './game-core.js';
import { isOwnedByTitle } from './deals.js';
import { savePersonal } from './personal-storage.js';
import { dataFetch } from './api-client.js';
import { isPro } from './auth-gate.js';

const SPONSORS_LOCAL_PATH = 'sponsors.json';
const SPONSORS_FALLBACK_PATH = 'curated/sponsors.json';

export const SPONSOR_PLACEMENTS = [
  'deal-rail',
  'spotlight',
  'picks',
  'table',
  'dash-picks',
  'claimable',
];

const SPONSOR_PLACEMENT_SET = new Set(SPONSOR_PLACEMENTS);

function dismissedSponsorsMap() {
  const m = state.personal.__dismissedSponsors;
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {};
}

export function dismissSponsoredDeal(id) {
  if (!id) return;
  if (!state.personal.__dismissedSponsors) state.personal.__dismissedSponsors = {};
  state.personal.__dismissedSponsors[id] = Date.now();
  savePersonal();
}

function isDismissed(id) {
  return Boolean(dismissedSponsorsMap()[id]);
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

export async function loadSponsoredDeals() {
  let doc = await fetchJson(SPONSORS_LOCAL_PATH);
  if (!doc?.items?.length) {
    doc = await fetchJson(SPONSORS_FALLBACK_PATH);
  }
  const items = Array.isArray(doc?.items) ? doc.items : [];
  state.sponsoredDeals = items.filter(it => it && typeof it === 'object' && it.id && it.title);
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

function sponsorActionAttrs(item) {
  const url = isSafeHttpUrl(item.url) ? escapeAttr(item.url) : '';
  return `data-action="sponsored-deal" data-sponsor-id="${escapeAttr(item.id)}" data-sponsor-url="${url}"`;
}

function sponsorDismissHtml(item) {
  return `<span class="sponsored-deal-dismiss" role="button" tabindex="0" data-action="sponsored-dismiss" data-sponsor-id="${escapeAttr(item.id)}" title="Dismiss this slot" aria-label="Dismiss sponsored slot">&times;</span>`;
}

/**
 * Eligible sponsored items for a placement, sorted by priority (lower first).
 */
export function getEligibleSponsors(placement) {
  if (isPro() || state.prefs?.hideSponsoredDeals) return [];
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

export function sponsoredDealCardHtml(item) {
  if (!item) return '';
  const disclosure = sponsorDisclosure(item);
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
      <span class="sponsored-badge" title="${escapeAttr(discTitle)}">${disclosure}</span>
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

/** Markup for the eligible deal-rail slot, or "" when none should show. */
export function sponsoredDealSlotHtml() {
  const item = getEligibleSponsoredDeal();
  return item ? sponsoredDealCardHtml(item) : '';
}

export function sponsoredPickCardHtml(item) {
  if (!item) return '';
  const disclosure = sponsorDisclosure(item);
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
    <span class="sponsored-badge sponsored-pick-badge" title="${escapeAttr(discTitle)}">${disclosure}</span>
    <div class="cover-wrap w-full block${ls}">${coverHtml}</div>
    <div class="text-xs text-slate-200 mt-1 truncate font-medium">${escapeHtml(item.title)}</div>
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

export function sponsoredTableRowHtml(item, { isWish } = {}) {
  if (!item) return '';
  const disclosure = sponsorDisclosure(item);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  const cta = item.cta || 'Learn more';
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  return `<tr class="sponsored-table-row${sponsorHouseClass(item)}" data-sponsored-row="1">
    <td class="col-select p-2 text-center" aria-hidden="true"></td>
    <td class="col-cover p-2">${coverHtml ? `<span class="cover-wrap">${coverHtml}</span>` : ''}</td>
    <td class="col-game p-2 game-name-cell" colspan="12">
      <button type="button" class="sponsored-table-body text-left w-full${sponsorHouseClass(item)}"
        ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
        <span class="sponsored-badge sponsored-table-badge">${disclosure}</span>
        <span class="sponsored-table-title">${escapeHtml(item.title)}</span>
        ${tagline ? `<span class="sponsored-table-tagline">${tagline}</span>` : ''}
        <span class="sponsored-deal-cta">${escapeHtml(cta)} &rarr;</span>
        ${sponsorDismissHtml(item)}
      </button>
    </td>
  </tr>`;
}

export function sponsoredDashPicksCardHtml(item) {
  if (!item) return '';
  const disclosure = sponsorDisclosure(item);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const coverHtml = coverUrl
    ? `<img class="dash-list-cover" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  const cta = item.cta || 'Learn more';
  return `<div class="dash-card sponsored-dash-picks-card${sponsorHouseClass(item)}">
    <div class="sponsored-deal-head mb-2">
      <h3 class="text-sm font-semibold text-slate-200">Featured</h3>
      <span class="sponsored-badge sponsored-badge--inline" title="${escapeAttr(discTitle)}">${disclosure}</span>
    </div>
    <button type="button" class="sponsored-dash-picks-body text-left w-full"
      ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
      ${coverHtml}
      <div class="sponsored-deal-meta min-w-0 flex-1 mt-2">
        <div class="sponsored-deal-name">${escapeHtml(item.title)}</div>
        ${item.tagline ? `<div class="sponsored-deal-tagline">${escapeHtml(item.tagline)}</div>` : ''}
        <span class="sponsored-deal-cta">${escapeHtml(cta)} &rarr;</span>
      </div>
      ${sponsorDismissHtml(item)}
    </button>
  </div>`;
}

export function sponsoredClaimCardHtml(item) {
  if (!item) return '';
  const disclosure = sponsorDisclosure(item);
  const discTitle = sponsorDiscTitle(item);
  const coverUrl = sponsorCoverUrl(item.cover);
  const ls = coverUrl ? window.coverLandscapeAttr?.(coverUrl) || '' : '';
  const coverHtml = coverUrl
    ? `<img class="deal-hero-cover${ls}" src="${escapeAttr(coverUrl)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : `<span class="deal-hero-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  const cta = item.cta || 'Learn more';
  return `<article class="claim-hero-card dash-card deal-rail-card sponsored-claim-card w-full${sponsorHouseClass(item)}">
    <div class="sponsored-deal-head">
      <span class="dash-kpi-label">Featured</span>
      <span class="sponsored-badge sponsored-badge--inline" title="${escapeAttr(discTitle)}">${disclosure}</span>
    </div>
    <button type="button" class="deal-hero-body mt-2 text-left w-full sponsored-claim-body"
      ${sponsorActionAttrs(item)} title="${escapeAttr(discTitle)}">
      <span class="cover-wrap deal-hero-cover-wrap${ls}">${coverHtml}</span>
      <div class="deal-hero-meta min-w-0 flex-1">
        <div class="deal-hero-name font-medium text-slate-100">${escapeHtml(item.title)}</div>
        ${item.tagline ? `<p class="claim-hero-blurb text-sm text-slate-400 mt-1">${escapeHtml(item.tagline)}</p>` : ''}
        <span class="sponsored-deal-cta mt-2 inline-block">${escapeHtml(cta)} &rarr;</span>
      </div>
      ${sponsorDismissHtml(item)}
    </button>
  </article>`;
}

/** Synthetic spotlight slide from a sponsor feed item. */
export function sponsorToSpotlightGame(item) {
  const cover = sponsorCoverUrl(item.cover);
  const disclosure = sponsorDisclosure(item);
  const tagline = item.tagline ? escapeHtml(item.tagline) : '';
  return {
    store: 'sponsored',
    id: item.id,
    name: item.title,
    header_image: cover,
    library_image: cover,
    _spotlightReason: {
      eyebrow: disclosure,
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

export function refreshSponsoredSurfaces() {
  import('./dashboard-cards.js').then(m => {
    m.renderDashboardWishlistStats();
    m.renderDashboardSponsoredPick?.();
  });
  import('./picks-ui.js').then(m => m.renderPicks());
  import('./claimable.js').then(m => m.renderClaimableModule());
  import('./table-ui.js').then(m => {
    if (state.activeView === 'library' || state.activeView === 'wishlist') m.renderTable();
  });
  import('./dashboard.js').then(m => m.refreshSpotlightAfterSponsorChange?.());
}
