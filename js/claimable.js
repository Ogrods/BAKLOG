/** Maintainer-curated free claimable games (Claimable Now) — aggregated from Epic, GamerPower, and ITAD. */
import { state } from './state.js';
import { escapeAttr, isSafeHttpUrl } from './dom-util.js';
import { normalizeNameForDedup, gameKey } from './game-core.js';
import { savePersonal } from './personal-storage.js';
import { switchView } from './filters-ui.js';
import { claimsSnapshotStorageKey } from './profiles.js';
import { dataFetch } from './api-client.js';
import { syncCoverFits } from './covers.js';
import { getAdsForLocation, sponsoredClaimCardHtml } from './sponsored-deals.js';
import { isPro } from './auth-gate.js';
import { affiliateUrl } from './affiliate.js';
import { hasValidClaimLinks, normalizeClaimUrls } from './claim-links.js';
import { isDebugEnabled } from './debug-overlay.js';
import {
  stripClaimTitleDecorations,
  dedupeClaims,
  sortClaims,
  claimableModuleMarkup,
  claimHiddenRowHtml,
  claimDetailPanelHtml,
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
/** Max wait for the hosted claims feed during reload (post-fetcher must not hang the chip). */
export const CLAIMS_HOSTED_FETCH_MS = 12_000;
const FALLBACK_PATH = 'curated/free_claims.fallback.json';
/** Prefer hosted feed when generated_at is this much newer than local (boot freshness). */
export const HOSTED_BOOT_FRESHNESS_MS = 60 * 60 * 1000;
const MAX_VISIBLE = 5;
// Dismissals persist until the user restores them from the hidden-claims menu.
// Never auto-prune by age or feed absence — feed ids churn and sources flap.

let _claimsVisibleCount = MAX_VISIBLE;
let _readOnlyPollTimer = null;
// The big hero card is only for a feed that loaded with a single claim. Once the
// user dismisses any claim from a longer list, the last survivor must stay a row
// rather than inflating into the hero card. Reset whenever a fresh feed loads.
let _claimDismissedSinceLoad = false;

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

// Purged claims are permanently removed via "Clear all" in the hidden-claims
// menu. Unlike a dismissal (restorable), a purge is irreversible: the claim must
// never reappear as visible or hidden. Keyed by stable dedup keys (appid/title)
// + id so a purge survives feed id churn the same way dismissals do.
function purgedClaimKeysMap() {
  const m = state.personal.__purgedClaimKeys;
  return m && typeof m === 'object' && !Array.isArray(m) ? m : {};
}

function isClaimPurged(c) {
  if (!c) return false;
  const keyMap = purgedClaimKeysMap();
  if (c.id && keyMap[`id:${c.id}`]) return true;
  return claimDedupKeys(c).some(k => keyMap[k]);
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
  _claimDismissedSinceLoad = true;
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
  pruneDismissedClaims();
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
  closeClaimDetail();
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

export function purgeAllHiddenClaims() {
  const feedItems = state.claimableFeed?.items || [];
  const hidden = getHiddenClaims(feedItems);
  if (!hidden.length) {
    closeClaimPurgeConfirm();
    closeHiddenClaimsModal();
    return;
  }
  if (!state.personal.__purgedClaimKeys) state.personal.__purgedClaimKeys = {};
  const purgeMap = state.personal.__purgedClaimKeys;
  const idMap = state.personal.__dismissedClaims;
  const keyMap = state.personal.__dismissedClaimKeys;
  const now = Date.now();
  for (const claim of hidden) {
    if (claim.id) {
      purgeMap[`id:${claim.id}`] = now;
      if (idMap && idMap[claim.id] != null) delete idMap[claim.id];
    }
    for (const k of claimDedupKeys(claim)) {
      purgeMap[k] = now;
      if (keyMap && keyMap[k] != null) delete keyMap[k];
    }
  }
  savePersonal();
  applyVisibleClaims();
  renderClaimableModule();
  updateClaimableBanner();
  closeClaimPurgeConfirm();
  closeHiddenClaimsModal();
}

function pruneDismissedClaims() {
  // Intentionally no-op: cleared claims stay hidden until restored via the menu.
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

function claimOwnedReason(claim) {
  if (!claim) return null;
  const appid = claim.steam_appid;
  if (appid != null) {
    const sid = String(appid);
    const ownedAppids = state.ownedSteamAppids;
    if (ownedAppids instanceof Set) {
      if (ownedAppids.has(sid)) return 'owned-by-appid';
    } else {
      const appidMatched = state.allGames.some(g => g.store === 'steam' && String(g.appid ?? g.id) === sid)
        || state.allGames.some(g => gameKey(g) === `steam:${sid}`);
      if (appidMatched) return 'owned-by-appid';
    }
  }
  const norms = claimTitleNorms(claim.title);
  if (norms.some(n => state.ownedNormNames?.has(n))) return 'owned-by-title';
  return null;
}

export function isClaimOwned(claim) {
  return claimOwnedReason(claim) != null;
}

/** Debug-only: why a feed row is visible, hidden, or filtered out. */
export function claimDispositionReason(c, now = Date.now(), pro = isPro()) {
  if (!isClaimFeedItemValid(c)) return 'invalid';
  if (isClaimExpired(c, now)) return 'expired';
  const owned = claimOwnedReason(c);
  if (owned) return owned;
  if (isClaimDismissed(c)) return 'dismissed';
  if (c.premium_only && !pro) return 'premium-gated';
  return 'eligible';
}

function logClaimsFeedDebug(doc, source) {
  if (!isDebugEnabled()) return;
  const items = doc?.items || [];
  console.debug('[baklog-claims] feed loaded', {
    source,
    generated_at: doc?.generated_at ?? null,
    fetched_at: doc?.fetched_at ?? null,
    total: items.length,
    visible: state.claimableNow?.length ?? 0,
    owned: getOwnedClaims(items).length,
    dismissed: getHiddenClaims(items).length,
  });
}

function logClaimsDispositionDebug(items) {
  if (!isDebugEnabled()) return;
  const now = Date.now();
  const pro = isPro();
  console.debug('[baklog-claims] dispositions', (items || []).map((c) => ({
    id: c.id,
    store: c.store,
    source: c.source,
    title: c.title,
    disposition: claimDispositionReason(c, now, pro),
  })));
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

function isClaimFeedItemValid(c) {
  return !!(c?.id && c.store && hasValidClaimLinks(c));
}

function isClaimExpired(c, now = Date.now()) {
  if (!c?.ends_at) return false;
  const end = Date.parse(c.ends_at);
  return Number.isFinite(end) && end < now;
}

function isClaimEligible(c, now = Date.now()) {
  if (!isClaimFeedItemValid(c)) return false;
  if (isClaimExpired(c, now)) return false;
  if (isClaimOwned(c)) return false;
  return true;
}

export function getVisibleClaims(items) {
  const now = Date.now();
  const pro = isPro();
  const filtered = (items || []).filter((c) => {
    if (!isClaimEligible(c, now)) return false;
    if (isClaimPurged(c)) return false;
    if (isClaimDismissed(c)) return false;
    if (c.premium_only && !pro) return false;
    return true;
  });
  return sortClaims(dedupeClaims(filtered));
}

export function getHiddenClaims(items) {
  const now = Date.now();
  const pro = isPro();
  const filtered = (items || []).filter((c) => {
    if (!isClaimEligible(c, now)) return false;
    if (isClaimPurged(c)) return false;
    if (!isClaimDismissed(c)) return false;
    if (c.premium_only && !pro) return false;
    return true;
  });
  return sortClaims(dedupeClaims(filtered));
}

/** Feed items filtered out because they match a game already in the library. */
export function getOwnedClaims(items) {
  const now = Date.now();
  const filtered = (items || []).filter((c) => {
    if (!isClaimFeedItemValid(c)) return false;
    if (isClaimExpired(c, now)) return false;
    if (isClaimPurged(c)) return false;
    return isClaimOwned(c);
  });
  return sortClaims(dedupeClaims(filtered));
}

export function diffClaims(prevKeys, items) {
  const visible = getVisibleClaims(items);
  let newCount = 0;
  for (const c of visible) {
    // A claim is "new" only when neither its volatile feed id nor any of its
    // stable dedup keys was in the last acknowledged snapshot. Feed ids churn
    // between regenerations (epic-*→gamerpower-* after dedup/enrich), so an
    // id-only comparison reports already-acknowledged games as new and re-fires
    // the banner; the dedup-key match keeps an acknowledged claim acknowledged.
    const acknowledged = prevKeys.has(c.id) || claimDedupKeys(c).some(k => prevKeys.has(k));
    if (!acknowledged) newCount += 1;
  }
  return { newCount, visible };
}

export function loadClaimsSnapshotKeys() {
  try {
    const raw = localStorage.getItem(claimsSnapshotStorageKey());
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    const ids = Array.isArray(parsed?.ids) ? parsed.ids : [];
    const keys = Array.isArray(parsed?.keys) ? parsed.keys : [];
    return new Set([...ids, ...keys]);
  } catch {
    return new Set();
  }
}

export function saveClaimsSnapshot(items) {
  if (!items?.length) return;
  const visible = getVisibleClaims(items);
  const ids = visible.map(c => c.id);
  // Persist stable dedup keys (appid/title) alongside the volatile ids so a
  // later feed regeneration that re-keys the same game (id churn) still matches
  // the acknowledged snapshot and does not re-trigger the new-claims banner.
  const keys = [...new Set(visible.flatMap(c => claimDedupKeys(c)))];
  try {
    localStorage.setItem(claimsSnapshotStorageKey(), JSON.stringify({
      saved_at: Date.now(),
      ids,
      keys,
    }));
  } catch (_) { /* quota */ }
}

async function fetchHostedClaims() {
  const url = getClaimsEndpoint();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), CLAIMS_HOSTED_FETCH_MS);
  try {
    const res = await fetch(url, { cache: 'no-store', signal: ctrl.signal });
    if (!res.ok) throw new Error(`claims feed ${res.status}`);
    const doc = await res.json();
    return doc;
  } catch (err) {
    if (err?.name === 'AbortError') throw new Error('claims feed timeout');
    throw err;
  } finally {
    clearTimeout(timer);
  }
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

/** Content freshness for feed comparison — generated_at only (when the feed was built).

Profile fetcher copies hosted generated_at and stamps fetched_at at download time.
Using max(generated_at, fetched_at) made a just-downloaded stale hosted feed beat a
newer bundled fallback, dropping claims that only exist in the local build.
*/
export function feedGeneratedAt(doc) {
  const gen = Date.parse(doc?.generated_at || '');
  if (Number.isFinite(gen)) return gen;
  const fetched = Date.parse(doc?.fetched_at || '');
  return Number.isFinite(fetched) ? fetched : 0;
}

/** Prefer the feed with the newer generated_at when both have items. */
export function pickNewerFeed(primary, secondary) {
  const a = primary?.items?.length ? primary : null;
  const b = secondary?.items?.length ? secondary : null;
  if (!a) return b;
  if (!b) return a;
  return feedGeneratedAt(b) > feedGeneratedAt(a) ? b : a;
}

// Repair dismissals that were stored against only a volatile feed id (legacy
// data, or keys lost to a prior orphan-prune run). For every dismissed id that
// still matches a claim in the current feed, backfill the claim's stable dedup
// keys (appid: / title:) so the dismissal survives a future id churn even though
// the id-only entry alone would not.
function reconcileDismissedClaimKeys(feedItems) {
  const items = feedItems || [];
  if (!items.length) return;
  const idMap = dismissedClaimsMap();
  if (!Object.keys(idMap).length) return;
  let changed = false;
  const keyMap = state.personal.__dismissedClaimKeys
    && typeof state.personal.__dismissedClaimKeys === 'object'
    && !Array.isArray(state.personal.__dismissedClaimKeys)
    ? state.personal.__dismissedClaimKeys
    : {};
  for (const c of items) {
    if (!c?.id || idMap[c.id] == null) continue;
    for (const k of claimDedupKeys(c)) {
      if (keyMap[k] == null) {
        keyMap[k] = idMap[c.id];
        changed = true;
      }
    }
  }
  if (changed) {
    state.personal.__dismissedClaimKeys = keyMap;
    savePersonal();
  }
}

function applyFeedDoc(doc, source = 'unknown') {
  state.claimableFeed = doc && typeof doc === 'object' ? doc : null;
  state.libraryMeta.claims = state.claimableFeed;
  pruneDismissedClaims();
  reconcileDismissedClaimKeys(state.claimableFeed?.items || []);
  // A fresh feed resets the "show more" expansion so a stale, inflated slice
  // can't carry over after claims expire or the feed shrinks.
  _claimsVisibleCount = MAX_VISIBLE;
  // A fresh feed is a new "load", so the hero card is allowed again when it
  // happens to carry a single claim.
  _claimDismissedSinceLoad = false;
  applyVisibleClaims();
  logClaimsFeedDebug(state.claimableFeed, source);
}

function applyVisibleClaims() {
  const items = state.claimableFeed?.items || [];
  state.claimableNow = getVisibleClaims(items);
  logClaimsDispositionDebug(items);
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

/** Merge local, fallback, and hosted feeds using boot freshness rules. */
export function resolveClaimsFeedDoc(localDoc, fallbackDoc, hostedDoc, { preferHosted = false } = {}) {
  let doc = pickNewerFeed(localDoc, fallbackDoc);
  if (hostedDoc?.items?.length) {
    if (preferHosted || !doc?.items?.length) {
      doc = pickNewerFeed(doc, hostedDoc) || hostedDoc;
    } else {
      const hostedGen = feedGeneratedAt(hostedDoc);
      const docGen = feedGeneratedAt(doc);
      if (hostedGen - docGen >= HOSTED_BOOT_FRESHNESS_MS) {
        doc = hostedDoc;
      }
    }
  }
  if (!doc?.items?.length) doc = { generated_at: null, items: [] };
  return doc;
}

export async function loadClaimableNow({ preferHosted = false } = {}) {
  let localDoc = null;
  let localOk = false;
  let fallbackDoc = null;
  let fallbackOk = false;
  let hostedDoc = null;
  let hostedOk = false;
  try {
    localDoc = await loadLocalClaimsFile();
    localOk = localDoc != null;
  } catch (_) { /* offline */ }
  try {
    fallbackDoc = await loadBundledFallback();
    fallbackOk = fallbackDoc != null;
  } catch (_) { /* offline */ }

  try {
    hostedDoc = await fetchHostedClaims();
    hostedOk = true;
  } catch (_) { /* network */ }

  state.claimableFeedUnavailable = !(localOk || fallbackOk || hostedOk);

  const doc = resolveClaimsFeedDoc(localDoc, fallbackDoc, hostedDoc, { preferHosted });
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
  const actionHtml = `<button type="button" class="claim-hidden-restore-btn text-xs text-sky-300 hover:text-sky-200 px-2 py-1 rounded border border-slate-600 shrink-0" data-claim-restore="${escapeAttr(claim.id)}">Restore</button>`;
  return claimHiddenRowHtml(claim, { actionHtml });
}

function ownedClaimRowHtml(claim) {
  const actionHtml = '<span class="claim-owned-tag text-xs text-emerald-300 px-2 py-1 rounded border border-emerald-700/60 shrink-0">In library</span>';
  return claimHiddenRowHtml(claim, { actionHtml, rowClass: 'claim-owned-row' });
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
    ? `<div class="claim-hidden-section-head flex items-start justify-between gap-3 mt-2">
        <p class="claim-hidden-intro text-sm text-slate-400">Claims you cleared from notifications. Restore any you want to see again.</p>
        <button type="button" class="claim-hidden-clear-all-btn text-xs text-rose-300 hover:text-rose-200 px-2 py-1 rounded border border-rose-700/60 shrink-0" data-claim-purge-all>Clear all</button>
      </div>
      <div class="claim-hidden-list mt-3 space-y-2">${hidden.map(hiddenClaimRowHtml).join('')}</div>`
    : '';
  const ownedSection = owned.length
    ? `<div class="claim-owned-section mt-8 pt-6 border-t border-slate-700/60">
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

export function openClaimPurgeConfirm() {
  const dlg = document.getElementById('claimPurgeConfirmDialog');
  if (!dlg) return;
  dlg.innerHTML = `
    <form method="dialog" class="claim-detail-panel claim-purge-confirm-panel">
      <div class="claim-detail-header">
        <h2 class="claim-detail-title">Clear all hidden claims?</h2>
        <button type="submit" class="claim-detail-close" aria-label="Close">×</button>
      </div>
      <p class="claim-purge-confirm-body text-sm text-slate-300 mt-3">This permanently removes all hidden claims. This cannot be undone.</p>
      <div class="claim-purge-confirm-actions flex justify-end gap-2 mt-6">
        <button type="submit" class="claim-purge-cancel-btn text-sm text-slate-300 hover:text-slate-100 px-3 py-1.5 rounded border border-slate-600">Cancel</button>
        <button type="button" class="claim-purge-confirm-btn text-sm text-white px-3 py-1.5 rounded bg-rose-600 hover:bg-rose-500" data-claim-purge-confirm>Clear all</button>
      </div>
    </form>`;
  if (typeof dlg.showModal === 'function') {
    dlg.showModal();
    dlg.focus();
  }
}

export function closeClaimPurgeConfirm() {
  const dlg = document.getElementById('claimPurgeConfirmDialog');
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
  state.claimableNow = getVisibleClaims(feedItems);
  const claims = state.claimableNow;
  const hiddenCount = getHiddenClaims(feedItems).length;
  const ownedCount = getOwnedClaims(feedItems).length;
  const unavailable = state.claimableFeedUnavailable;
  const hide = !show || (!claims.length && !hiddenCount && !ownedCount && !unavailable);
  if (hide) {
    mount.classList.add('hidden');
    mount.innerHTML = '';
    return;
  }
  mount.classList.remove('hidden');
  const sponsoredItems = getAdsForLocation('claim-cards', { count: 3 });
  const sponsoredHtml = sponsoredItems.length
    ? `<div class="sponsored-claim-row">${sponsoredItems.map(sponsoredClaimCardHtml).join('')}</div>`
    : '';
  const emptyReason = unavailable && !claims.length ? 'unavailable' : 'empty';
  mount.innerHTML = sponsoredHtml + claimableModuleMarkup(claims, {
    visibleCount: _claimsVisibleCount,
    attribution: state.claimableFeed?.attribution,
    showHiddenButtonHtml: showHiddenClaimsButtonHtml(hiddenCount + ownedCount),
    allowHero: !_claimDismissedSinceLoad,
    emptyReason,
  });
  if (claims.length || sponsoredHtml) syncCoverFits(mount);
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
  const prevKeys = loadClaimsSnapshotKeys();
  const { newCount } = diffClaims(prevKeys, state.claimableFeed?.items || []);
  if (newCount <= 0) el.classList.add('hidden');
}

export function openClaimDetail(id) {
  const claim = (state.claimableFeed?.items || []).find(c => c.id === id)
    || state.claimableNow.find(c => c.id === id);
  const dlg = document.getElementById('claimDetailDialog');
  if (!claim || !dlg) return;
  dlg.innerHTML = claimDetailPanelHtml(claim, {
    owned: isClaimOwned(claim),
    attribution: state.claimableFeed?.attribution,
  });
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
  const finish = () => {
    if (finished) return; finished = true;
    commit();
  };
  el.addEventListener('transitionend', (ev) => { if (ev.propertyName === 'height') finish(); });
  setTimeout(() => finish(), 360); // fallback if transitionend never fires
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
    if (isSafeHttpUrl(claim?.claim_url)) {
      const outbound = affiliateUrl(claim.claim_url);
      if (isDebugEnabled()) {
        console.debug('[baklog-claims] claim open', {
          id: claim.id,
          store: claim.store,
          source: claim.source,
          claim_url: claim.claim_url,
          affiliateApplied: outbound !== claim.claim_url,
          outbound,
        });
      }
      window.open(outbound, '_blank', 'noopener,noreferrer');
    }
    return true;
  }
  const platformBtn = e.target.closest('[data-claim-go-ios], [data-claim-go-android]');
  if (platformBtn) {
    const id = platformBtn.dataset.claimGoIos || platformBtn.dataset.claimGoAndroid;
    const platform = platformBtn.dataset.claimGoIos ? 'ios' : 'android';
    const claim = (state.claimableFeed?.items || []).find(c => c.id === id)
      || state.claimableNow.find(c => c.id === id);
    const urls = normalizeClaimUrls(claim?.claim_urls);
    const target = urls[platform];
    if (isSafeHttpUrl(target)) {
      const outbound = affiliateUrl(target);
      if (isDebugEnabled()) {
        console.debug('[baklog-claims] claim open', {
          id: claim.id,
          store: claim.store,
          source: claim.source,
          platform,
          claim_url: target,
          affiliateApplied: outbound !== target,
          outbound,
        });
      }
      window.open(outbound, '_blank', 'noopener,noreferrer');
    }
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
  // Lightweight hosted-feed poll (default 15 min). Separate from the fetcher
  // chip auto-refresh (maybeAutoRefreshClaims, 30–360 min) which re-downloads
  // profiles/<id>/free_claims.json via fetch_free_claims.py. Both can show the
  // new-claims banner; saveClaimsSnapshot dedupes by visible claim ids.
  if (_readOnlyPollTimer) return;
  _readOnlyPollTimer = setInterval(async () => {
    if (document.visibilityState !== 'visible') return;
    const prevKeys = loadClaimsSnapshotKeys();
    try {
      await loadClaimableNow({ preferHosted: true });
      const { newCount } = diffClaims(prevKeys, state.claimableFeed?.items || []);
      if (newCount > 0) showClaimableBanner(newCount);
      saveClaimsSnapshot(state.claimableFeed?.items || []);
      refreshClaimableUi();
    } catch (_) { /* silent */ }
  }, intervalMs);
}
