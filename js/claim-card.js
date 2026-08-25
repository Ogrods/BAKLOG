/**
 * Pure, state-free rendering + dedupe/sort helpers for the "Claimable Now"
 * free-claims module. Shared by the live app (js/claimable.js) and the admin
 * console's publish preview iframe (admin/admin.js) so both render byte-for-byte
 * identical markup — there is no hand-mirrored copy to keep in sync.
 *
 * Nothing here touches `state` or the DOM; callers own visibility/ownership/
 * dismissal decisions and pass in the already-resolved claim list.
 *
 * Dedup semantics (intentional asymmetry with Python):
 * - `dedupeClaims` here collapses cross-source copies by appid/title for the
 *   user-facing wishlist module (lower CLAIM_SOURCE_RANK wins).
 * - `shared/free_claims_sources.dedup_claim_items_by_id` dedupes by feed id
 *   only and keeps cross-source title dupes so the admin console can DUPE-stamp.
 *
 * Sync pairs (update together):
 * - stripClaimTitleDecorations ↔ shared/steam_match.strip_giveaway_decorations
 * - CLAIM_SOURCE_RANK ↔ shared/free_claims_sources.SOURCE_PRECEDENCE
 * - sanitizeBlurb ↔ build_free_claims._clean_blurb
 */
import { escapeHtml, escapeAttr, isSafeHttpUrl } from './dom-util.js';
import {
  EPIC_MOBILE_STORE,
  hasValidClaimLinks,
  inferClaimUrlPlatform,
  isEpicMobileStore,
  missingClaimLinkFields,
  normalizeClaimUrls,
} from './claim-links.js';
import { normalizeNameForDedup } from './game-core.js';
import { storeLogoHtml, storeDisplayName } from './store-logos.js';
import { affiliateUrl } from './affiliate.js';
import { sortClaimsItems } from './claim-sort.js';

export {
  EPIC_MOBILE_STORE,
  hasValidClaimLinks,
  inferClaimUrlPlatform,
  isEpicMobileStore,
  missingClaimLinkFields,
  normalizeClaimUrls,
} from './claim-links.js';

/** Strip giveaway/store boilerplate from auto-sourced claim titles before ownership match. */
export function stripClaimTitleDecorations(title) {
  let t = String(title || '').trim();
  if (!t) return t;
  t = t.replace(/\s*\([^)]*\)\s*giveaway\s*$/i, '');
  t = t.replace(/\s+free\s+(at\s+egs\s+)?on\s+epic\s*games?\s*store.*$/i, '');
  t = t.replace(/\s+free\s+for\s+mobile\s+on\s+egs.*$/i, '');
  t = t.replace(/\s+in\s+game\s+(items?|currency\s+pack).*$/i, '');
  t = t.replace(/\s+free\s+on\s+(steam|itchio|itch\.io|gog|indiegala).*$/i, '');
  t = t.replace(/\s*-\s*free\s+on\s+indiegala.*$/i, '');
  t = t.replace(/\s+on\s+(steam|gog|itch\.?io|epic\s*games?\s*store)\s*$/i, '');
  t = t.replace(/\s+-\s+chapters?[\s\d,]+.*$/i, '');
  t = t.replace(/\s+giveaway\s*$/i, '');
  return t.trim();
}

// Lower rank wins when the same game shows up from multiple sources — mirrors
// SOURCE_PRECEDENCE in shared/free_claims_sources.py (a direct store offer over
// an aggregator listing).
export const CLAIM_SOURCE_RANK = { epic: 0, gamerpower: 1, itad: 2 };

export function claimDedupKey(c) {
  if (c.steam_appid != null && c.steam_appid !== '') {
    const base = `appid:${c.steam_appid}`;
    return isEpicMobileStore(c.store) ? `${base}:mobile` : base;
  }
  const norm = normalizeNameForDedup(stripClaimTitleDecorations(c.title || ''));
  if (!norm) return `id:${c.id}`;
  if (isEpicMobileStore(c.store)) return `title:${norm}:mobile`;
  return `title:${norm}`;
}

