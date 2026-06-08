/** Maintainer-curated free claimable games (Claimable Now) — aggregated from Epic, GamerPower, and ITAD. */
import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { normalizeNameForDedup, gameKey } from './game-core.js';
import { storeLogoHtml, storeDisplayName } from './store-logos.js';
import { savePersonal } from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { switchView } from './filters-ui.js';
import { claimsSnapshotStorageKey } from './profiles.js';
import { dataFetch } from './api-client.js';
import { syncCoverFits } from './covers.js';

export const CLAIMS_HOSTED_URL = 'https://baklog.app/free-claims.json';
const FALLBACK_PATH = 'curated/free_claims.fallback.json';
const MAX_VISIBLE = 5;

let _claimsVisibleCount = MAX_VISIBLE;
let _readOnlyPollTimer = null;
let _detailClaimId = null;

export function getClaimsEndpoint() {
  return (document.querySelector('meta[name="baklog-claims-endpoint"]')?.content)
    || window.__BAKLOG_CLAIMS_ENDPOINT
    || CLAIMS_HOSTED_URL;
}

function dismissedClaimsMap() {
  const m = state.personal.__dismissedClaims;
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {};
}

export function dismissClaim(id) {
  if (!id) return;
  if (!state.personal.__dismissedClaims) state.personal.__dismissedClaims = {};
  state.personal.__dismissedClaims[id] = Date.now();
  savePersonal();
  pruneDismissedClaims(state.claimableFeed?.items || []);
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
  closeClaimDetail();
}

function pruneDismissedClaims(feedItems) {
  const feedIds = new Set((feedItems || []).map(c => c?.id).filter(Boolean));
  const dismissed = dismissedClaimsMap();
  let changed = false;
  for (const id of Object.keys(dismissed)) {
    if (!feedIds.has(id)) {
      delete dismissed[id];
      changed = true;
    }
  }
  if (changed) {
    state.personal.__dismissedClaims = dismissed;
    savePersonal();
  }
}

/** Strip giveaway/store boilerplate from auto-sourced claim titles before ownership match. */
export function stripClaimTitleDecorations(title) {
  let t = String(title || '').trim();
  if (!t) return t;
  t = t.replace(/\s*\([^)]*\)\s*giveaway\s*$/i, '');
  t = t.replace(/\s+free\s+(at\s+egs\s+)?on\s+epic\s+game\s+store.*$/i, '');
  t = t.replace(/\s+free\s+for\s+mobile\s+on\s+egs.*$/i, '');
  t = t.replace(/\s+in\s+game\s+(items?|currency\s+pack).*$/i, '');
  t = t.replace(/\s+free\s+on\s+(steam|itchio|itch\.io|gog|indiegala).*$/i, '');
  t = t.replace(/\s*-\s*free\s+on\s+indiegala.*$/i, '');
  t = t.replace(/\s+on\s+(steam|gog|itch\.?io|epic\s+game\s+store)\s*$/i, '');
  t = t.replace(/\s+-\s+chapters?[\s\d,]+.*$/i, '');
  t = t.replace(/\s+giveaway\s*$/i, '');
  return t.trim();
}

function claimTitleNorms(title) {
  const raw = String(title || '');
  const norms = new Set();
  for (const candidate of [raw, stripClaimTitleDecorations(raw)]) {
    const n = normalizeNameForDedup(candidate);
    if (n) norms.add(n);
  }
  return [...norms];
}

export function isClaimOwned(claim) {
  if (!claim) return false;
  const appid = claim.steam_appid;
  let appidMatched = false;
  if (appid != null) {
    const sid = String(appid);
    if (state.allGames.some(g => g.store === 'steam' && String(g.appid ?? g.id) === sid)) appidMatched = true;
    else if (state.allGames.some(g => gameKey(g) === `steam:${sid}`)) appidMatched = true;
  }
  const norms = claimTitleNorms(claim.title);
  const titleMatched = norms.some(n => state.ownedNormNames?.has(n));
  if (appidMatched) return true;
  if (titleMatched) return true;
  return false;
}

