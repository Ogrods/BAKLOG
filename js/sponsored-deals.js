/**
 * Sponsored / house deal slot for the wishlist deal rail.
 *
 * Honest by design: every sponsored slot carries a visible "Sponsored" (or
 * "House") disclosure, is ownership-aware (a slot whose `match_title` you
 * already own is skipped), and can be dismissed. The slot is part of the free
 * tier; the planned paid tier removes it via `prefs.hideSponsoredDeals`.
 *
 * Feed shape (sponsors.json / curated/sponsors.json):
 *   { version, generated_at, items: [{ id, kind, title, tagline, cta, url,
 *     cover, match_title?, priority?, enabled?, starts?, ends? }] }
 *   kind: "house" -> "House" disclosure; anything else -> "Sponsored".
 */
import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { normalizeNameForDedup } from './game-core.js';
import { isOwnedByTitle } from './deals.js';
import { savePersonal } from './personal-storage.js';
import { dataFetch } from './api-client.js';

const SPONSORS_LOCAL_PATH = 'sponsors.json';
const SPONSORS_FALLBACK_PATH = 'curated/sponsors.json';

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
  } catch {
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

/**
 * Highest-priority eligible sponsored slot, or null. Eligible = enabled, inside
 * its date window, not dismissed, and (when it names a game) not already owned.
 */
export function getEligibleSponsoredDeal() {
  if (state.prefs?.hideSponsoredDeals) return null;
  const now = Date.now();
  const eligible = (state.sponsoredDeals || []).filter(item => {
    if (item.enabled === false) return false;
    if (isDismissed(item.id)) return false;
    if (!withinWindow(item, now)) return false;
    if (item.match_title) {
      const norm = normalizeNameForDedup(item.match_title);
      if (norm && (isOwnedByTitle(item.match_title) || state.ownedNormNames?.has(norm))) return false;
    }
    return true;
  });
  if (!eligible.length) return null;
  eligible.sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99));
  return eligible[0];
}

export function sponsoredDealCardHtml(item) {
  if (!item) return '';
  const isHouse = String(item.kind || '').toLowerCase() === 'house';
  const disclosure = isHouse ? 'House' : 'Sponsored';
  const discTitle = isHouse
    ? 'House promotion from BAKLOG (not a paid placement)'
    : 'Paid placement. Disclosed sponsored slot — funds the free tier.';
  const cta = item.cta || 'Learn more';
  const tagline = item.tagline ? `<div class="sponsored-deal-tagline">${escapeHtml(item.tagline)}</div>` : '';
  const cover = item.cover
    ? `<img class="sponsored-deal-cover" src="${escapeAttr(item.cover)}" alt="" loading="lazy" onerror="this.style.display='none'" />`
    : '';
  const url = item.url ? escapeAttr(item.url) : '';
  return `<button type="button"
    class="deal-card-clickable dash-card deal-rail-card sponsored-deal-card${isHouse ? ' sponsored-deal-house' : ''} text-left w-full"
    data-action="sponsored-deal"
    data-sponsor-id="${escapeAttr(item.id)}"
    data-sponsor-url="${url}"
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
    <span class="sponsored-deal-dismiss" role="button" tabindex="0" data-action="sponsored-dismiss" data-sponsor-id="${escapeAttr(item.id)}" title="Dismiss this slot" aria-label="Dismiss sponsored slot">&times;</span>
  </button>`;
}

/** Markup for the eligible sponsored slot, or "" when none should show. */
export function sponsoredDealSlotHtml() {
  const item = getEligibleSponsoredDeal();
  return item ? sponsoredDealCardHtml(item) : '';
}