/** Collapse the same game arriving from multiple sources to one row. */
export function dedupeClaims(list) {
  const titleToAppid = new Map();
  for (const c of list) {
    if (c.steam_appid == null || c.steam_appid === '') continue;
    const titleNorm = normalizeNameForDedup(stripClaimTitleDecorations(c.title || ''));
    if (titleNorm) titleToAppid.set(titleNorm, c.steam_appid);
  }
  const best = new Map();
  for (const c of list) {
    let key = claimDedupKey(c);
    if (key.startsWith('title:') && (c.steam_appid == null || c.steam_appid === '')) {
      const appid = titleToAppid.get(key.slice(6));
      if (appid != null) key = `appid:${appid}`;
    }
    const cur = best.get(key);
    if (!cur) { best.set(key, c); continue; }
    const rank = CLAIM_SOURCE_RANK[String(c.source || '').toLowerCase()] ?? 99;
    const curRank = CLAIM_SOURCE_RANK[String(cur.source || '').toLowerCase()] ?? 99;
    if (rank < curRank) {
      best.set(key, c);
      continue;
    }
    if (rank > curRank) continue;
    // Equal source rank: prefer newer first_seen, else lower id as stable tiebreak.
    const seen = Date.parse(c.first_seen || '') || 0;
    const curSeen = Date.parse(cur.first_seen || '') || 0;
    if (seen > curSeen) {
      best.set(key, c);
      continue;
    }
    if (seen < curSeen) continue;
    if (String(c.id || '') < String(cur.id || '')) best.set(key, c);
  }
  return [...best.values()];
}

/** Newest first — matches admin Claims auto table default (first_seen desc). */
export function sortClaims(list) {
  return sortClaimsItems(list, 'newest');
}

/**
 * ITAD-sourced claims ship `blurb` as raw HTML (anchor tags + literal giveaway
 * URLs + "expires on … | go to giveaway" boilerplate). Escaping it for display
 * leaks that markup/URL as visible text, so strip tags, decode the handful of
 * entities ITAD emits, and drop the giveaway boilerplate before rendering.
 * Sync pair: build_free_claims._clean_blurb (published feed uses the Python copy).
 */
export function sanitizeBlurb(raw) {
  if (!raw) return '';
  let t = String(raw)
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#0*39;|&apos;/g, "'");
  t = t.replace(/\s*\|?\s*(unknown expiry|expires on[^|]*)\s*\|?\s*go to giveaway\s*/i, ' ');
  // ITAD blurbs sometimes leave a bare giveaway URL behind once the anchor tag
  // is stripped — drop any leftover http(s) link so it doesn't show as text.
  t = t.replace(/https?:\/\/\S+/gi, ' ');
  return t.replace(/\s+/g, ' ').trim();
}