export function getVisibleClaims(items) {
  const dismissed = dismissedClaimsMap();
  const now = Date.now();
  return (items || []).filter((c) => {
    if (!c?.id || !c.claim_url || !c.store) return false;
    if (dismissed[c.id]) return false;
    if (c.ends_at) {
      const end = Date.parse(c.ends_at);
      if (Number.isFinite(end) && end < now) return false;
    }
    if (isClaimOwned(c)) return false;
    return true;
  }).sort((a, b) => {
    const ea = a.ends_at ? Date.parse(a.ends_at) : Infinity;
    const eb = b.ends_at ? Date.parse(b.ends_at) : Infinity;
    if (ea !== eb) return ea - eb;
    return String(a.title || '').localeCompare(String(b.title || ''));
  });
}

export function diffClaims(prevIds, items) {
  const visible = getVisibleClaims(items);
  let newCount = 0;
  for (const c of visible) {
    if (!prevIds.has(c.id)) newCount += 1;
  }
  return { newCount, visible };
}

function loadClaimsSnapshotIds() {
  try {
    const raw = localStorage.getItem(claimsSnapshotStorageKey());
    if (!raw) return new Set();
    const ids = JSON.parse(raw)?.ids;
    return new Set(Array.isArray(ids) ? ids : []);
  } catch {
    return new Set();
  }
}

export function saveClaimsSnapshot(items) {
  const ids = getVisibleClaims(items).map(c => c.id);
  try {
    localStorage.setItem(claimsSnapshotStorageKey(), JSON.stringify({
      saved_at: Date.now(),
      ids,
    }));
  } catch (_) { /* quota */ }
}

async function fetchHostedClaims() {
  const url = getClaimsEndpoint();
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`claims feed ${res.status}`);
  return res.json();
}

async function loadBundledFallback() {
  try {
    const res = await dataFetch(FALLBACK_PATH);
    if (!res.ok) return null;
    return res.json();
  } catch {
    return null;
  }
}

/** Parse feed timestamp for local vs bundled comparison (profile uses fetched_at). */
export function feedGeneratedAt(doc) {
  const raw = doc?.generated_at || doc?.fetched_at || '';
  const t = Date.parse(raw);
  return Number.isFinite(t) ? t : 0;
}

/** Prefer the feed with the newer generated_at when both have items. */
export function pickNewerFeed(primary, secondary) {
  const a = primary?.items?.length ? primary : null;
  const b = secondary?.items?.length ? secondary : null;
  if (!a) return b;
  if (!b) return a;
  return feedGeneratedAt(b) > feedGeneratedAt(a) ? b : a;
}

function applyFeedDoc(doc) {
  state.claimableFeed = doc && typeof doc === 'object' ? doc : null;
  state.libraryMeta.claims = state.claimableFeed;
  pruneDismissedClaims(state.claimableFeed?.items || []);
  applyVisibleClaims();
}

function applyVisibleClaims() {
  state.claimableNow = getVisibleClaims(state.claimableFeed?.items || []);
}

async function loadLocalClaimsFile() {
  try {
    const res = await dataFetch(`free_claims.json?t=${Date.now()}`);
    if (!res.ok) return null;
    const doc = await res.json();
    return doc;
  } catch {
    return null;
  }
}

export async function loadClaimableNow({ preferHosted = false } = {}) {
  let localDoc = null;
  let fallbackDoc = null;
  try {
    localDoc = await loadLocalClaimsFile();
  } catch (_) { /* offline */ }
  try {
    fallbackDoc = await loadBundledFallback();
  } catch (_) { /* offline */ }

  let doc = pickNewerFeed(localDoc, fallbackDoc);

  if (preferHosted || !doc?.items?.length) {
    try {
      const hosted = await fetchHostedClaims();
      if (hosted?.items?.length) doc = pickNewerFeed(doc, hosted) || hosted;
    } catch (_) { /* network */ }
  }
  if (!doc?.items?.length) doc = { generated_at: null, items: [] };
  applyFeedDoc(doc);
  return state.claimableNow;
}

export function refreshClaimableUi() {
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
}

let claimsPendingAutoRun = false;

export function consumeClaimsAutoRunFlag() {
  const v = claimsPendingAutoRun;
  claimsPendingAutoRun = false;
  return v;
}

export function markClaimsPendingAutoRun() {
  claimsPendingAutoRun = true;
}

