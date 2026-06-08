/** Maintainer-curated free claimable games (Claimable Now) — aggregated from Epic, GamerPower, and ITAD. */
import { state } from './state.js';
import { escapeHtml, escapeAttr, isSafeHttpUrl } from './dom-util.js';
import { normalizeNameForDedup, gameKey } from './game-core.js';
import { storeLogoHtml, storeDisplayName } from './store-logos.js';
import { savePersonal } from './personal-storage.js';
import { savePrefs } from './prefs.js';
import { switchView } from './filters-ui.js';
import { claimsSnapshotStorageKey } from './profiles.js';
import { dataFetch } from './api-client.js';
import { syncCoverFits } from './covers.js';
import {
  stripClaimTitleDecorations,
  dedupeClaims,
  sortClaims,
  sanitizeBlurb,
  reviewPercentValue,
  claimCoverUrl,
  claimCoverFallback,
  formatEndsAt,
  claimSourceHtml,
  claimAttributionHtml,
  claimableModuleMarkup,
} from './claim-card.js';

// Re-export the shared pure helpers consumed elsewhere (tests, admin) so the
// public surface of this module is unchanged after the claim-card.js split.
export {
  stripClaimTitleDecorations,
  sanitizeBlurb,
  claimCoverFallback,
  claimSourceHtml,
  claimAttributionHtml,
} from './claim-card.js';

export const CLAIMS_HOSTED_URL = 'https://baklog.app/free-claims.json';
const FALLBACK_PATH = 'curated/free_claims.fallback.json';
const MAX_VISIBLE = 5;

let _claimsVisibleCount = MAX_VISIBLE;
let _readOnlyPollTimer = null;

export function getClaimsEndpoint() {
  return (document.querySelector('meta[name="baklog-claims-endpoint"]')?.content)
    || window.__BAKLOG_CLAIMS_ENDPOINT
    || CLAIMS_HOSTED_URL;
}

function dismissedClaimsMap() {
  const m = state.personal.__dismissedClaims;
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {};
}

// Dismissals are also keyed by the stable dedup key (appid / title-norm), not
// just the volatile feed id. The displayed claim's id can change between feed
// regenerations (e.g. the same game flips from an epic-* to a gamerpower-*
// source after dedup), so an id-only dismissal would reappear on reload. The
// key map keeps a cleared claim hidden as long as the same game is in the feed.
function dismissedClaimKeysMap() {
  const m = state.personal.__dismissedClaimKeys;
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {};
}

function findClaimById(id) {
  return (state.claimableFeed?.items || []).find(c => c.id === id)
    || (state.claimableNow || []).find(c => c.id === id)
    || null;
}

function isClaimDismissed(c) {
  if (!c) return false;
  if (dismissedClaimsMap()[c.id]) return true;
  const keyMap = dismissedClaimKeysMap();
  return claimDedupKeys(c).some(k => keyMap[k]);
}

export function dismissClaim(id) {
  if (!id) return;
  const beforeVisible = (state.claimableNow || []).length;
  if (!state.personal.__dismissedClaims) state.personal.__dismissedClaims = {};
  state.personal.__dismissedClaims[id] = Date.now();
  const claim = findClaimById(id);
  const dedupKeys = claim ? claimDedupKeys(claim) : [];
  if (claim) {
    if (!state.personal.__dismissedClaimKeys) state.personal.__dismissedClaimKeys = {};
    const now = Date.now();
    for (const k of dedupKeys) state.personal.__dismissedClaimKeys[k] = now;
  }
  savePersonal();
  pruneDismissedClaims(state.claimableFeed?.items || []);
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
  closeClaimDetail();
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'A',location:'claimable.js:dismissClaim',message:'claim dismissed',data:{id,beforeVisible,afterVisible:(state.claimableNow||[]).length,dedupKeys,title:claim?.title||null},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
}