/** Coerce a feed-supplied review percent to a safe integer, or null. */
export function reviewPercentValue(claim) {
  const n = Number(claim?.review_percent);
  if (!Number.isFinite(n)) return null;
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Safe cover URL from a claim, or '' when missing/unsafe scheme. */
export function claimCoverUrl(claim) {
  return isSafeHttpUrl(claim?.header_image) ? claim.header_image : '';
}

/** Steam header.jpg fallback for a claim with a known appid (portrait
 * library_600x900 art 404s for many older apps). '' when no appid. */
export function claimCoverFallback(claim) {
  const appid = String(claim?.steam_appid || '').trim();
  return appid
    ? `https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/${appid}/header.jpg`
    : '';
}

export function formatEndsAt(endsAt) {
  if (!endsAt) return null;
  const t = Date.parse(endsAt);
  if (!Number.isFinite(t)) return null;
  const d = new Date(t);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

const CLAIM_SOURCE_META = {
  epic: { label: 'Epic', url: 'https://store.epicgames.com/free-games' },
  gamerpower: { label: 'GamerPower', url: 'https://www.gamerpower.com/' },
  itad: { label: 'ITAD', url: 'https://isthereanydeal.com/' },
};

/** Per-claim "referenced via <provider>" badge — where the listing was sourced from. */
export function claimSourceHtml(source, { tag = 'span' } = {}) {
  const key = String(source || '').toLowerCase();
  const meta = CLAIM_SOURCE_META[key];
  if (!meta) return '';
  const label = escapeHtml(meta.label);
  const inner = (tag === 'a')
    ? `<a href="${escapeAttr(affiliateUrl(meta.url))}" target="_blank" rel="noopener noreferrer">${label}</a>`
    : label;
  return `<span class="claim-source" title="Referenced via ${label}">via ${inner}</span>`;
}

/** Render feed attribution credits (e.g. GamerPower.com API terms). */
export function claimAttributionHtml(attribution) {
  const items = (attribution || []).filter(Boolean);
  if (!items.length) return '';
  const parts = items.map((name) => {
    const label = escapeHtml(String(name));
    if (/gamerpower/i.test(name)) {
      return `<a href="https://www.gamerpower.com/" target="_blank" rel="noopener noreferrer">${label}</a>`;
    }
    return label;
  });
  const itad = '<a href="https://isthereanydeal.com/" target="_blank" rel="noopener noreferrer">ITAD</a>';
  return `<p class="claim-attribution">Giveaway data via ${parts.join(' · ')} and ${itad}</p>`;
}

function claimPremiumBadgeHtml(claim) {
  if (!claim?.premium_only) return '';
  return '<span class="claim-pro-badge deal-cut-badge" title="Pro-only bonus drop">Pro</span>';
}

const CLAIM_OPEN_BTN_CLASS = {
  hero: 'bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-3 py-1.5 rounded',
  row: 'bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-2.5 py-1 rounded',
};

/** Primary claim CTA(s) for list/hero cards (buttons; claimable.js handles clicks). */
export function claimPlatformButtonsHtml(claim, { variant = 'row' } = {}) {
  const id = escapeAttr(claim.id);
  const btnClass = CLAIM_OPEN_BTN_CLASS[variant] || CLAIM_OPEN_BTN_CLASS.row;
  if (isEpicMobileStore(claim.store)) {
    const urls = normalizeClaimUrls(claim.claim_urls);
    const parts = [];
    const iosLabel = variant === 'row' ? 'iOS' : 'Claim on iOS';
    const androidLabel = variant === 'row' ? 'Android' : 'Claim on Android';
    if (urls.ios) {
      parts.push(
        `<button type="button" class="btn-claim-open btn-claim-open--ios ${btnClass}" data-claim-go-ios="${id}" aria-label="Claim on iOS">${iosLabel}</button>`,
      );
    }
    if (urls.android) {
      parts.push(
        `<button type="button" class="btn-claim-open btn-claim-open--android ${btnClass}" data-claim-go-android="${id}" aria-label="Claim on Android">${androidLabel}</button>`,
      );
    }
    return parts.join('');
  }
  return `<button type="button" class="btn-claim-open ${btnClass}" data-claim-go="${id}">Claim free →</button>`;
}

function claimDetailClaimActionsHtml(claim, owned) {
  if (owned) {
    return '<p class="claim-detail-owned">Already in your library.</p>';
  }
  if (isEpicMobileStore(claim.store)) {
    const urls = normalizeClaimUrls(claim.claim_urls);
    const parts = [];
    if (urls.ios) {
      const href = escapeAttr(affiliateUrl(urls.ios));
      parts.push(
        `<a href="${href}" target="_blank" rel="noopener noreferrer" class="claim-detail-claim-btn claim-detail-claim-btn--ios">Claim on iOS</a>`,
      );
    }
    if (urls.android) {
      const href = escapeAttr(affiliateUrl(urls.android));
      parts.push(
        `<a href="${href}" target="_blank" rel="noopener noreferrer" class="claim-detail-claim-btn claim-detail-claim-btn--android">Claim on Android</a>`,
      );
    }
    if (!parts.length) {
      return '<p class="claim-detail-owned">Claim link unavailable.</p>';
    }
    return `<div class="claim-detail-platform-actions">${parts.join('')}</div>`;
  }
  const claimable = isSafeHttpUrl(claim.claim_url);
  if (!claimable) {
    return '<p class="claim-detail-owned">Claim link unavailable.</p>';
  }
  const claimHref = escapeAttr(affiliateUrl(claim.claim_url));
  return `<a href="${claimHref}" target="_blank" rel="noopener noreferrer" class="claim-detail-claim-btn">Claim free →</a>`;
}

export function claimCardHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claimCoverUrl(claim);
  const blurbText = sanitizeBlurb(claim.blurb);
  const blurb = blurbText ? `<p class="claim-hero-blurb text-sm text-slate-400 mt-1">${escapeHtml(blurbText)}</p>` : '';
  const reviewPct = reviewPercentValue(claim);
  const review = reviewPct != null
    ? `<span class="deal-hero-stat" title="Steam review score"><span class="deal-hero-stat-dot deal-hero-stat-dot-review"></span>${reviewPct}%</span>`
    : '';
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `<span class="text-xs text-amber-300/90">Ends ${escapeHtml(ends)}</span>` : '';
  const genres = (claim.genres || []).slice(0, 2).map(escapeHtml).join(' · ');
  const genreHtml = genres ? `<span class="deal-hero-genres">${genres}</span>` : '';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="deal-hero-cover${ls}" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(claimCoverFallback(claim))}" data-name="${escapeAttr(claim.title || '')}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />`
    : `<span class="deal-hero-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;

  return `<article class="claim-hero-card dash-card deal-rail-card claim-fire-card w-full" data-claim-id="${escapeAttr(claim.id)}">
    <div class="dash-kpi-label">Claimable Now</div>
    <div class="deal-hero-body mt-2">
      <span class="cover-wrap deal-hero-cover-wrap${ls}">${coverHtml}</span>
      <div class="deal-hero-meta min-w-0 flex-1">
        <div class="deal-hero-top">
          <div class="deal-hero-name font-medium text-slate-100">${title}</div>
          <div class="deal-hero-prices mt-1">
            <span class="deal-hero-price claim-free-label">Free to claim</span>
          </div>
        </div>
        <div class="deal-hero-badges flex flex-wrap items-center gap-1.5 mt-1">
          <span class="deal-cut-badge deal-cut-huge claim-cut-fire">100% off</span>
          ${claimPremiumBadgeHtml(claim)}
          ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
          ${claimSourceHtml(claim.source)}
          ${endsHtml}
        </div>
        ${blurb}
        <div class="deal-hero-stats mt-2">
          <div class="deal-hero-stats-row">${review}${genreHtml}</div>
        </div>
        <div class="claim-hero-actions flex flex-wrap gap-2 mt-3">
          ${claimPlatformButtonsHtml(claim, { variant: 'hero' })}
          <button type="button" class="btn-claim-clear text-slate-400 hover:text-slate-200 text-sm px-2 py-1.5 rounded border border-slate-600" data-claim-clear="${escapeAttr(claim.id)}">Clear</button>
        </div>
      </div>
    </div>
  </article>`;
}