/**
 * ITAD-sourced claims ship `blurb` as raw HTML (anchor tags + literal giveaway
 * URLs + "expires on … | go to giveaway" boilerplate). Escaping it for display
 * leaks that markup/URL as visible text, so strip tags, decode the handful of
 * entities ITAD emits, and drop the giveaway boilerplate before rendering.
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
  return t.replace(/\s+/g, ' ').trim();
}

function formatEndsAt(endsAt) {
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
    ? `<a href="${escapeAttr(meta.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
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
  return `<p class="claim-attribution">Giveaway data via ${parts.join(' · ')}</p>`;
}

function claimCardHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claim.header_image || '';
  const blurbText = sanitizeBlurb(claim.blurb);
  const blurb = blurbText ? `<p class="claim-hero-blurb text-sm text-slate-400 mt-1">${escapeHtml(blurbText)}</p>` : '';
  const review = claim.review_percent != null
    ? `<span class="deal-hero-stat" title="Steam review score"><span class="deal-hero-stat-dot deal-hero-stat-dot-review"></span>${claim.review_percent}%</span>`
    : '';
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `<span class="text-xs text-amber-300/90">Ends ${escapeHtml(ends)}</span>` : '';
  const genres = (claim.genres || []).slice(0, 2).map(escapeHtml).join(' · ');
  const genreHtml = genres ? `<span class="deal-hero-genres">${genres}</span>` : '';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="deal-hero-cover${ls}" src="${escapeAttr(cover)}" alt="" loading="lazy" onload="window.markLandscape(this)" />`
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
          ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
          ${claimSourceHtml(claim.source)}
          ${endsHtml}
        </div>
        ${blurb}
        <div class="deal-hero-stats mt-2">
          <div class="deal-hero-stats-row">${review}${genreHtml}</div>
        </div>
        <div class="claim-hero-actions flex flex-wrap gap-2 mt-3">
          <button type="button" class="btn-claim-open bg-sky-600 hover:bg-sky-500 text-white text-sm font-semibold px-3 py-1.5 rounded" data-claim-go="${escapeAttr(claim.id)}">Claim free →</button>
          <button type="button" class="btn-claim-clear text-slate-400 hover:text-slate-200 text-sm px-2 py-1.5 rounded border border-slate-600" data-claim-clear="${escapeAttr(claim.id)}">Clear</button>
        </div>
      </div>
    </div>
  </article>`;
}

function claimRowsHeaderHtml() {
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

function claimRowHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claim.header_image || '';
  const ends = formatEndsAt(claim.ends_at);
  const review = claim.review_percent != null ? `${claim.review_percent}%` : '—';
  const endsHtml = ends ? `Ends ${escapeHtml(ends)}` : '—';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="claim-row-cover${ls}" src="${escapeAttr(cover)}" alt="" loading="lazy" onload="window.markLandscape(this)" />`
    : `<span class="claim-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  return `<div class="claim-row claim-fire-card" data-claim-id="${escapeAttr(claim.id)}">
    <span class="claim-cell-cover cover-wrap claim-row-cover-wrap${ls}">${coverHtml}</span>
    <span class="claim-cell-title">
      <span class="claim-row-title truncate">${title}</span>
      <span class="claim-cell-store">${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}</span>
      ${claimSourceHtml(claim.source)}
    </span>
    <span class="claim-cell-meta">
      <span class="claim-cell-review">${review}</span>
      <span class="claim-cell-ends">${endsHtml}</span>
    </span>
    <span class="claim-cell-actions">
      <button type="button" class="btn-claim-open bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-2.5 py-1 rounded" data-claim-go="${escapeAttr(claim.id)}">Claim free →</button>
      <button type="button" class="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 rounded border border-slate-600" data-claim-clear="${escapeAttr(claim.id)}">Clear</button>
    </span>
  </div>`;
}

export function renderClaimableModule() {
  const mount = document.getElementById('claimableNowModule');
  if (!mount) return;
  const show = state.activeView === 'wishlist' && state.dashboardDataReady;
  const claims = state.claimableNow || [];
  if (!show || !claims.length) {
    mount.classList.add('hidden');
    mount.innerHTML = '';
    return;
  }
  mount.classList.remove('hidden');
  const visible = claims.slice(0, _claimsVisibleCount);
  const remaining = claims.length - visible.length;
  const more = remaining > 0
    ? `<button type="button" class="text-sm text-sky-300 hover:text-sky-200 underline mt-2" data-claim-show-more>+${remaining} more →</button>`
    : '';
  const attribution = claimAttributionHtml(state.claimableFeed?.attribution);
  if (claims.length === 1) {
    mount.innerHTML = `<section class="claimable-now-module space-y-3" aria-label="Claimable Now">
      ${claimCardHtml(claims[0])}
      ${attribution}
    </section>`;
    syncCoverFits(mount);
    return;
  }
  mount.innerHTML = `<section class="claimable-now-module dash-card claim-rows-card" aria-label="Claimable Now">
    <div class="dash-kpi-label claim-rows-head">Claimable Now</div>
    <div class="claim-rows">${claimRowsHeaderHtml()}${visible.map(claimRowHtml).join('')}</div>
    ${more}
    ${attribution}
  </section>`;
  syncCoverFits(mount);
}

export function showClaimableBanner(newCount) {
  const el = document.getElementById('claimableBanner');
  if (!el || !newCount) return;
  const n = newCount;
  el.innerHTML = `
    <div class="migration-banner-body">
      <span><strong>${n} free game${n === 1 ? '' : 's'}</strong> ready to claim right now.
        <button type="button" class="text-sky-300 hover:text-sky-200 underline ml-1" data-claim-view>View claims →</button>
      </span>
      <span class="migration-banner-actions">
        <button type="button" class="fh-log-btn" data-claim-banner-dismiss>Dismiss</button>
      </span>
    </div>`;
  el.classList.remove('hidden');
}

export function updateClaimableBanner() {
  const el = document.getElementById('claimableBanner');
  if (!el || el.classList.contains('hidden')) return;
  const prevIds = loadClaimsSnapshotIds();
  const { newCount } = diffClaims(prevIds, state.claimableFeed?.items || []);
  if (newCount <= 0) el.classList.add('hidden');
}

export function openClaimDetail(id) {
  const claim = (state.claimableFeed?.items || []).find(c => c.id === id)
    || state.claimableNow.find(c => c.id === id);
  const dlg = document.getElementById('claimDetailDialog');
  if (!claim || !dlg) return;
  _detailClaimId = id;
  const owned = isClaimOwned(claim);
  const ends = formatEndsAt(claim.ends_at);
  const cover = claim.header_image
    ? `<img src="${escapeAttr(claim.header_image)}" alt="" class="claim-detail-cover" />`
    : '';
  const review = claim.review_percent != null ? `${claim.review_percent}% Steam reviews` : '';
  const blurbText = sanitizeBlurb(claim.blurb);
  const blurb = blurbText ? `<p class="claim-detail-blurb">${escapeHtml(blurbText)}</p>` : '';
  const endsHtml = ends
    ? `<span class="claim-detail-ends">Ends ${escapeHtml(ends)}</span>`
    : '';
  const claimBtn = owned
    ? `<p class="claim-detail-owned">Already in your library.</p>`
    : `<a href="${escapeAttr(claim.claim_url)}" target="_blank" rel="noopener" class="claim-detail-claim-btn">Claim free →</a>`;
  dlg.innerHTML = `
    <form method="dialog" class="claim-detail-panel">
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
      ${claimAttributionHtml(state.claimableFeed?.attribution)}
      <button type="button" class="claim-detail-clear" data-claim-clear="${escapeAttr(claim.id)}">Clear from notifications</button>
    </form>`;
  if (typeof dlg.showModal === 'function') {
    dlg.showModal();
    // showModal() autofocuses the first focusable child (the × close button).
    dlg.focus();
  }
}

export function closeClaimDetail() {
  const dlg = document.getElementById('claimDetailDialog');
  _detailClaimId = null;
  if (dlg?.open) dlg.close();
}

function findClaimEl(id) {
  const mount = document.getElementById('claimableNowModule');
  if (!mount) return null;
  return [...mount.querySelectorAll('[data-claim-id]')].find(el => el.dataset.claimId === id) || null;
}

/**
 * Collapse + fade the cleared card/row out before committing the dismissal, so
 * the list settles fluidly instead of snapping on the full innerHTML rebuild.
 * Falls back to an immediate commit when the element is missing or the user
 * prefers reduced motion.
 */