export function restoreClaim(id) {
  if (!id) return;
  const claim = findClaimById(id);
  const idMap = state.personal.__dismissedClaims;
  const keyMap = state.personal.__dismissedClaimKeys;
  let changed = false;
  if (idMap && idMap[id] != null) { delete idMap[id]; changed = true; }
  if (claim && keyMap) {
    for (const k of claimDedupKeys(claim)) {
      if (keyMap[k] != null) { delete keyMap[k]; changed = true; }
    }
  }
  if (!changed) return;
  savePersonal();
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
  const feedItems = state.claimableFeed?.items || [];
  const hidden = getHiddenClaims(feedItems);
  const owned = getOwnedClaims(feedItems);
  if (!hidden.length && !owned.length) closeHiddenClaimsModal();
  else openHiddenClaimsModal();
}

function pruneDismissedClaims(feedItems) {
  // An empty feed is indistinguishable from a failed / mid-regeneration load,
  // so never prune against it — doing so would wipe every dismissal whenever the
  // claims feed is briefly unavailable at boot (the cleared-overnight bug).
  if (!feedItems || feedItems.length === 0) return;
  const feedIds = new Set(feedItems.map(c => c?.id).filter(Boolean));
  const feedKeys = new Set(feedItems.flatMap(c => claimDedupKeys(c)).filter(Boolean));
  let changed = false;
  const dismissed = dismissedClaimsMap();
  for (const id of Object.keys(dismissed)) {
    if (!feedIds.has(id)) {
      delete dismissed[id];
      changed = true;
    }
  }
  const dismissedKeys = dismissedClaimKeysMap();
  for (const k of Object.keys(dismissedKeys)) {
    if (!feedKeys.has(k)) {
      delete dismissedKeys[k];
      changed = true;
    }
  }
  if (changed) {
    state.personal.__dismissedClaims = dismissed;
    state.personal.__dismissedClaimKeys = dismissedKeys;
    savePersonal();
  }
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

// Every stable identity a claim can be matched on. A claim's appid is filled in
// by cross-store enrichment *between* feed regenerations, so the single
// canonical dedup key (appid when present, else title) flips from `title:…` to
// `appid:…` once enrichment lands — which would resurrect a cleared claim.
// Dismissals are stored against (and checked against) all of these keys so a
// cleared claim stays cleared regardless of whether a given feed snapshot
// happens to carry the appid.
function claimDedupKeys(c) {
  if (!c) return [];
  const keys = [];
  if (c.steam_appid != null && c.steam_appid !== '') keys.push(`appid:${c.steam_appid}`);
  const norm = normalizeNameForDedup(stripClaimTitleDecorations(c.title || ''));
  if (norm) keys.push(`title:${norm}`);
  if (!keys.length && c.id) keys.push(`id:${c.id}`);
  return keys;
}

function isClaimEligible(c, now = Date.now()) {
  if (!c?.id || !c.claim_url || !c.store) return false;
  if (c.ends_at) {
    const end = Date.parse(c.ends_at);
    if (Number.isFinite(end) && end < now) return false;
  }
  if (isClaimOwned(c)) return false;
  return true;
}

export function getVisibleClaims(items) {
  const now = Date.now();
  const filtered = (items || []).filter((c) => {
    if (!isClaimEligible(c, now)) return false;
    if (isClaimDismissed(c)) return false;
    return true;
  });
  return sortClaims(dedupeClaims(filtered));
}

export function getHiddenClaims(items) {
  const now = Date.now();
  const filtered = (items || []).filter((c) => {
    if (!isClaimEligible(c, now)) return false;
    if (!isClaimDismissed(c)) return false;
    return true;
  });
  return sortClaims(dedupeClaims(filtered));
}

/** Feed items filtered out because they match a game already in the library. */
export function getOwnedClaims(items) {
  const now = Date.now();
  const filtered = (items || []).filter((c) => {
    if (!c?.id || !c.claim_url || !c.store) return false;
    if (c.ends_at) {
      const end = Date.parse(c.ends_at);
      if (Number.isFinite(end) && end < now) return false;
    }
    return isClaimOwned(c);
  });
  return sortClaims(dedupeClaims(filtered));
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

/** Newest timestamp on a feed doc (profile fetcher stamps fetched_at; bundled uses generated_at). */
export function feedGeneratedAt(doc) {
  const gen = Date.parse(doc?.generated_at || '');
  const fetched = Date.parse(doc?.fetched_at || '');
  const ts = [
    Number.isFinite(gen) ? gen : 0,
    Number.isFinite(fetched) ? fetched : 0,
  ];
  return Math.max(...ts);
}

/** Prefer the feed with the newer generated_at when both have items. */
export function pickNewerFeed(primary, secondary) {
  const a = primary?.items?.length ? primary : null;
  const b = secondary?.items?.length ? secondary : null;
  if (!a) return b;
  if (!b) return a;
  return feedGeneratedAt(b) > feedGeneratedAt(a) ? b : a;
}

function applyFeedDoc(doc, source = 'unknown') {
  state.claimableFeed = doc && typeof doc === 'object' ? doc : null;
  state.libraryMeta.claims = state.claimableFeed;
  pruneDismissedClaims(state.claimableFeed?.items || []);
  // A fresh feed resets the "show more" expansion so a stale, inflated slice
  // can't carry over after claims expire or the feed shrinks.
  _claimsVisibleCount = MAX_VISIBLE;
  applyVisibleClaims();
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'B',location:'claimable.js:applyFeedDoc',message:'feed applied',data:{source,feedItems:(state.claimableFeed?.items||[]).length,visible:(state.claimableNow||[]).length,generatedAt:state.claimableFeed?.generated_at||null,fetchedAt:state.claimableFeed?.fetched_at||null},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
}

function applyVisibleClaims() {
  const items = state.claimableFeed?.items || [];
  const now = Date.now();
  let owned = 0;
  let expired = 0;
  let ineligible = 0;
  const dismissedTitles = [];
  for (const c of items) {
    if (!c?.id || !c.claim_url || !c.store) { ineligible += 1; continue; }
    if (c.ends_at) {
      const end = Date.parse(c.ends_at);
      if (Number.isFinite(end) && end < now) { expired += 1; continue; }
    }
    if (isClaimOwned(c)) { owned += 1; continue; }
    if (isClaimDismissed(c)) { dismissedTitles.push(c.title || c.id); continue; }
  }
  state.claimableNow = getVisibleClaims(items);
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'D',location:'claimable.js:applyVisibleClaims',message:'visibility recompute',data:{total:items.length,visible:(state.claimableNow||[]).length,dismissed:dismissedTitles.length,owned,expired,ineligible,dismissedMapSize:Object.keys(dismissedClaimsMap()).length,dismissedKeyMapSize:Object.keys(dismissedClaimKeysMap()).length,dismissedTitles},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
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
  const feedSource = doc === localDoc ? 'local'
    : doc === fallbackDoc ? 'fallback'
      : doc?.generated_at && !doc?.fetched_at ? 'hosted'
        : 'merged';
  applyFeedDoc(doc, feedSource);
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

function showHiddenClaimsButtonHtml(count) {
  if (!count) return '';
  const n = count;
  return `<button type="button" class="claim-show-hidden-btn text-sm text-slate-400 hover:text-slate-200 underline mt-2" data-claim-show-hidden>Show hidden (${n})</button>`;
}

function hiddenClaimRowHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claimCoverUrl(claim);
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `Ends ${escapeHtml(ends)}` : '—';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="claim-hidden-row-cover${ls}" src="${escapeAttr(cover)}" alt="" loading="lazy" onload="window.markLandscape(this)" />`
    : `<span class="claim-hidden-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  return `<div class="claim-hidden-row" data-claim-id="${escapeAttr(claim.id)}">
    <span class="claim-hidden-row-cover-wrap cover-wrap${ls}">${coverHtml}</span>
    <span class="claim-hidden-row-meta min-w-0 flex-1">
      <span class="claim-hidden-row-title truncate">${title}</span>
      <span class="claim-hidden-row-badges flex flex-wrap items-center gap-1.5 mt-0.5">
        ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
        ${claimSourceHtml(claim.source)}
        <span class="text-xs text-slate-500">${endsHtml}</span>
      </span>
    </span>
    <button type="button" class="claim-hidden-restore-btn text-xs text-sky-300 hover:text-sky-200 px-2 py-1 rounded border border-slate-600 shrink-0" data-claim-restore="${escapeAttr(claim.id)}">Restore</button>
  </div>`;
}

// Owned claims are auto-hidden (already in the library), so the row mirrors the
// dismissed-claim row but swaps the Restore action for a static "In library" tag.
function ownedClaimRowHtml(claim) {
  const title = escapeHtml(claim.title || 'Free game');
  const store = claim.store || 'other';
  const cover = claimCoverUrl(claim);
  const ends = formatEndsAt(claim.ends_at);
  const endsHtml = ends ? `Ends ${escapeHtml(ends)}` : '—';
  const ls = cover ? window.coverLandscapeAttr(cover) : '';
  const coverHtml = cover
    ? `<img class="claim-hidden-row-cover${ls}" src="${escapeAttr(cover)}" alt="" loading="lazy" onload="window.markLandscape(this)" />`
    : `<span class="claim-hidden-row-cover claim-hero-cover-fallback" aria-hidden="true"></span>`;
  return `<div class="claim-hidden-row claim-owned-row">
    <span class="claim-hidden-row-cover-wrap cover-wrap${ls}">${coverHtml}</span>
    <span class="claim-hidden-row-meta min-w-0 flex-1">
      <span class="claim-hidden-row-title truncate">${title}</span>
      <span class="claim-hidden-row-badges flex flex-wrap items-center gap-1.5 mt-0.5">
        ${storeLogoHtml(store, { size: 'sm', title: storeDisplayName(store) })}
        ${claimSourceHtml(claim.source)}
        <span class="text-xs text-slate-500">${endsHtml}</span>
      </span>
    </span>
    <span class="claim-owned-tag text-xs text-emerald-300 px-2 py-1 rounded border border-emerald-700/60 shrink-0">In library</span>
  </div>`;
}

export function openHiddenClaimsModal() {
  const dlg = document.getElementById('claimHiddenDialog');
  if (!dlg) return;
  const feedItems = state.claimableFeed?.items || [];
  const hidden = getHiddenClaims(feedItems);
  const owned = getOwnedClaims(feedItems);
  if (!hidden.length && !owned.length) {
    closeHiddenClaimsModal();
    return;
  }
  const hiddenSection = hidden.length
    ? `<p class="claim-hidden-intro text-sm text-slate-400 mt-2">Claims you cleared from notifications. Restore any you want to see again.</p>
      <div class="claim-hidden-list mt-3 space-y-2">${hidden.map(hiddenClaimRowHtml).join('')}</div>`
    : '';
  const ownedSection = owned.length
    ? `<div class="claim-owned-section mt-4 pt-4 border-t border-slate-700/60">
        <h3 class="claim-owned-heading text-sm font-medium text-slate-300">Already in your library</h3>
        <p class="claim-owned-intro text-sm text-slate-400 mt-1">Hidden automatically because you already own ${owned.length === 1 ? 'this game' : 'these games'}.</p>
        <div class="claim-hidden-list mt-3 space-y-2">${owned.map(ownedClaimRowHtml).join('')}</div>
      </div>`
    : '';
  dlg.innerHTML = `
    <form method="dialog" class="claim-detail-panel claim-hidden-panel">
      <div class="claim-detail-header">
        <h2 class="claim-detail-title">Hidden claim notifications</h2>
        <button type="submit" class="claim-detail-close" aria-label="Close">×</button>
      </div>
      <div class="claim-hidden-scroll">
        ${hiddenSection}
        ${ownedSection}
      </div>
    </form>`;
  if (typeof dlg.showModal === 'function') {
    dlg.showModal();
    dlg.focus();
  }
  syncCoverFits(dlg);
}

export function closeHiddenClaimsModal() {
  const dlg = document.getElementById('claimHiddenDialog');
  if (dlg?.open) dlg.close();
}

export function renderClaimableModule() {
  const mount = document.getElementById('claimableNowModule');
  if (!mount) return;
  const show = state.activeView === 'wishlist' && state.dashboardDataReady;
  const feedItems = state.claimableFeed?.items || [];
  // Recompute the visible set from the current feed + owned + dismissed state on
  // every render. state.claimableNow can be stale: it is first computed during
  // boot (loadClaimableNow) before ownedNormNames finishes building, and the
  // post-merge refreshClaimableUi only recomputes when the wishlist tab is
  // already active. Without this, switching to wishlist paints owned games as
  // claimable, and the first Clear click triggers the recompute that drops them
  // all at once — looking like one click cleared several. Recomputing here keeps
  // the painted list consistent with hiddenCount/ownedCount below.
  const claimsBefore = (state.claimableNow || []).length;
  state.claimableNow = getVisibleClaims(feedItems);
  const claims = state.claimableNow;
  const hiddenCount = getHiddenClaims(feedItems).length;
  const ownedCount = getOwnedClaims(feedItems).length;
  const hide = !show || (!claims.length && !hiddenCount && !ownedCount);
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',runId:'post-fix',hypothesisId:'H',location:'claimable.js:renderClaimableModule',message:'module render',data:{hide,show,activeView:state.activeView,dashboardDataReady:state.dashboardDataReady,claimsBefore,claimsCount:claims.length,hiddenCount,ownedCount,feedItems:feedItems.length},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
  if (hide) {
    mount.classList.add('hidden');
    mount.innerHTML = '';
    return;
  }
  mount.classList.remove('hidden');
  mount.innerHTML = claimableModuleMarkup(claims, {
    visibleCount: _claimsVisibleCount,
    attribution: state.claimableFeed?.attribution,
    showHiddenButtonHtml: showHiddenClaimsButtonHtml(hiddenCount + ownedCount),
  });
  if (claims.length) syncCoverFits(mount);
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
  const owned = isClaimOwned(claim);
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
  const claimable = !owned && isSafeHttpUrl(claim.claim_url);
  const claimBtn = owned
    ? `<p class="claim-detail-owned">Already in your library.</p>`
    : (claimable
      ? `<a href="${escapeAttr(claim.claim_url)}" target="_blank" rel="noopener noreferrer" class="claim-detail-claim-btn">Claim free →</a>`
      : `<p class="claim-detail-owned">Claim link unavailable.</p>`);
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
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'F',location:'claimable.js:animateClaimOut',message:'animate start',data:{id,foundEl:!!el,reduceMotion:!!reduceMotion},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
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
    // #region agent log
    fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'F',location:'claimable.js:animateClaimOut.finish',message:'animate finish',data:{id,via},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    commit();
  };
  el.addEventListener('transitionend', (ev) => { if (ev.propertyName === 'height') finish('transitionend'); });
  setTimeout(() => finish('timeout'), 360); // fallback if transitionend never fires
}

export function handleClaimableClick(e) {
  const clearBtn = e.target.closest('[data-claim-clear]');
  const goBtnEarly = e.target.closest('[data-claim-go]');
  const cardEarly = e.target.closest('[data-claim-id]');
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'88c551'},body:JSON.stringify({sessionId:'88c551',hypothesisId:'A',location:'claimable.js:handleClaimableClick',message:'claim click',data:{action:clearBtn?'clear':goBtnEarly?'go':cardEarly?'open':e.target.closest('[data-claim-show-more]')?'more':e.target.closest('[data-claim-show-hidden]')?'hidden':'unknown',claimId:clearBtn?.dataset.claimClear||goBtnEarly?.dataset.claimGo||cardEarly?.dataset.claimId||null,visibleBefore:(state.claimableNow||[]).length,tagName:e.target?.tagName||null,evType:e.type||null,evDetail:e.detail,isTrusted:e.isTrusted,currentTargetId:e.currentTarget?.id||null},timestamp:Date.now()})}).catch(()=>{});
  // #endregion
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
    if (isSafeHttpUrl(claim?.claim_url)) window.open(claim.claim_url, '_blank', 'noopener,noreferrer');
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
  if (e.target.closest('[data-claim-show-hidden]')) {
    openHiddenClaimsModal();
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
