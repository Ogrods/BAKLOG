/** Maintainer-curated free claimable games (Claimable Now). */
import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { normalizeNameForDedup, gameKey } from './game-core.js';
import { storeLogoHtml, storeDisplayName } from './store-logos.js';
import { savePersonal } from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { switchView } from './filters-ui.js';
import { claimsSnapshotStorageKey } from './profiles.js';
import { dataFetch } from './api-client.js';

export const CLAIMS_HOSTED_URL = 'https://baklog.app/free-claims.json';
const FALLBACK_PATH = 'curated/free_claims.fallback.json';
const MAX_VISIBLE = 3;

let _claimsExpandAll = false;
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
    return res.json();
  } catch {
    return null;
  }
}

export async function loadClaimableNow({ preferHosted = false } = {}) {
  let doc = null;
  try {
    doc = await loadLocalClaimsFile();
  } catch (_) { /* offline */ }

  const empty = !doc?.items?.length;
  if (empty || preferHosted) {
    try {
      const hosted = await fetchHostedClaims();
      if (hosted?.items?.length) doc = hosted;
    } catch (_) { /* network */ }
  }
  if (!doc?.items?.length) {
    doc = await loadBundledFallback() || { generated_at: null, items: [] };
  }
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

function formatEndsAt(endsAt) {
  if (!endsAt) return null;
  const t = Date.parse(endsAt);
  if (!Number.isFinite(t)) return null;
  const d = new Date(t);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

function claimCardHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claim.header_image || '';
  const blurb = claim.blurb ? `<p class="claim-hero-blurb text-sm text-slate-400 mt-1">${escapeHtml(claim.blurb)}</p>` : '';
  const review = claim.review_percent != null
    ? `<span class="deal-hero-stat" title="Steam review score"><span class="deal-hero-stat-dot deal-hero-stat-dot-review"></span>${claim.review_percent}%</span>`
    : '';
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `<span class="text-xs text-amber-300/90">Ends ${escapeHtml(ends)}</span>` : '';
  const genres = (claim.genres || []).slice(0, 2).map(escapeHtml).join(' · ');
  const genreHtml = genres ? `<span class="deal-hero-genres">${genres}</span>` : '';
  const coverHtml = cover
    ? `<img class="deal-hero-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" />`
    : `<span class="deal-hero-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;

  return `<article class="claim-hero-card dash-card deal-rail-card claim-fire-card w-full" data-claim-id="${escapeAttr(claim.id)}">
    <div class="dash-kpi-label">Claimable Now</div>
    <div class="deal-hero-body mt-2">
      <span class="cover-wrap deal-hero-cover-wrap">${coverHtml}</span>
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

function claimRowHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claim.header_image || '';
  const ends = formatEndsAt(claim.ends_at);
  const review = claim.review_percent != null ? `${claim.review_percent}%` : '';
  const genres = (claim.genres || []).slice(0, 2).map(escapeHtml).join(' · ');
  const coverHtml = cover
    ? `<img class="claim-row-cover" src="${escapeAttr(cover)}" alt="" loading="lazy" />`
    : `<span class="claim-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  return `<div class="claim-row claim-fire-card" data-claim-id="${escapeAttr(claim.id)}">
    <span class="cover-wrap claim-row-cover-wrap">${coverHtml}</span>
    <div class="claim-row-main min-w-0">
      <div class="claim-row-title truncate">${title}</div>
      <div class="claim-row-meta">
        ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
        <span class="deal-cut-badge claim-cut-fire">100% off</span>
        ${ends ? `<span class="claim-row-ends">Ends ${escapeHtml(ends)}</span>` : ''}
        ${review ? `<span class="claim-row-review">${review}</span>` : ''}
        ${genres ? `<span class="claim-row-genres truncate">${genres}</span>` : ''}
      </div>
    </div>
    <div class="claim-row-actions">
      <button type="button" class="btn-claim-open bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold px-2.5 py-1 rounded" data-claim-go="${escapeAttr(claim.id)}">Claim free →</button>
      <button type="button" class="text-slate-400 hover:text-slate-200 text-xs px-2 py-1 rounded border border-slate-600" data-claim-clear="${escapeAttr(claim.id)}">Clear</button>
    </div>
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
  const visible = _claimsExpandAll ? claims : claims.slice(0, MAX_VISIBLE);
  const more = claims.length > MAX_VISIBLE && !_claimsExpandAll
    ? `<button type="button" class="text-sm text-sky-300 hover:text-sky-200 underline mt-2" data-claim-show-all>Show all ${claims.length}</button>`
    : '';
  if (claims.length === 1) {
    mount.innerHTML = `<section class="claimable-now-module space-y-3" aria-label="Claimable Now">
      ${claimCardHtml(claims[0])}
    </section>`;
    return;
  }
  mount.innerHTML = `<section class="claimable-now-module dash-card claim-rows-card" aria-label="Claimable Now">
    <div class="dash-kpi-label claim-rows-head">Claimable Now</div>
    <div class="claim-rows">${visible.map(claimRowHtml).join('')}</div>
    ${more}
  </section>`;
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
    ? `<img src="${escapeAttr(claim.header_image)}" alt="" class="claim-detail-cover rounded" />`
    : '';
  const review = claim.review_percent != null ? `${claim.review_percent}% Steam reviews` : '';
  const blurb = claim.blurb ? `<p class="text-slate-300 mt-2">${escapeHtml(claim.blurb)}</p>` : '';
  const claimBtn = owned
    ? `<p class="text-emerald-300 text-sm mt-3">Already in your library.</p>`
    : `<a href="${escapeAttr(claim.claim_url)}" target="_blank" rel="noopener" class="inline-block mt-3 bg-gradient-to-b from-orange-400 to-orange-600 hover:from-orange-300 hover:to-orange-500 text-slate-950 font-bold px-4 py-2 rounded claim-detail-claim-btn">Claim free →</a>`;
  dlg.innerHTML = `
    <form method="dialog" class="claim-detail-panel bg-slate-800 border border-slate-600 rounded-lg p-4 max-w-md w-[min(100vw-2rem,28rem)]">
      <div class="flex justify-between items-start gap-2">
        <h2 class="text-lg font-semibold text-slate-100 pr-6">${escapeHtml(claim.title || 'Free game')}</h2>
        <button type="submit" class="text-slate-400 hover:text-white text-xl leading-none" aria-label="Close">×</button>
      </div>
      ${cover}
      <div class="flex flex-wrap items-center gap-2 mt-2">
        ${storeLogoHtml(claim.store, { size: 'sm' })}
        <span class="deal-cut-badge deal-cut-huge claim-cut-fire">100% off</span>
        ${ends ? `<span class="text-xs text-amber-300">${escapeHtml(ends)}</span>` : ''}
        ${review ? `<span class="text-xs text-slate-400">${escapeHtml(review)}</span>` : ''}
      </div>
      ${blurb}
      ${claimBtn}
      <button type="button" class="block mt-3 text-sm text-slate-400 hover:text-slate-200 underline" data-claim-clear="${escapeAttr(claim.id)}">Clear from notifications</button>
    </form>`;
  if (typeof dlg.showModal === 'function') dlg.showModal();
}

export function closeClaimDetail() {
  const dlg = document.getElementById('claimDetailDialog');
  _detailClaimId = null;
  if (dlg?.open) dlg.close();
}

export function handleClaimableClick(e) {
  const clearBtn = e.target.closest('[data-claim-clear]');
  if (clearBtn) {
    dismissClaim(clearBtn.dataset.claimClear);
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
  if (e.target.closest('[data-claim-show-all]')) {
    _claimsExpandAll = true;
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