function animateClaimOut(id, commit) {
  const el = findClaimEl(id);
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
  if (!el || reduceMotion) { commit(); return; }

  const h = el.getBoundingClientRect().height;
  el.style.height = `${h}px`;
  el.style.flexShrink = '0';
  void el.offsetHeight; // commit the fixed height before transitioning to 0
  el.classList.add('claim-clearing');
  requestAnimationFrame(() => {
    el.style.height = '0px';
    el.style.opacity = '0';
    el.style.transform = 'translateX(-14px)';
    el.style.marginTop = '0px';
    el.style.marginBottom = '0px';
    el.style.paddingTop = '0px';
    el.style.paddingBottom = '0px';
  });

  let finished = false;
  const finish = (via) => {
    if (finished) return; finished = true;
    commit();
  };
  el.addEventListener('transitionend', (ev) => { if (ev.propertyName === 'height') finish('transitionend'); });
  setTimeout(() => finish('timeout'), 360); // fallback if transitionend never fires
}

export function handleClaimableClick(e) {
  const clearBtn = e.target.closest('[data-claim-clear]');
  if (clearBtn) {
    const id = clearBtn.dataset.claimClear;
    const inModule = !!clearBtn.closest('#claimableNowModule');
    const skipAnim = inModule && (state.claimableNow?.length || 0) <= 1;
    // Only animate when clearing from the inline list; the detail dialog covers
    // the card, so there animate would just delay the dialog close pointlessly.
    // Skip animation for the last/only claim — the whole module hides on dismiss.
    if (inModule && !skipAnim) animateClaimOut(id, () => dismissClaim(id));
    else dismissClaim(id);
    return true;
  }
  const goBtn = e.target.closest('[data-claim-go]');
  if (goBtn) {
    const id = goBtn.dataset.claimGo;
    const claim = (state.claimableFeed?.items || []).find(c => c.id === id)
      || state.claimableNow.find(c => c.id === id);
    if (claim?.claim_url) window.open(claim.claim_url, '_blank', 'noopener');
    return true;
  }
  const openBtn = e.target.closest('[data-claim-open]');
  if (openBtn) {
    openClaimDetail(openBtn.dataset.claimOpen);
    return true;
  }
  const card = e.target.closest('[data-claim-id]');
  if (card && !e.target.closest('button')) {
    openClaimDetail(card.dataset.claimId);
    return true;
  }
  if (e.target.closest('[data-claim-show-more]')) {
    _claimsVisibleCount += MAX_VISIBLE;
    renderClaimableModule();
    return true;
  }
  return false;
}