export function claimRowsHeaderHtml() {
  return `<div class="claim-rows-header" aria-hidden="true">
    <span class="claim-cell-cover"></span>
    <span class="claim-cell-title">Title</span>
    <span class="claim-cell-meta">
      <span class="claim-cell-review">Review</span>
      <span class="claim-cell-ends">Ends</span>
    </span>
    <span class="claim-cell-actions"></span>
  </div>`;
}

export function claimRowHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claimCoverUrl(claim);
  const ends = formatEndsAt(claim.ends_at);
  const reviewPct = reviewPercentValue(claim);
  const review = reviewPct != null ? `${reviewPct}%` : '-';
  const endsHtml = ends ? `Ends ${escapeHtml(ends)}` : '-';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="claim-row-cover${ls}" src="${escapeAttr(cover)}" data-fallback="${escapeAttr(claimCoverFallback(claim))}" data-name="${escapeAttr(claim.title || '')}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />`
    : `<span class="claim-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  return `<div class="claim-row claim-fire-card" data-claim-id="${escapeAttr(claim.id)}">
    <span class="claim-cell-cover cover-wrap claim-row-cover-wrap${ls}">${coverHtml}</span>
    <span class="claim-cell-title">
      <span class="claim-row-title truncate">${title}</span>
      ${claimPremiumBadgeHtml(claim)}
      <span class="claim-cell-store">${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}</span>
      ${claimSourceHtml(claim.source)}
    </span>
    <span class="claim-cell-meta">
      <span class="claim-cell-review">${review}</span>
      <span class="claim-cell-ends">${endsHtml}</span>
    </span>
    <span class="claim-cell-actions">
      ${claimPlatformButtonsHtml(claim, { variant: 'row' })}
      <button type="button" class="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 rounded border border-slate-600" data-claim-clear="${escapeAttr(claim.id)}">Clear</button>
    </span>
  </div>`;
}

/** Shared row for hidden/owned modals — pass `actionHtml` for Restore button or owned tag. */
export function claimHiddenRowHtml(claim, { actionHtml = '', rowClass = '' } = {}) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claimCoverUrl(claim);
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `Ends ${escapeHtml(ends)}` : '-';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="claim-hidden-row-cover${ls}" src="${escapeAttr(cover)}" alt="" loading="lazy" onload="window.markLandscape(this)" />`
    : `<span class="claim-hidden-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  const extraClass = rowClass ? ` ${rowClass}` : '';
  return `<div class="claim-hidden-row${extraClass}"${claim.id ? ` data-claim-id="${escapeAttr(claim.id)}"` : ''}>
    <span class="claim-hidden-row-cover-wrap cover-wrap${ls}">${coverHtml}</span>
    <span class="claim-hidden-row-meta min-w-0 flex-1">
      <span class="claim-hidden-row-title truncate">${title}</span>
      <span class="claim-hidden-row-badges flex flex-wrap items-center gap-1.5 mt-0.5">
        ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
        ${claimSourceHtml(claim.source)}
        <span class="text-xs text-slate-500">${endsHtml}</span>
      </span>
    </span>
    ${actionHtml}
  </div>`;
}

/** Detail dialog panel markup (caller opens the dialog and assigns innerHTML). */
export function claimDetailPanelHtml(claim, {
  owned = false,
  attribution = null,
} = {}) {
  const ends = formatEndsAt(claim.ends_at);
  const coverUrl = claimCoverUrl(claim);
  const cover = coverUrl
    ? `<img src="${escapeAttr(coverUrl)}" data-fallback="${escapeAttr(claimCoverFallback(claim))}" data-name="${escapeAttr(claim.title || '')}" alt="" class="claim-detail-cover" onerror="window.coverFallback(this)" />`
    : '';
  const reviewPct = reviewPercentValue(claim);
  const review = reviewPct != null ? `${reviewPct}% Steam reviews` : '';
  const blurbText = sanitizeBlurb(claim.blurb);
  const blurb = blurbText ? `<p class="claim-detail-blurb">${escapeHtml(blurbText)}</p>` : '';
  const endsHtml = ends
    ? `<span class="claim-detail-ends">Ends ${escapeHtml(ends)}</span>`
    : '';
  const claimBtn = claimDetailClaimActionsHtml(claim, owned);
  return `<form method="dialog" class="claim-detail-panel">
      <div class="claim-detail-header">
        <h2 class="claim-detail-title">${escapeHtml(claim.title || 'Free game')}</h2>
        <button type="submit" class="claim-detail-close" aria-label="Close">×</button>
      </div>
      ${cover}
      <div class="claim-detail-badges">
        ${storeLogoHtml(claim.store, { size: 'sm' })}
        <span class="deal-cut-badge deal-cut-huge claim-cut-fire">100% off</span>
        ${claimSourceHtml(claim.source, { tag: 'a' })}
        ${endsHtml}
        ${review ? `<span class="claim-detail-review">${escapeHtml(review)}</span>` : ''}
      </div>
      ${blurb}
      ${claimBtn}
      ${claimAttributionHtml(attribution)}
      <button type="button" class="claim-detail-clear" data-claim-clear="${escapeAttr(claim.id)}">Clear from notifications</button>
    </form>`;
}

/**
 * Build the full "Claimable Now" <section> markup for an already-resolved list
 * of claims. Mirrors what renderClaimableModule() emits in js/claimable.js:
 * a hero card for a single claim, an aligned row list for many (capped at
 * `visibleCount` with a "+N more →" toggle), plus optional show-hidden button
 * and feed attribution footer. Callers pass claims already filtered/deduped/
 * sorted (the live app via getVisibleClaims; the admin preview via
 * sortClaims(dedupeClaims(items))). Order is newest first by first_seen desc,
 * matching the admin Claims auto table default.
 */
export function claimableModuleMarkup(claims, {
  visibleCount = Infinity,
  attribution = null,
  showHiddenButtonHtml = '',
  allowHero = true,
  emptyReason = 'empty',
} = {}) {
  const list = Array.isArray(claims) ? claims : [];
  const showHiddenBtn = showHiddenButtonHtml || '';
  const attributionHtml = claimAttributionHtml(attribution);
  if (!list.length) {
    const emptyMsg = emptyReason === 'unavailable'
      ? 'Feed updating - check back soon.'
      : 'No new free games to claim right now.';
    return `<section class="claimable-now-module dash-card claim-rows-card claim-empty-card" aria-label="Claimable Now">
      <div class="claim-empty-row">
        <div class="claim-empty-text">
          <span class="dash-kpi-label claim-rows-head">Claimable Now</span>
          <span class="claim-empty-msg">${escapeHtml(emptyMsg)}</span>
        </div>
        <div class="claim-empty-actions">${showHiddenBtn}</div>
      </div>
      ${attributionHtml}
    </section>`;
  }
  // The inflated hero card is reserved for a feed that *loaded* with a single
  // claim. When a list of several is whittled down to one by dismissals, callers
  // pass allowHero:false so the survivor stays a row instead of snapping big.
  if (list.length === 1 && allowHero) {
    return `<section class="claimable-now-module space-y-3" aria-label="Claimable Now">
      ${claimCardHtml(list[0])}
      ${showHiddenBtn}
      ${attributionHtml}
    </section>`;
  }
  const visible = list.slice(0, visibleCount);
  const remaining = list.length - visible.length;
  const more = remaining > 0
    ? `<button type="button" class="text-sm text-sky-300 hover:text-sky-200 underline mt-2" data-claim-show-more>+${remaining} more →</button>`
    : '';
  return `<section class="claimable-now-module dash-card claim-rows-card" aria-label="Claimable Now">
    <div class="dash-kpi-label claim-rows-head">Claimable Now</div>
    <div class="claim-rows">${claimRowsHeaderHtml()}${visible.map(claimRowHtml).join('')}</div>
    ${more}
    ${showHiddenBtn}
    ${attributionHtml}
  </section>`;
}