export function handleClaimableBannerClick(e) {
  if (e.target.closest('[data-claim-banner-dismiss]')) {
    saveClaimsSnapshot(state.claimableFeed?.items || []);
    document.getElementById('claimableBanner')?.classList.add('hidden');
    return true;
  }
  if (e.target.closest('[data-claim-view]')) {
    saveClaimsSnapshot(state.claimableFeed?.items || []);
    document.getElementById('claimableBanner')?.classList.add('hidden');
    if (state.activeView !== 'wishlist') switchView('wishlist');
    else renderClaimableModule();
    requestAnimationFrame(() => {
      document.getElementById('claimableNowModule')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    return true;
  }
  return false;
}

export function startClaimableReadOnlyPolling(intervalMs = 15 * 60_000) {
  if (_readOnlyPollTimer) return;
  _readOnlyPollTimer = setInterval(async () => {
    if (document.visibilityState !== 'visible') return;
    const prevIds = loadClaimsSnapshotIds();
    try {
      await loadClaimableNow({ preferHosted: true });
      const { newCount } = diffClaims(prevIds, state.claimableFeed?.items || []);
      if (newCount > 0) showClaimableBanner(newCount);
      saveClaimsSnapshot(state.claimableFeed?.items || []);
      refreshClaimableUi();
    } catch (_) { /* silent */ }
  }, intervalMs);
}
