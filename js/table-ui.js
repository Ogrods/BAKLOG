import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import { beginRowLoader, endRowLoader, forceHideRowLoader, isViewOverlayVisible } from './loading-curtain.js';
import { deferTableRender, isTableDataView } from './render-gate.js';
import { noteTableRender, noteTableRenderSkipped } from './propagation-trace.js';
import { isSurfaceAnimating } from './library-count-animation.js';
import {
  collectTableParams,
  queryGames,
  queryGamesAsync,
  buildQueryContext,
  querySourceForView,
} from './table-query.js';
import { safeCoverAttrUrl, safeCoverCssUrl } from './covers.js';
import { buildStatusSelect, STATUS_LABELS } from './row-templates.js';
import {
  gameKey,
  alphaBucket,
  isHiddenGem,
  coverFallbackFor,
  libraryCoverFor,
  storeLinkHtml,
  storeUrlForGame,
  storeBadgeHtml,
  wishlistBadgeHtml,
  wishlistStatusSelectHtml,
  coopPillsHtml,
  trophyProgressPillHtml,
  platinumBadgeHtml,
  staleBadgeHtml,
  earlyAccessRibbonHtml,
  earlyAccessPillHtml,
  priorityScore,
  formatHours,
  formatDate,
  formatReleaseDate,
  itchIsGame,
  findGameByKey,
  getSameTitleKeys,
  renderBulkStatusButtons,
  recomputeCrossStoreHidden,
  combinedPlaytime,
  combinedPlaytimeTooltip,
  psnPlatformsLineHtml,
} from './game-core.js';
import {
  isCleanupCandidate,
  isOwnedByTitle,
  getDealInfo,
} from './deals.js';
import { isPlatformToken } from './genres.js';
import { syncCoverFits } from './covers.js';
import { getAdsForLocation, pickLocationForView, rotateLocationAd, sponsoredTableRowHtml } from './sponsored-deals.js';
import {
  getPersonal,
  setPersonal,
  savePersonal,
  bumpPersonalMemo,
  removeManualGame,
  loadManualGames,
  saveManualGames,
  setGameHidden,
  countUserHiddenWishlist,
  countsInLibraryTotal,
  countedLibraryDenominator,
  addNintendoDroppedId,
  NINTENDO_DROPPED_KEY,
} from './personal-storage.js';
import { refreshAfterManualChange } from './library-load.js';
import { getCoopFilterMode } from './prefs.js';
import { renderSummary, switchView, hideViewLoading } from './filters-ui.js';
import { buildTableEmptyStateHtml } from './table-empty-state.js';
import { visibleItchGames } from './connections-status.js';
import { formatPrice } from './table-price-format.js';

export { formatPrice };
import { renderPicks, effectivePicksTab } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
// dashboard-drilldown imports from table-ui already; the cycle is safe because
// both sides only invoke each other's functions inside click-time bodies.
import { dashResetLibraryFiltersExceptDedup } from './dashboard-drilldown.js';
import {
  isTablePerfEnabled,
  perfBeginRun,
  perfMark,
  perfMeasure,
  perfChunk,
  perfEndRun,
  perfActiveRun,
} from './table-perf.js';
import { applyColumnVisibility } from './table-columns.js';
import {
  observeTableDensity,
  scheduleTableDensitySync,
  syncTableDensity,
} from './table-density.js';
import { notesAffordanceHtml } from './notes-dialog.js';

// === Alpha nav + scroll ===
export function initAlphaNav() {
  const nav = document.getElementById("alphaNav");
  if (!nav || nav.dataset.built) return;
  const letters = ["#", ..."ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("")];
  nav.innerHTML = letters.map(l => {
    const letter = l;
    const title = letter === "#" ? "Jump to non-letter titles" : `Jump to ${letter}`;
    return `<button type="button" class="alpha-nav-btn" data-letter="${letter}" title="${title}">${letter}</button>`;
  }).join("");
  nav.dataset.built = "1";
  nav.addEventListener("click", e => {
    const btn = e.target.closest(".alpha-nav-btn");
    if (!btn || btn.disabled) return;
    jumpToLetter(btn.dataset.letter);
  });
  ensureVirtualScrollBound();
}

/** Letter set is recomputed only when the filtered list identity changes —
 *  buildAlphaNav runs on every renderTable, so the 1700-name scan was the
 *  hidden cost inside post:bulk-alpha-focus. */
let _alphaListRef = null;
let _alphaLetterSet = null;
function buildAlphaNav(list) {
  const nav = document.getElementById("alphaNav");
  if (!nav) return;
  if (_alphaListRef !== list) {
    const letters = new Set();
    for (let i = 0; i < list.length; i++) letters.add(alphaBucket(list[i].name));
    _alphaListRef = list;
    _alphaLetterSet = letters;
  }
  const letters = _alphaLetterSet;
  nav.querySelectorAll(".alpha-nav-btn").forEach(btn => {
    const enabled = letters.has(btn.dataset.letter);
    btn.classList.toggle("enabled", enabled);
    btn.disabled = !enabled;
  });
}

/** Scroll so the row sits slightly above vertical center (readable under sticky chrome). */
function scrollRowToCenter(row, { smooth = true } = {}) {
  if (!row) return;
  // Compute the target scroll position in one shot so the user never sees a
  // two-step "center, then nudge up" jump — that was the post-paint snap when
  // landing from a dashboard drill-in.
  const rect = row.getBoundingClientRect();
  const rowCenterY = rect.top + window.scrollY + rect.height / 2;
  // Aim ~42% from the top of the viewport, accounting for the sticky table
  // header so the focused row clears it.
  const target = Math.max(0, rowCenterY - window.innerHeight * 0.42);
  window.scrollTo({ top: target, behavior: smooth ? "smooth" : "auto" });
}

function markFocusedRow(key) {
  document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
  document.querySelectorAll("tr.row-picked").forEach(r => r.classList.remove("row-picked"));
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) {
    row.classList.add("row-focused", "row-picked");
    preloadRowHeroEl(row);
  }
  return row;
}

export function scrollToRowIndex(idx, { smooth = false } = {}) {
  const list = state._visibleList || sortedGames(filteredGames());
  if (!list.length || idx < 0 || idx >= list.length) return;
  setRowAdAnchor(idx);
  const key = gameKey(list[idx]);
  const useSmooth = smooth && list.length <= FIRST_CHUNK;
  setPendingScrollTarget({
    kind: "row",
    key,
    smooth: useSmooth,
  });
  state.focusedRowIndex = idx;
  state.pickedKey = key;

  if (!usesVirtualScroll(list)) {
    const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
    if (!row) {
      const tbody = document.getElementById("tbody");
      if (tbody) {
        const ctx = { isWish: state.activeView === "wishlist" };
        const rendered = tbodyRowCount();
        if (idx + 1 - rendered > 0 && idx + 1 - rendered <= FIRST_CHUNK) {
          tbody.insertAdjacentHTML("beforeend", appendChunk(list, rendered, idx + 1, ctx));
          timeSyncCoverFits(tbody);
        }
      }
    }
  }

  consumePendingScrollTarget(list);
}

function jumpToLetter(letter) {
  const list = state._visibleList || sortedGames(filteredGames());
  const idx = list.findIndex(g => alphaBucket(g.name) === letter);
  if (idx < 0) return;
  scrollToRowIndex(idx);
}

export function filteredGames() {
  return state._visibleList || [];
}

export function visibleListForKeyboard() {
  return sortedGames(filteredGames());
}

export function sortedGames(list) {
  return list;
}

// === Selection & bulk ===
export function updateBulkBar() {
  renderBulkStatusButtons();
  const bar = document.getElementById("bulkBar");
  const n = state.selectedKeys.size;
  document.getElementById("bulkCount").textContent = `${n} selected`;
  const show = n > 0 && state.activeView !== "dashboard";
  bar.classList.toggle("hidden", !show);
  document.body.classList.toggle("bulk-bar-open", show);
}

export function toggleSelection(key, on) {
  if (on) state.selectedKeys.add(key);
  else state.selectedKeys.delete(key);
  updateBulkBar();
}

// === Undo (mutation history) ===
// Targets accidental mass mutations like the "Set 1700+ games to Playing"
// faceplant. Each entry: { label, undo, ts }. Ctrl+Z (or the toast button)
// runs `undo()` which restores previous state. Bounded stack so we never
// hold onto stale snapshots.
const UNDO_LIMIT = 20;
const UNDO_TOAST_MS = 12000;
const _undoStack = [];
let _undoToastTimer = null;

function pushUndo({ label, undo }) {
  if (typeof undo !== "function") return;
  _undoStack.push({ label, undo, ts: Date.now() });
  while (_undoStack.length > UNDO_LIMIT) _undoStack.shift();
  showUndoToast(label);
}

/** Snapshot personal keys, push undo that restores them (for hidden-panel restore, etc.). */
export function pushPersonalUndo({ label, keys, afterUndo }) {
  const snap = snapshotPersonalForKeys(keys);
  pushUndo({
    label,
    undo: () => {
      restorePersonalFromSnapshot(snap);
      if (typeof window.updateHiddenGamesMenuCount === "function") window.updateHiddenGamesMenuCount();
      afterUndo?.();
    },
  });
}

export function performUndo() {
  const entry = _undoStack.pop();
  if (!entry) return false;
  try { entry.undo(); } catch (err) { console.error("[undo] failed", err); }
  hideUndoToast();
  return true;
}

export function canUndo() {
  return _undoStack.length > 0;
}

export function hideUndoToast() {
  const el = document.getElementById("undoToast");
  if (!el) return;
  el.classList.add("hidden");
  el.innerHTML = "";
  if (_undoToastTimer) { clearTimeout(_undoToastTimer); _undoToastTimer = null; }
}

function showUndoToast(label) {
  const el = document.getElementById("undoToast");
  if (!el) return;
  el.innerHTML = `
    <span class="undo-toast-label">${escapeHtml(label)}<span class="undo-toast-shortcut">Ctrl+Z</span></span>
    <button type="button" data-undo-action="undo" title="Undo last status change (Ctrl+Z)">Undo</button>
    <button type="button" class="undo-toast-dismiss" data-undo-action="dismiss" aria-label="Dismiss" title="Dismiss undo toast">×</button>
  `;
  el.classList.remove("hidden");
  if (_undoToastTimer) clearTimeout(_undoToastTimer);
  _undoToastTimer = setTimeout(hideUndoToast, UNDO_TOAST_MS);
}

function snapshotPersonalForKeys(keys) {
  // Deep-clone affected entries (or capture "absent" so undo can re-delete).
  const snap = new Map();
  for (const key of keys) {
    const cur = state.personal[key];
    snap.set(key, cur ? JSON.parse(JSON.stringify(cur)) : null);
  }
  return snap;
}

function restorePersonalFromSnapshot(snap) {
  for (const [key, prev] of snap) {
    if (prev === null) delete state.personal[key];
    else state.personal[key] = prev;
  }
  window._dataVersion = (window._dataVersion || 0) + 1;
  bumpPersonalMemo();
  savePersonal();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  renderTable();
  renderSummary();
  renderPicks();
  if (state.activeView === "dashboard") scheduleDashboardRender();
}

export function bulkSetStatus(status) {
  const affectedKeys = [...state.selectedKeys];
  if (!affectedKeys.length) return;
  const snap = snapshotPersonalForKeys(affectedKeys);
  for (const key of affectedKeys) {
    const g = findGameByKey(key);
    if (g) setPersonal(g, "status", status);
  }
  state.selectedKeys.clear();
  updateBulkBar();
  invalidateTableCache();
  renderTable();
  const statusLabel = (STATUS_LABELS && STATUS_LABELS[status]) || status;
  pushUndo({
    label: `Set ${affectedKeys.length} game${affectedKeys.length === 1 ? "" : "s"} to ${statusLabel}`,
    undo: () => restorePersonalFromSnapshot(snap),
  });
}

function snapshotRemoveState(keys) {
  // Hiding a pulled row mirrors the hidden flag across same-title keys and adds
  // its title norm to __hidden_title_norms_v1. Capture both so undo fully
  // reverses the hide — otherwise applyHiddenTitleNorms re-hides the row on the
  // next merge and the "Removed N games" undo silently leaves it hidden.
  const expanded = new Set(keys);
  for (const key of keys) {
    const g = findGameByKey(key);
    if (g) for (const k of getSameTitleKeys(g)) expanded.add(k);
  }
  expanded.add('__hidden_title_norms_v1');
  expanded.add(NINTENDO_DROPPED_KEY);
  const personalSnap = snapshotPersonalForKeys(expanded);
  const manualSnap = [];
  for (const key of keys) {
    const g = findGameByKey(key);
    if (g?.manual) manualSnap.push(JSON.parse(JSON.stringify(g)));
  }
  return { personalSnap, manualSnap };
}

function restoreRemoveSnapshot({ personalSnap, manualSnap }) {
  restorePersonalFromSnapshot(personalSnap);
  const manual = loadManualGames();
  const restored = [...manualSnap];
  const restoredKeys = new Set(manualSnap.map(g => `${g.store}:${g.id}`));
  for (const m of manual) {
    const k = `${m.store}:${m.id}`;
    if (!restoredKeys.has(k)) restored.push(m);
  }
  saveManualGames(restored);
  refreshAfterManualChange();
}

export function bulkRemove() {
  const affectedKeys = [...state.selectedKeys];
  if (!affectedKeys.length) return;
  let customCount = 0;
  let pulledCount = 0;
  for (const key of affectedKeys) {
    const g = findGameByKey(key);
    if (g?.manual) customCount++;
    else pulledCount++;
  }
  const parts = [];
  if (customCount) parts.push(`${customCount} custom`);
  if (pulledCount) parts.push(`${pulledCount} hidden`);
  const detail = parts.length ? ` (${parts.join(", ")})` : "";
  const ok = confirm(
    `Remove ${affectedKeys.length} game${affectedKeys.length === 1 ? "" : "s"}${detail}?\n\n` +
    "Custom entries are deleted. Pulled entries are hidden and can be restored from the kebab menu.",
  );
  if (!ok) return;
  const snap = snapshotRemoveState(affectedKeys);
  for (const key of affectedKeys) {
    const g = findGameByKey(key);
    if (!g) continue;
    if (g.manual) {
      removeManualGame(g.store, g.id);
      delete state.personal[key];
    } else {
      if (g.store === 'nintendo') {
        addNintendoDroppedId(g.nintendo_id ?? g.id, { silent: true });
      }
      setGameHidden(g, true, { silent: true });
    }
  }
  savePersonal();
  bumpPersonalMemo();
  state.selectedKeys.clear();
  updateBulkBar();
  invalidateTableCache();
  recomputeCrossStoreHidden();
  refreshAfterManualChange();
  renderTable();
  renderSummary();
  renderPicks();
  if (state.activeView === "dashboard") scheduleDashboardRender();
  if (typeof window.updateHiddenGamesMenuCount === "function") window.updateHiddenGamesMenuCount();
  pushUndo({
    label: `Removed ${affectedKeys.length} game${affectedKeys.length === 1 ? "" : "s"}`,
    undo: () => {
      restoreRemoveSnapshot(snap);
      if (typeof window.updateHiddenGamesMenuCount === "function") window.updateHiddenGamesMenuCount();
    },
  });
}

const _pendingFlashKeys = new Set();

function applyRowFlash(key) {
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (!row) return false;
  row.classList.add("row-flash");
  setTimeout(() => row.classList.remove("row-flash"), 2000);
  _pendingFlashKeys.delete(key);
  return true;
}

export function flashGameRow(key) {
  _pendingFlashKeys.add(key);
  focusGame(key);
  requestAnimationFrame(() => {
    if (!applyRowFlash(key) && _pendingFlashKeys.has(key)) {
      setTimeout(() => applyRowFlash(key), 100);
    }
  });
}

// === Row helpers ===
export function updateHasNotesIndicatorInPlace(tr, g) {
  if (!tr) return;
  const meta = tr.querySelector(".row-meta");
  if (!meta) return;
  const key = gameKey(g);
  meta.querySelectorAll(".has-notes-dot, .notes-open-btn").forEach((n) => n.remove());
  meta.insertAdjacentHTML("beforeend", notesAffordanceHtml(key, getPersonal(g).notes));
}

export function updateRowInPlace(tr, g) {
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const key = gameKey(g);
  const selected = state.selectedKeys.has(key);
  const focused = tr.classList.contains("row-focused");
  const { heroClass, heroStyle } = rowHeroAttrs(g);
  tr.className = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}${heroClass}`;
  if (heroStyle) tr.setAttribute('style', heroStyle);
  else tr.removeAttribute('style');
  if (cleanup) tr.title = 'Cleanup candidate: tagged backlog, 0h, rated under 60%, 2+ yrs old';
  else tr.removeAttribute('title');
}

function rowHeroAttrs(g) {
  const hero = coverFallbackFor(g);
  const safe = safeCoverCssUrl(hero);
  if (!safe) return { heroClass: '', heroStyle: '' };
  return {
    heroClass: ' row-has-hero',
    heroStyle: `--row-hero:url('${safe}')`,
  };
}

function rowClass(g, lowConf) {
  const status = getPersonal(g).status;
  const stateClass = status === "next" ? "status-next" : status === "playing" ? "status-playing" : status === "unfinished" ? "status-unfinished" : status === "live" ? "status-live" : status === "finished" ? "status-finished" : status === "skip" ? "status-skip" : "";
  const lowClass = lowConf ? " low-confidence" : "";
  const picked = state.pickedKey === gameKey(g) ? " row-picked" : "";
  return `bg-slate-800/50 hover:bg-slate-700/50 ${stateClass}${lowClass}${picked}`;
}

function hltbLabel(g) {
  const p = getPersonal(g);
  if (p.hltb_override != null && p.hltb_override !== "") return `${p.hltb_override}* / - / -`;
  const m = g.hltb_main_hours ?? "-";
  const e = g.hltb_main_extra_hours ?? "-";
  const c = g.hltb_completionist_hours ?? "-";
  return `${m} / ${e} / ${c}`;
}

// === Focus helpers ===
/** @typedef {{ kind: 'row'|'toolbar', key?: string, idx?: number, smooth?: boolean, hideOverlay?: boolean, consumed?: boolean }} PendingScrollTarget */

let _pendingScrollTarget = null;
let _lastConsumeWasSmooth = false;
let _chromeScrollObs = null;

const SPONSORED_TABLE_SLOT = 5;
const ROW_AD_DRILL_OFFSET = 1;
let _rowAdAnchorIndex = null;

export function setRowAdAnchor(idx) {
  if (typeof idx === 'number' && idx >= 0) _rowAdAnchorIndex = idx;
  else _rowAdAnchorIndex = null;
}

export function clearRowAdAnchor() {
  _rowAdAnchorIndex = null;
}

function resolveSponsoredTableSlot(total) {
  if (!total) return 0;
  if (_rowAdAnchorIndex != null) {
    return Math.min(total - 1, Math.max(0, _rowAdAnchorIndex - ROW_AD_DRILL_OFFSET));
  }
  return total > SPONSORED_TABLE_SLOT ? SPONSORED_TABLE_SLOT : Math.max(0, total - 1);
}

/** Vitest hook for sponsored row ad slot resolution. */
export function sponsoredTableSlotForTest(total) {
  return resolveSponsoredTableSlot(total);
}

function disconnectChromeScrollObs() {
  if (_chromeScrollObs) {
    _chromeScrollObs.disconnect();
    _chromeScrollObs = null;
  }
}

export function setPendingScrollTarget(target) {
  if (!target) {
    _pendingScrollTarget = null;
    disconnectChromeScrollObs();
    return;
  }
  if (target.kind === 'toolbar') clearRowAdAnchor();
  _pendingScrollTarget = {
    consumed: false,
    smooth: false,
    hideOverlay: false,
    ...target,
  };
}

export function cancelPendingScrollTarget() {
  _pendingScrollTarget = null;
  disconnectChromeScrollObs();
}

export function hasPendingScrollTarget() {
  return !!(_pendingScrollTarget && !_pendingScrollTarget.consumed);
}

function scrollToToolbarAnchor({ smooth = false } = {}) {
  const toolbar = document.getElementById("toolbarSection");
  if (!toolbar) {
    window.scrollTo(0, 0);
    return;
  }
  const rect = toolbar.getBoundingClientRect();
  const targetY = Math.max(0, rect.top + window.scrollY - 12);
  window.scrollTo({ top: targetY, behavior: smooth ? "smooth" : "auto" });
}

function ensureRowPaintedForScroll(list, idx, key) {
  if (!list?.length || idx < 0 || !key) return null;
  let row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) return row;
  if (usesVirtualScroll(list) && _virtualList === list) {
    const { start, end } = computeVirtualRange(list.length, idx);
    paintVirtualSlice(start, end);
    row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  }
  return row;
}

function completeDrillOverlayIfNeeded(hideOverlay) {
  if (hideOverlay || state._drillHideOverlay) {
    state._drillHideOverlay = false;
    hideViewLoading();
  }
}

/** Consume the pending scroll target exactly once after layout has settled. */
export function consumePendingScrollTarget(list = state._visibleList) {
  const t = _pendingScrollTarget;
  if (!t || t.consumed) return false;

  if (t.kind === "toolbar") {
    if (!isToolbarScrollReady()) {
      scheduleScrollAfterChromeSettled();
      return false;
    }
    disconnectChromeScrollObs();
    scrollToToolbarAnchor({ smooth: !!t.smooth });
    t.consumed = true;
    _pendingScrollTarget = null;
    completeDrillOverlayIfNeeded(t.hideOverlay);
    return true;
  }

  if (t.kind === "row") {
    // Cross-view drills: wait for picks/summary chrome like toolbar drills.
    if (t.hideOverlay && !isToolbarScrollReady()) {
      scheduleScrollAfterChromeSettled();
      return false;
    }
    const key = t.key;
    if (!key || !Array.isArray(list) || !list.length) {
      t.consumed = true;
      _pendingScrollTarget = null;
      return false;
    }
    const idx = list.findIndex(g => gameKey(g) === key);
    if (idx < 0) {
      console.warn("[consumePendingScrollTarget] row not in list", { key, listLen: list.length });
      t.consumed = true;
      _pendingScrollTarget = null;
      completeDrillOverlayIfNeeded(t.hideOverlay);
      return false;
    }
    t.idx = idx;
    state.pickedKey = key;
    state.focusedRowIndex = idx;
    setRowAdAnchor(idx);

    const row = ensureRowPaintedForScroll(list, idx, key);
    const phone = isTablePhoneLayout();
    if (phone && row) {
      // Variable-height card rows: live rect beats idx * rh spacer math.
      markFocusedRow(key);
      refreshMeasuredRowHeight(row.parentElement);
      scrollRowToCenter(row, { smooth: !!t.smooth });
      if (_pendingFlashKeys.has(key)) applyRowFlash(key);
    } else if (usesVirtualScroll(list)) {
      // Virtual lists: position by deterministic index math (top-spacer height +
      // measured row height) instead of the freshly-painted row's rect. The giant
      // top spacer isn't always laid out when we measure two rAF after paint, so a
      // getBoundingClientRect read can land the drill "much too high" near the top
      // of the page. This mirrors the anchor-paint path that dashboard drills use.
      scrollToVirtualRowIndex(idx, { behavior: t.smooth ? "smooth" : "auto" });
      if (row) markFocusedRow(key);
      if (_pendingFlashKeys.has(key)) applyRowFlash(key);
    } else if (row) {
      markFocusedRow(key);
      scrollRowToCenter(row, { smooth: !!t.smooth });
      if (_pendingFlashKeys.has(key)) applyRowFlash(key);
    }

    _lastConsumeWasSmooth = !!t.smooth && !!row && (phone || !usesVirtualScroll(list));
    t.consumed = true;
    _pendingScrollTarget = null;
    completeDrillOverlayIfNeeded(t.hideOverlay);
    return true;
  }
  return false;
}

/** Two rAF ticks after layout, then consume the pending scroll target once. */
export function scheduleScrollAfterLayoutSettled() {
  const t = _pendingScrollTarget;
  if (!t || t.consumed) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      consumePendingScrollTarget(state._visibleList);
    });
  });
}

/** Category / cross-view drills: wait for summary/picks chrome before scrolling. */
export function scheduleScrollAfterChromeSettled() {
  const t = _pendingScrollTarget;
  if (!t || t.consumed || (t.kind !== 'toolbar' && t.kind !== 'row')) {
    scheduleScrollAfterLayoutSettled();
    return;
  }

  disconnectChromeScrollObs();

  const tryConsume = () => {
    if (!_pendingScrollTarget || _pendingScrollTarget.consumed) {
      disconnectChromeScrollObs();
      return;
    }
    if (isToolbarScrollReady()) {
      disconnectChromeScrollObs();
      scheduleScrollAfterLayoutSettled();
    }
  };

  const picks = document.getElementById('picksSection');
  const toolbar = document.getElementById('toolbarSection');
  const summary = document.getElementById('summary');
  const viewHouse = document.getElementById('viewHouseSlot');
  const wishRadar = document.getElementById('wishlistDealRadar');
  if (!picks || !toolbar || typeof ResizeObserver !== 'function') {
    const run = () => scheduleScrollAfterLayoutSettled();
    if (typeof requestIdleCallback === 'function') requestIdleCallback(run, { timeout: 800 });
    else setTimeout(run, 0);
    return;
  }

  _chromeScrollObs = new ResizeObserver(() => {
    requestAnimationFrame(tryConsume);
  });
  _chromeScrollObs.observe(picks);
  _chromeScrollObs.observe(toolbar);
  if (summary) _chromeScrollObs.observe(summary);
  if (viewHouse) _chromeScrollObs.observe(viewHouse);
  if (wishRadar) _chromeScrollObs.observe(wishRadar);
  requestAnimationFrame(() => requestAnimationFrame(tryConsume));
}

const CHROME_BAND_ABOVE_TOOLBAR = ['viewHouseSlot', 'wishlistDealRadar'];

function isChromeBandAboveToolbarSettled(toolbarTop) {
  for (const id of CHROME_BAND_ABOVE_TOOLBAR) {
    const el = document.getElementById(id);
    if (!el || el.classList.contains('hidden')) continue;
    const hasContent = el.innerHTML.trim().length > 0;
    if (hasContent && el.offsetHeight < 8) return false;
    const bottom = el.offsetTop + el.offsetHeight;
    if (bottom > 0 && toolbarTop > 0 && toolbarTop < bottom - 2) return false;
  }
  return true;
}

function scrollDeferredToRefreshFilterUI() {
  return hasPendingToolbarScroll();
}

export function hasPendingToolbarScroll() {
  return _pendingScrollTarget?.kind === 'toolbar' && !_pendingScrollTarget?.consumed;
}

/** Toolbar scroll must not run until library chrome + overlay have fully settled. */
function isToolbarScrollReady() {
  if (!isTableDataView(state.activeView)) return false;
  if (isViewOverlayVisible()) return false;
  const toolbar = document.getElementById('toolbarSection');
  if (!toolbar || toolbar.classList.contains('hidden')) return false;
  const picks = document.getElementById('picksSection');
  if (!picks || picks.classList.contains('hidden')) return false;
  if (picks.offsetHeight < 24) return false;
  const picksTop = picks.offsetTop;
  const toolbarTop = toolbar.offsetTop;
  if (picksTop > 0 && toolbarTop > 0) {
    if (toolbarTop < picksTop + picks.offsetHeight - 4) return false;
    if (!isChromeBandAboveToolbarSettled(toolbarTop)) return false;
    const toolbarRectTop = toolbar.getBoundingClientRect().top;
    if (window.scrollY < 16 && toolbarRectTop < 80) return false;
  }
  return true;
}

export function focusGame(key) {
  state.pickedKey = key;
  const targetIsWishlist = String(key).startsWith("wishlist:");
  const targetIsItch = String(key).startsWith("itch:");
  const targetView = targetIsWishlist ? "wishlist" : targetIsItch ? "itch" : "library";
  const crossingView = state.activeView !== targetView;

  const targetList = crossingView ? null : visibleListForKeyboard();
  const alreadyVisible = targetList && targetList.findIndex(g => gameKey(g) === key) >= 0;
  if (!alreadyVisible) {
    dashResetLibraryFiltersExceptDedup();
  }

  if (crossingView) {
    state._pendingFocusKey = key;
    state._drillHideOverlay = true;
    setPendingScrollTarget({ kind: "row", key, smooth: false, hideOverlay: true });
    switchView(targetView);
    return;
  }

  const list = visibleListForKeyboard();
  const idx = list.findIndex(g => gameKey(g) === key);
  if (idx < 0) {
    console.warn('[focusGame] key not found in visible list even after filter reset', { key, view: state.activeView, listLen: list.length });
    state._pendingFocusKey = key;
    setPendingScrollTarget({ kind: "row", key, smooth: false });
    renderTable({ force: true });
    return;
  }
  state.focusedRowIndex = idx;
  setPendingScrollTarget({ kind: "row", key, idx, smooth: true });

  const existing = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (existing) {
    markFocusedRow(key);
    consumePendingScrollTarget(list);
    return;
  }
  state._pendingFocusKey = key;
  renderTable({ force: true, anchorIndex: idx });
}

function consumePendingFocus(list) {
  const key = state._pendingFocusKey;
  if (!key) return;
  state._pendingFocusKey = null;
  const idx = list.findIndex(g => gameKey(g) === key);
  const run = perfActiveRun();
  if (run) run.meta.pendingKeyFound = idx >= 0;
  if (idx < 0) {
    console.warn('[consumePendingFocus] pending key not in painted list - anchor lost', {
      key,
      view: state.activeView,
      listLen: list.length,
    });
    cancelPendingScrollTarget();
    completeDrillOverlayIfNeeded(true);
    return;
  }
  state.pickedKey = key;
  state.focusedRowIndex = idx;
  if (_pendingScrollTarget?.kind === "row" && !_pendingScrollTarget.consumed) {
    _pendingScrollTarget.key = key;
    _pendingScrollTarget.idx = idx;
  }
  ensureRowPaintedForScroll(list, idx, key);
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) markFocusedRow(key);
  if (run) run.meta.anchorPrepared = true;
}

export function focusRow(key) {
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (!row) return;
  document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
  row.classList.add("row-focused");
  preloadRowHeroEl(row);
}

export function openStoreForFocused() {
  const list = visibleListForKeyboard();
  const g = list[state.focusedRowIndex];
  if (!g) return;
  const url = storeUrlForGame(g);
  if (url) window.open(url, "_blank", "noopener");
}

// === Table fingerprint / cache ===
let _tableFingerprint = "";
let _lastRenderedView = null;

/**
 * Lets filters-ui's switchView check whether the table cache already covers
 * the target view at the supplied fingerprint without exposing the private
 * cache variables.
 */
export function isViewCached(view, fpForView) {
  return view === _lastRenderedView && fpForView === _tableFingerprint;
}

export function tableFingerprint() {
  const sp = state.sessionPrefs || {};
  return JSON.stringify({
    v: state.activeView,
    sk: state.sortKey, sd: state.sortDir,
    // The 6 live-filter controls live in state.sessionPrefs (single source of
    // truth — DOM mirrors state). Reading them here means the fingerprint
    // changes whenever the user (or a drill-in) touches search, status,
    // unplayed/early-access, or the rating/hours sliders.
    q: String(sp.search || "").trim().toLowerCase(),
    sf: sp.statusFilter || "",
    minR: +(sp.minRating || 0),
    maxH: sp.maxHours == null ? 200 : +sp.maxHours,
    unp: !!sp.unplayedOnly,
    ea: !!sp.earlyAccessOnly,
    stale: !!sp.staleOnly,
    store: state.prefs.storeFilter || "",
    wstore: state.prefs.wishlistStoreFilter || "",
    customList: state.prefs.customListFilter ?? null,
    releaseYear: state.prefs.releaseYearFilter || "",
    hltbBucket: state.prefs.hltbBucket ?? null,
    gen: state.prefs.genreFilters || [],
    gm: state.prefs.genreFilterMode,
    deal: [state.prefs.dealOnSaleOnly, state.prefs.dealHistoricalLowOnly, state.prefs.dealHideOwned, state.prefs.dealMinDiscount, state.prefs.dealMaxPrice],
    coop: getCoopFilterMode(),
    cleanup: !!state.cleanupModeActive,
    dedupe: !!state.sessionPrefs.crossStoreDedup,
    ihng: !!state.sessionPrefs.itchHideNonGames,
    lib: state.allGames.length,
    wl: state.wishlistGames.length,
    itch: state.itchGames.length,
    dv: window._dataVersion || 0,
  });
}

export function invalidateTableCache() {
  cancelPendingScrollTarget();
  forceHideRowLoader();
  _tableFingerprint = "";
  state._visibleList = null;
  state._visibleListView = null;
  _lastRenderedView = null;
  _renderTableGen++;
  cancelPaintJobs();
  _virtualList = null;
  _virtualCtx = null;
  _virtualWindow = { start: 0, end: 0 };
  _virtualWindowList = null;
  _alphaListRef = null;
  _alphaLetterSet = null;
  const tbody = document.getElementById("tbody");
  if (tbody) tbody.innerHTML = "";
}

/** Survives invalidateTableCache so a drill-back-to-library doesn't re-query 1700 rows. */
const _queryResultCache = new Map();
const QUERY_CACHE_MAX = 4;
export function clearQueryResultCache() {
  _queryResultCache.clear();
}
function rememberQueryResult(fp, list) {
  if (!fp) return;
  if (_queryResultCache.has(fp)) _queryResultCache.delete(fp);
  _queryResultCache.set(fp, list);
  while (_queryResultCache.size > QUERY_CACHE_MAX) {
    const oldest = _queryResultCache.keys().next().value;
    _queryResultCache.delete(oldest);
  }
}

/** Warm query cache for another view during idle (library tab → faster wishlist switch). */
export async function prewarmTableQueryForView(view) {
  if (!state.dashboardDataReady || state.activeView === view) return;
  const prev = state.activeView;
  try {
    state.activeView = view;
    const fp = tableFingerprint();
    if (_queryResultCache.has(fp)) return;
    const params = collectTableParams(state.sessionPrefs);
    let list;
    try {
      list = await queryGamesAsync(state, params);
    } catch (_) {
      list = queryGames({
        source: querySourceForView(state),
        ctx: {
          ...buildQueryContext(state, params),
          hiddenKeys: view === "wishlist"
            ? state.wishlistCrossStoreHiddenKeys
            : state.crossStoreHiddenKeys,
          ownedNormNames: state.ownedNormNames,
        },
      });
    }
    if (Array.isArray(list)) rememberQueryResult(fp, list);
  } finally {
    state.activeView = prev;
  }
}

let _renderTableGen = 0;

/* Match modal/fetcher sheet MQ so phone landscape (e.g. 844×390) uses cards. */
const TABLE_PHONE_MQ =
  '(max-width: 639.98px), (max-height: 480px) and (hover: none)';

export function isTablePhoneLayout() {
  const wrap = document.getElementById('tableWrap');
  return !!wrap?.classList.contains('table-phone');
}

function syncTablePhoneStickyChrome() {
  const bar = document.getElementById('tablePhoneSticky');
  if (!bar) return;
  const phone = isTablePhoneLayout();
  const tableView = state.activeView === 'library'
    || state.activeView === 'wishlist'
    || state.activeView === 'itch';
  bar.hidden = !(phone && tableView);
  if (!phone || !tableView) return;
  const label = document.getElementById('tablePhoneStickyLabel');
  const count = document.getElementById('tablePhoneStickyCount');
  if (label) {
    label.textContent = state.activeView === 'wishlist'
      ? 'Wishlist'
      : state.activeView === 'itch'
        ? 'itch.io'
        : 'Library';
  }
  if (count) {
    const n = state._visibleList?.length ?? 0;
    count.textContent = n ? `${n}` : '';
  }
}

function syncTablePhoneLayout() {
  const wrap = document.getElementById('tableWrap');
  if (!wrap) return;
  const wasPhone = wrap.classList.contains('table-phone');
  const phone = typeof matchMedia === 'function' && matchMedia(TABLE_PHONE_MQ).matches;
  wrap.classList.toggle('table-phone', phone);
  syncTablePhoneStickyChrome();
  if (wasPhone !== phone) {
    /* Phone cards are taller than the 76px desktop row; seed a better estimate
       before the first measured paint so spacers drift less on switch-in. */
    _rowHeightPx = phone ? 96 : ROW_HEIGHT;
    _virtualWindow = { start: -1, end: -1 };
    _virtualWindowList = null;
    scheduleTableDensitySync((v) => applyColumnVisibility(v), state.activeView);
    if (_virtualList && usesVirtualScroll(_virtualList)) {
      scheduleVirtualScrollUpdate();
    }
  }
}

/** Toggle card-style library rows on narrow viewports. */
export function initTablePhoneLayout() {
  syncTablePhoneLayout();
  if (typeof matchMedia !== 'function') return;
  const mq = matchMedia(TABLE_PHONE_MQ);
  const onChange = () => syncTablePhoneLayout();
  if (mq.addEventListener) mq.addEventListener('change', onChange);
  else mq.addListener(onChange);
}

/** Wire density ResizeObserver (call once at boot). */
export function initTableDensity() {
  observeTableDensity(
    (v) => applyColumnVisibility(v),
    () => state.activeView,
  );
}
let _paintGen = 0;
const FIRST_CHUNK = 50;
/** CSS sets .games-table tbody tr { height: 76px }, but on a table row `height`
 *  is a minimum: borders/padding push the real painted row taller (~82px). The
 *  virtual-scroll spacer math must use the ACTUAL rendered height or the top
 *  spacer drifts (start * delta) and the slice repaint shifts content on scroll
 *  end. ROW_HEIGHT is the bootstrap default; _rowHeightPx is refined from a real
 *  painted row and used everywhere the math runs. */
const ROW_HEIGHT = 76;
let _rowHeightPx = ROW_HEIGHT;

/** Measured (or default) row height used for all virtual-scroll geometry. */
function rowHeightPx() {
  return _rowHeightPx;
}

/** Refresh the cached row height from a freshly painted data row. */
function refreshMeasuredRowHeight(tbody) {
  const row = tbody?.querySelector('tr[data-row-index]');
  if (!row) return;
  const h = row.getBoundingClientRect().height;
  if (!(h > 0) || Math.abs(h - _rowHeightPx) < 0.5) return;
  const prev = _rowHeightPx;
  _rowHeightPx = h;
  // Phone cards vary with meta wrap; update spacer heights in place so scroll
  // math tracks the new estimate without a full slice rewrite.
  const phone = document.getElementById('tableWrap')?.classList.contains('table-phone');
  if (!phone || Math.abs(h - prev) < 2) return;
  const start = _virtualWindow.start;
  const end = _virtualWindow.end;
  const listLen = _virtualList?.length ?? 0;
  if (listLen <= 0 || end <= start) return;
  const top = tbody.querySelector('tr.virtual-spacer-top td');
  const bot = tbody.querySelector('tr.virtual-spacer-bottom td');
  if (top) top.style.height = `${start * h}px`;
  if (bot) bot.style.height = `${(listLen - end) * h}px`;
}
export const TABLE_COLSPAN = 14;
const VIRTUAL_OVERSCAN = 20;
let _virtualList = null;
let _virtualCtx = null;
let _virtualWindow = { start: 0, end: 0 };
/** Which list reference the current _virtualWindow was painted from. Used so a
 *  resort (same indices, different rows at those indices) doesn't trigger the
 *  early-return inside paintVirtualSlice and leave stale rows on screen. */
let _virtualWindowList = null;
let _virtualScrollRaf = 0;
let _virtualScrollBound = false;

const _warmedHeroes = new Set();

function preloadHeroUrl(url) {
  if (!url || _warmedHeroes.has(url)) return;
  _warmedHeroes.add(url);
  const img = new Image();
  img.decoding = "async";
  try { img.fetchPriority = "low"; } catch { /* unsupported */ }
  img.src = url;
}

function heroUrlFromRow(tr) {
  const v = tr.style.getPropertyValue("--row-hero");
  const m = v && v.match(/url\(['"]?([^'")]+)['"]?\)/);
  return m ? m[1] : "";
}

export function preloadRowHeroEl(tr) {
  if (!state.prefs.rowHeroBackdrop || !tr) return;
  preloadHeroUrl(heroUrlFromRow(tr));
}

export function warmVisibleRowHeroes() {
  if (!state.prefs.rowHeroBackdrop) return;
  const tbody = document.getElementById("tbody");
  if (!tbody) return;
  const rows = [...tbody.querySelectorAll("tr.row-has-hero")];
  const run = () => rows.forEach(tr => preloadHeroUrl(heroUrlFromRow(tr)));
  if (typeof requestIdleCallback === "function") requestIdleCallback(run, { timeout: 1200 });
  else setTimeout(run, 0);
}

function cancelPaintJobs() {
  _paintGen++;
  if (_virtualScrollRaf) {
    cancelAnimationFrame(_virtualScrollRaf);
    _virtualScrollRaf = 0;
  }
}

function usesVirtualScroll(list) {
  return list.length > FIRST_CHUNK;
}

function isTablePainted(list) {
  if (!list?.length) return true;
  if (!usesVirtualScroll(list)) return tbodyRowCount() > 0;
  return _virtualList === list && _virtualWindow.end > _virtualWindow.start;
}

function getRow0DocY() {
  const shell = document.getElementById("tableShell");
  const thead = document.querySelector(".games-table thead");
  if (!shell) return 0;
  // Phone hides thead (display:none → offsetHeight 0); do not invent 48px.
  const headH = thead && getComputedStyle(thead).display !== 'none'
    ? (thead.offsetHeight || 0)
    : 0;
  const phoneBar = document.getElementById('tablePhoneSticky');
  const barH = phoneBar && !phoneBar.hidden ? (phoneBar.offsetHeight || 0) : 0;
  return shell.offsetTop + headH + barH;
}

/** Extra Y from a sponsored row inserted at slot when slot < idx. */
function sponsoredExtraBeforeIndex(idx) {
  if (!_virtualList?.length || idx <= 0) return 0;
  const slot = resolveSponsoredTableSlot(_virtualList.length);
  if (slot < 0 || slot >= idx) return 0;
  const ad = document.querySelector('#tbody tr.sponsored-table-row');
  const h = ad?.getBoundingClientRect().height;
  return h > 0 ? h : rowHeightPx();
}

function scrollTopForRowCenter(idx) {
  const rh = rowHeightPx();
  const extra = sponsoredExtraBeforeIndex(idx);
  const rowCenterY = getRow0DocY() + extra + idx * rh + rh / 2;
  return Math.max(0, rowCenterY - window.innerHeight * 0.42);
}

/** Sync viewport to a virtual row index (drill anchor). Must run when painting an anchored slice. */
function scrollToVirtualRowIndex(idx, { behavior = "auto" } = {}) {
  if (idx < 0) return;
  window.scrollTo({ top: scrollTopForRowCenter(idx), behavior });
}

function computeVirtualRange(listLen, preferIdx = null) {
  const rh = rowHeightPx();
  const minRows = Math.ceil(window.innerHeight / rh) + VIRTUAL_OVERSCAN * 2;
  let start;
  let end;
  if (preferIdx != null && preferIdx >= 0) {
    start = Math.max(0, preferIdx - VIRTUAL_OVERSCAN);
    end = Math.min(listLen, preferIdx + minRows + VIRTUAL_OVERSCAN);
  } else {
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const row0 = getRow0DocY();
    start = Math.max(0, Math.floor((scrollY - row0) / rh) - VIRTUAL_OVERSCAN);
    end = Math.min(listLen, Math.ceil((scrollY + window.innerHeight - row0) / rh) + VIRTUAL_OVERSCAN);
  }
  if (end - start < minRows) {
    end = Math.min(listLen, start + minRows);
    start = Math.max(0, end - minRows);
  }
  return { start, end };
}

function virtualSpacerHtml(which, heightPx) {
  if (heightPx <= 0) return "";
  return `<tr class="virtual-spacer virtual-spacer-${which}" aria-hidden="true"><td colspan="${TABLE_COLSPAN}" style="height:${heightPx}px;padding:0;border:none;line-height:0"></td></tr>`;
}

function ensureVirtualScrollBound() {
  if (_virtualScrollBound) return;
  _virtualScrollBound = true;
  window.addEventListener("scroll", scheduleVirtualScrollUpdate, { passive: true });
  window.addEventListener("resize", scheduleVirtualScrollUpdate, { passive: true });
}

function scheduleVirtualScrollUpdate() {
  if (!_virtualList || !usesVirtualScroll(_virtualList)) return;
  if (_virtualScrollRaf) return;
  _virtualScrollRaf = requestAnimationFrame(() => {
    _virtualScrollRaf = 0;
    if (!_virtualList) return;
    const { start, end } = computeVirtualRange(_virtualList.length);
    paintVirtualSlice(start, end);
  });
}

/** Schedule cover-fit hydration off the critical path. Cached covers still get
 *  marked landscape, but the work doesn't block the slice paint. */
let _coverFitIdleHandle = 0;
function scheduleCoverFitSync(tbody) {
  if (_coverFitIdleHandle) {
    if (typeof cancelIdleCallback === "function") cancelIdleCallback(_coverFitIdleHandle);
    else cancelAnimationFrame(_coverFitIdleHandle);
  }
  const run = perfActiveRun();
  const work = () => {
    _coverFitIdleHandle = 0;
    if (!tbody?.isConnected) return;
    const t0 = run ? performance.now() : 0;
    syncCoverFits(tbody);
    if (run) {
      const ms = performance.now() - t0;
      run.measures.push({ name: 'cover:sync-fits-idle', ms, detail: {} });
    }
  };
  if (typeof requestIdleCallback === "function") {
    _coverFitIdleHandle = requestIdleCallback(work, { timeout: 200 });
  } else {
    _coverFitIdleHandle = requestAnimationFrame(work);
  }
}

function paintVirtualSlice(start, end) {
  const list = _virtualList;
  const ctx = _virtualCtx;
  const tbody = document.getElementById("tbody");
  if (!list || !ctx || !tbody) return;
  start = Math.max(0, start);
  end = Math.min(list.length, end);
  if (end <= start) {
    tbody.innerHTML = "";
    _virtualWindow = { start: 0, end: 0 };
    _virtualWindowList = null;
    return;
  }
  if (_virtualWindowList === list && _virtualWindow.start === start && _virtualWindow.end === end && tbody.querySelector("tr[data-row-index]")) {
    return;
  }
  _virtualWindow = { start, end };
  _virtualWindowList = list;
  const run = perfActiveRun();
  const t0 = run ? performance.now() : 0;
  const rh = rowHeightPx();
  const topH = start * rh;
  const botH = (list.length - end) * rh;
  tbody.innerHTML =
    virtualSpacerHtml("top", topH) +
    appendChunk(list, start, end, ctx) +
    virtualSpacerHtml("bottom", botH);
  refreshMeasuredRowHeight(tbody);
  if (run) {
    run._lastChunkRange = { start, end, count: end - start };
    run._lastChunkHtmlMs = performance.now() - t0;
    recordChunkPaint("virtual-window", 0);
    run.meta.virtualWindow = { start, end, total: list.length, domRows: end - start };
  }
  scheduleCoverFitSync(tbody);
  warmVisibleRowHeroes();
}

function tbodyRowCount() {
  return document.getElementById("tbody")?.querySelectorAll("tr[data-row-index]").length || 0;
}

/**
 * Resolve the sponsored row markup for the next eligible creative in the active
 * table location, or '' when none remain. Advances the round-robin cursor so a
 * dismiss reveals a *different* creative rather than re-resolving the same one.
 */
function nextSponsoredTableRowHtml({ layoutHint = 'auto' } = {}) {
  const rowLoc = resolveTableRowLocation();
  rotateLocationAd(rowLoc);
  const next = getAdsForLocation(rowLoc)[0];
  if (!next) return '';
  const isWish = state.activeView === 'wishlist';
  const ctx = { isWish, locationKey: rowLoc };
  const outgoingIsHouse = layoutHint === 'house';
  const nextIsHouse = String(next.kind || '').toLowerCase() === 'house';
  // On dismiss from a sponsor row, render the next house creative in the same
  // full-column shell so the row height stays put (strip layout is initial-paint only).
  if (!outgoingIsHouse && nextIsHouse) {
    return sponsoredTableRowHtml(next, { ...ctx, tableLayout: 'sponsor' });
  }
  return sponsoredTableRowHtml(next, ctx);
}

/**
 * Swap the sponsored table row to the next eligible creative the instant it is
 * dismissed — so the slot "instantly changes" instead of collapsing the row and
 * waiting for a full renderTable() query + virtual repaint (~200ms+ on large
 * libraries). Only when no creative remains do we drop the row (collapse).
 */
export function syncSponsoredTableAfterDismiss() {
  const row = document.getElementById('tbody')?.querySelector('.sponsored-table-row');
  const outgoingIsHouse = !!row?.classList.contains('sponsored-table-row--house');
  if (!row) return;
  const html = nextSponsoredTableRowHtml({ layoutHint: outgoingIsHouse ? 'house' : 'sponsor' });
  if (html) {
    const tmpl = document.createElement('template');
    tmpl.innerHTML = html.trim();
    const newRow = tmpl.content.querySelector('tr');
    if (newRow) {
      row.replaceWith(newRow);
      return;
    }
  }
  row.remove();
  if (_virtualList) {
    _virtualWindow = { start: -1, end: -1 };
    _virtualWindowList = null;
  }
}

function resolveTableRowLocation() {
  const view = state.activeView === 'wishlist' ? 'wishlist'
    : (state.activeView === 'itch' ? 'itch' : 'library');
  if (effectivePicksTab() === 'wishlistDeals' && view === 'library') {
    return pickLocationForView('deals', 'row');
  }
  return pickLocationForView(view, 'row');
}

function appendChunk(list, start, end, ctx) {
  const run = perfActiveRun();
  const t0 = run ? performance.now() : 0;
  const out = [];
  const rowLoc = resolveTableRowLocation();
  const total = list.length;
  const slot = resolveSponsoredTableSlot(total);
  const tableAd = total > 0 && slot >= start && slot < end
    ? getAdsForLocation(rowLoc)[0]
    : null;
  for (let i = start; i < end; i++) {
    if (tableAd && i === slot) {
      out.push(sponsoredTableRowHtml(tableAd, { ...ctx, locationKey: rowLoc, tableLayout: 'sponsor' }));
    }
    out.push(tableRowHtml(list[i], i, ctx));
  }
  const html = out.join("");
  if (run) {
    run._lastChunkHtmlMs = performance.now() - t0;
    run._lastChunkRange = { start, end, count: end - start };
  }
  return html;
}

function recordChunkPaint(mode, syncCoverMs = 0) {
  const run = perfActiveRun();
  if (!run || !run._lastChunkRange) return;
  const htmlMs = run._lastChunkHtmlMs || 0;
  const { start, end, count } = run._lastChunkRange;
  perfChunk(run, {
    start,
    end,
    count,
    mode,
    htmlMs,
    syncCoverMs,
    totalMs: htmlMs + syncCoverMs,
  });
  run._lastChunkHtmlMs = 0;
  run._lastChunkRange = null;
}

function timeSyncCoverFits(tbody) {
  const run = perfActiveRun();
  if (!run) {
    syncCoverFits(tbody);
    return;
  }
  const t0 = performance.now();
  syncCoverFits(tbody);
  return performance.now() - t0;
}

function tableRowHtml(g, idx, { isWish }) {
  const p = getPersonal(g);
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const hiddenGem = state.activeView !== "wishlist" && isHiddenGem(g);
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cover = libraryCoverFor(g);
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const ownedWish = state.activeView === "wishlist" && isOwnedByTitle(g.name);
  const selected = state.selectedKeys.has(key);
  const focused = idx === state.focusedRowIndex;
  const cleanupTitle = cleanup ? ' title="Cleanup candidate: tagged backlog, 0h, rated under 60%, 2+ yrs old"' : '';
  const { heroClass, heroStyle } = rowHeroAttrs(g);
  const heroAttr = heroStyle ? ` style="${heroStyle}"` : '';
  const hltbTxt = hltbLabel(g);
  const hltbEmpty = hltbTxt.replace(/[-\s/]/g, "") === "";
  const priceHtml = formatPrice(g);
  const priceOccupied = priceHtml.trim() !== "-";
  const lastPlayedHtml = formatDate(g.last_played);
  const lastPlayedOccupied = lastPlayedHtml.trim() !== "-";
  const cls = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}${heroClass}`;
  return `<tr data-row-key="${escapeAttr(key)}" data-row-index="${idx}" class="${cls}"${heroAttr}${cleanupTitle}>
      <td class="col-select p-2 text-center"><input type="checkbox" class="row-select rounded" data-game-key="${escapeAttr(key)}" ${selected ? "checked" : ""} title="Select for bulk status or remove" /></td>
      <td class="col-cover p-2"><span class="cover-wrap${window.coverLandscapeAttr(cover)}"><img class="cover${window.coverLandscapeAttr(cover)}" src="${safeCoverAttrUrl(cover)}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" aria-hidden="true" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />${earlyAccessRibbonHtml(g, { label: "EA" })}</span></td>
      <td class="col-game p-2 game-name-cell">
        <div class="flex items-center gap-2">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 min-w-0">
              ${storeLinkHtml(g, "text-sky-400 hover:underline font-medium game-name truncate min-w-0", escapeHtml(g.name))}
              ${ownedWish ? '<span class="text-amber-400 text-xs shrink-0" title="You already own this (matched by title)">owned</span>' : ""}
              ${earlyAccessPillHtml(g)}
              ${hiddenGem ? '<span class="text-purple-400 shrink-0" style="cursor: default" title="Hidden gem: 90%+ rated and unplayed">✦</span>' : ""}
            </div>
            <div class="row-meta mt-1 flex items-center gap-1.5 flex-wrap">
              ${state.activeView === "wishlist" ? wishlistBadgeHtml(g) : storeBadgeHtml(g)}
              ${g.manual && state.activeView === "library" ? `<label class="row-count-toggle text-xs text-slate-400 inline-flex items-center gap-1" title="Count this item in the library total"><input type="checkbox" class="rounded" data-game-key="${escapeAttr(key)}" data-field="count_in_total" ${countsInLibraryTotal(g) ? "checked" : ""} /> Count</label>` : ""}
              ${staleBadgeHtml(g)}
              ${coopPillsHtml(g)}
              ${state.activeView === "wishlist" ? "" : trophyProgressPillHtml(g)}
              ${state.activeView === "wishlist" ? "" : platinumBadgeHtml(g)}
              ${notesAffordanceHtml(key, p.notes)}
            </div>
            ${lowConf && g.hltb_name ? `<div class="hltb-match-hint text-xs text-amber-400" title="Uncertain HowLongToBeat match - Shift+click HLTB to override">HLTB match: ${escapeHtml(g.hltb_name)}</div>` : ""}
          </div>
        </div>
      </td>
      ${isWish ? `<td class="col-status p-2">${wishlistStatusSelectHtml(g, p)}</td>` : `<td class="col-status p-2">${buildStatusSelect(key, p.status)}</td>`}
      <td class="col-score p-2 text-right" title="Priority score = Steam review % ÷ log₂(HLTB main hours + 2), so well-rated, shorter games rank highest. Games with no HLTB time assume 20 hours.">${priorityScore(g).toFixed(1)}</td>
      <td class="col-played p-2 text-right text-slate-300"${combinedPlaytimeTooltip(g) ? ` title="${escapeAttr(combinedPlaytimeTooltip(g))}"` : ""}>${formatHours(combinedPlaytime(g))}</td>
      <td class="col-hltb p-2 text-right">
        <button data-hltb-edit="${escapeAttr(key)}" class="px-2 py-1 rounded text-xs${hltbEmpty ? " hltb-empty" : ""}" style="cursor: pointer" title="Open HowLongToBeat (Shift+click to override main hours)">${hltbTxt}</button>
      </td>
      <td class="col-steam p-2 text-right" title="${g.steam_review_percent != null ? `Steam review: ${g.steam_review_percent}%` : 'No Steam review data'}">${g.steam_review_percent != null ? `${g.steam_review_percent}%` : " - "}</td>
      <td class="col-mc p-2 text-right text-slate-300" title="${g.metacritic_score != null ? `Metacritic: ${g.metacritic_score}` : 'No Metacritic score'}">${g.metacritic_score != null ? g.metacritic_score : " - "}</td>
      <td class="col-price p-2 text-right">${priceOccupied ? `<span class="row-hero-pill">${priceHtml}</span>` : priceHtml}</td>
      <td class="col-released p-2 text-slate-300 whitespace-nowrap">${formatReleaseDate(g.release_date)}</td>
      <td class="col-lastplayed p-2 text-slate-300">${lastPlayedOccupied ? `<span class="row-hero-pill">${lastPlayedHtml}</span>` : lastPlayedHtml}</td>
      <td class="col-genres p-2 text-slate-400 text-xs truncate" title="${escapeAttr((g.genres || []).filter(x => !isPlatformToken(x)).join(", "))}">${escapeHtml((g.genres || []).filter(x => !isPlatformToken(x)).slice(0, 2).join(", ") || " - ")}</td>
      <td class="col-notes p-2 notes-cell${psnPlatformsLineHtml(g) ? " has-psn-platforms" : ""}">
        ${psnPlatformsLineHtml(g)}
        <textarea data-game-key="${escapeAttr(key)}" data-field="notes" placeholder="Notes..." rows="3" class="notes-input rounded text-xs w-full px-2 py-1" title="Personal notes - saved automatically">${escapeHtml(p.notes || "")}</textarea>
      </td>
    </tr>`;
}

function paintTableBody(list, opts = {}) {
  const tbody = document.getElementById("tbody");
  if (!tbody) return;
  cancelPaintJobs();
  const run = perfActiveRun();
  if (run) perfMark(run, 'paint:start');
  if (opts.resetScroll) {
    const shell = document.getElementById("tableShell");
    if (shell) window.scrollTo({ top: shell.offsetTop - 8, behavior: "auto" });
  }
  const isWish = state.activeView === "wishlist";
  const ctx = { isWish };

  if (!list.length) {
    _virtualList = null;
    _virtualCtx = null;
    _virtualWindow = { start: 0, end: 0 };
    _virtualWindowList = null;
    tbody.innerHTML = buildTableEmptyStateHtml(state.activeView, TABLE_COLSPAN);
    if (run) {
      run.meta.paintPath = 'empty';
      perfMeasure(run, 'paint:total', 'paint:start', { rows: 0 });
    }
    return;
  }

  // Small lists: one-shot paint (most reliable).
  if (!usesVirtualScroll(list)) {
    _virtualList = null;
    _virtualCtx = null;
    _virtualWindow = { start: 0, end: 0 };
    _virtualWindowList = null;
    if (run) run.meta.paintPath = 'oneshot';
    if (run) run.meta.syncPaintRows = list.length;
    tbody.innerHTML = appendChunk(list, 0, list.length, ctx);
    const syncCoverMs = timeSyncCoverFits(tbody) ?? 0;
    recordChunkPaint('oneshot', syncCoverMs);
    if (run) perfMeasure(run, 'paint:total', 'paint:start', { rows: list.length, path: 'oneshot' });
    warmVisibleRowHeroes();
    return;
  }

  const anchorIdx = typeof opts.anchorIndex === "number" ? opts.anchorIndex : -1;
  // Forced re-renders (e.g. sponsored-row dismiss) reuse the same list ref and
  // scroll position, so computeVirtualRange returns an unchanged window and
  // paintVirtualSlice would early-return — bust the window cache so the slice
  // always repaints.
  if (opts.bustVirtualCache) {
    _virtualWindow = { start: -1, end: -1 };
    _virtualWindowList = null;
  }
  _virtualList = list;
  _virtualCtx = ctx;
  ensureVirtualScrollBound();
  if (run) {
    run.meta.paintPath = anchorIdx >= 0 ? 'virtual+anchor' : 'virtual-window';
    run.meta.anchorIndex = anchorIdx >= 0 ? anchorIdx : undefined;
  }
  const { start, end } = computeVirtualRange(list.length, anchorIdx >= 0 ? anchorIdx : null);
  paintVirtualSlice(start, end);
  if (anchorIdx >= 0 && !hasPendingScrollTarget()) {
    if (isTablePhoneLayout()) {
      const key = gameKey(list[anchorIdx]);
      const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
      if (row) scrollRowToCenter(row, { smooth: false });
      else scrollToVirtualRowIndex(anchorIdx, { behavior: "auto" });
    } else {
      scrollToVirtualRowIndex(anchorIdx, { behavior: "auto" });
    }
  }
  if (run) {
    perfMeasure(run, 'paint:total', 'paint:start', {
      rows: list.length,
      path: run.meta.paintPath,
      virtualWindow: run.meta.virtualWindow,
    });
  }
}

/**
 * Decorate every `<th data-sort>` with an aria-sort attribute and a small
 * arrow span (.sort-arrow) reflecting the current state.sortKey / sortDir.
 *
 * The Price header has a special case — its data-sort is `deal_price`, but
 * shift-click also routes the same column to `discount_percent`. So when
 * sortKey is `discount_percent`, the Price header should still show as
 * "active" with a `%` glyph so the user knows the column is sorting by
 * discount instead of by price.
 */
export function renderSortIndicators() {
  const key = state.sortKey;
  const dir = state.sortDir;
  document.querySelectorAll("th[data-sort]").forEach(th => {
    const ownKey = th.dataset.sort;
    const isPriceHeader = th.id === "priceHeader";
    const matchesAlt = isPriceHeader && key === "discount_percent";
    const active = ownKey === key || matchesAlt;
    const arrowGlyph = matchesAlt
      ? (dir < 0 ? "%↓" : "%↑")
      : (dir < 0 ? "↓" : "↑");
    th.setAttribute("aria-sort", active ? (dir < 0 ? "descending" : "ascending") : "none");
    th.classList.toggle("th-sorted", active);
    let arrow = th.querySelector(".sort-arrow");
    if (!arrow) {
      arrow = document.createElement("span");
      arrow.className = "sort-arrow";
      arrow.setAttribute("aria-hidden", "true");
      th.appendChild(arrow);
    }
    arrow.textContent = active ? arrowGlyph : "\u2195";
  });
}

export function formatRowCountText(view, list) {
  const rows = list || [];
  let base;
  if (view === "wishlist") {
    const onSale = rows.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
    const lows = rows.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; }).length;
    const dealBits = [];
    if (onSale) dealBits.push(`${onSale} on sale`);
    if (lows) dealBits.push(`${lows} at historical low`);
    const tail = dealBits.length ? ` · ${dealBits.join(", ")}` : "";
    base = `Wishlist: ${rows.length} of ${Math.max(0, state.wishlistGames.length - state.wishlistCrossStoreHiddenKeys.size - countUserHiddenWishlist())}${tail}`;
  } else if (view === "itch") {
    const itchGames = visibleItchGames();
    const total = itchGames.length;
    const gamesOnly = itchGames.filter(itchIsGame).length;
    const suffix = state.sessionPrefs.itchHideNonGames && gamesOnly !== total ? ` (${gamesOnly} games of ${total} items)` : "";
    base = `Itch.io: ${rows.length} of ${total}${suffix}`;
  } else {
    base = `Showing ${rows.filter(countsInLibraryTotal).length} of ${countedLibraryDenominator()} games`;
  }
  const extra = state.cleanupModeActive && view === "library" ? " · cleanup mode" : "";
  return base + extra;
}

/** Filtered row count for library/wishlist table views (matches #rowCount). */
export function visibleRowCountForActiveView(view = state.activeView) {
  if (view !== 'library' && view !== 'wishlist') return null;
  const params = collectTableParams(state.sessionPrefs);
  const list = queryGames({
    source: querySourceForView({ ...state, activeView: view }),
    ctx: {
      ...buildQueryContext(state, params),
      hiddenKeys: view === 'wishlist'
        ? state.wishlistCrossStoreHiddenKeys
        : state.crossStoreHiddenKeys,
      ownedNormNames: state.ownedNormNames,
    },
  });
  if (view === 'library') return list.filter(countsInLibraryTotal).length;
  return list.length;
}

/** Paint #rowCount; library/wishlist views get a popup mount target for 1UP animation. */
export function renderRowCountEl(el, view, list) {
  if (!el) return;
  const rows = list || [];
  if (view === "library") {
    const total = countedLibraryDenominator();
    const extra = state.cleanupModeActive ? " · cleanup mode" : "";
    el.innerHTML = `Showing <span class="library-count-host" data-libcount-host><span data-count-target="rowcount-library">${rows.filter(countsInLibraryTotal).length}</span></span> of ${total} games${escapeHtml(extra)}`;
    return;
  }
  if (view === "wishlist") {
    const onSale = rows.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
    const lows = rows.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; }).length;
    const dealBits = [];
    if (onSale) dealBits.push(`${onSale} on sale`);
    if (lows) dealBits.push(`${lows} at historical low`);
    const tail = dealBits.length ? ` · ${escapeHtml(dealBits.join(", "))}` : "";
    const total = Math.max(0, state.wishlistGames.length - state.wishlistCrossStoreHiddenKeys.size - countUserHiddenWishlist());
    el.innerHTML = `Wishlist: <span class="library-count-host" data-libcount-host><span data-count-target="rowcount-wishlist">${rows.length}</span></span> of ${total}${tail}`;
    return;
  }
  el.textContent = formatRowCountText(view, list);
}

/** Keep #rowCount in sync with activeView (e.g. after tab switch before async renderTable finishes). */
export function syncRowCountLabel() {
  const el = document.getElementById("rowCount");
  if (!el) return;
  const view = state.activeView;
  if (view === "dashboard" || view === "connections") return;
  const animTarget = el.querySelector('[data-count-target^="rowcount-"]');
  if (animTarget && isSurfaceAnimating(animTarget)) return;
  let list = state._visibleListView === view ? state._visibleList : null;
  if (!Array.isArray(list)) {
    const params = collectTableParams(state.sessionPrefs);
    list = queryGames({
      source: querySourceForView(state),
      ctx: {
        ...buildQueryContext(state, params),
        hiddenKeys: view === "wishlist"
          ? state.wishlistCrossStoreHiddenKeys
          : state.crossStoreHiddenKeys,
        ownedNormNames: state.ownedNormNames,
      },
    });
  }
  renderRowCountEl(el, view, list);
  const topEl = document.getElementById("rowCountTop");
  if (topEl) topEl.textContent = formatRowCountText(view, list);
}

export async function renderTable(opts) {
  const force = !!opts?.force;
  const drillIn = !!opts?.drillIn || !!state._drillHideOverlay || !!state._pendingFocusKey;
  if (!force && state.activeView === 'connections') {
    deferTableRender();
    return;
  }
  renderSortIndicators();
  const fp = tableFingerprint();
  if (!force && fp === _tableFingerprint && _lastRenderedView === state.activeView && state._visibleList && isTablePainted(state._visibleList)) {
    if (state._pendingFocusKey && state._visibleList) consumePendingFocus(state._visibleList);
    if (hasPendingScrollTarget() && !scrollDeferredToRefreshFilterUI()) scheduleScrollAfterLayoutSettled();
    syncRowCountLabel();
    if (isTablePerfEnabled()) {
      console.log('[baklog-perf] renderTable skipped (fingerprint cache hit)', { view: state.activeView, fpLen: fp.length });
    }
    noteTableRenderSkipped();
    return;
  }
  noteTableRender();
  // Rotate the row ad on each real (re)render — drill-ins, filters, sorts — so
  // it isn't pinned to one creative all session. Scroll re-renders go through
  // the virtual-window path (not renderTable), so this never flickers mid-scroll.
  rotateLocationAd(resolveTableRowLocation());
  const loaderToken = drillIn ? 0 : beginRowLoader();
  try {
  // drillIn uses the view overlay; in-tab filter/sort uses the row pill only
  const perfRun = perfBeginRun({
    view: state.activeView,
    force,
    pendingFocus: !!state._pendingFocusKey,
    anchorIndex: opts?.anchorIndex ?? null,
  });
  perfMark(perfRun, 'renderTable:start');
  const gen = ++_renderTableGen;
  const params = collectTableParams(state.sessionPrefs);
  let list;
  let queryCacheHit = false;
  perfMark(perfRun, 'query:start');
  const cached = _queryResultCache.get(fp);
  if (cached && Array.isArray(cached)) {
    list = cached;
    queryCacheHit = true;
  } else {
    try {
      list = await queryGamesAsync(state, params);
    } catch (err) {
      console.warn("[renderTable] query failed, retrying on main thread", err);
      list = queryGames({
        source: querySourceForView(state),
        ctx: {
          ...buildQueryContext(state, params),
          hiddenKeys: state.activeView === "wishlist"
            ? state.wishlistCrossStoreHiddenKeys
            : state.crossStoreHiddenKeys,
          ownedNormNames: state.ownedNormNames,
        },
      });
    }
  }
  if (gen !== _renderTableGen) {
    if (perfRun) {
      perfRun.meta.aborted = 'stale-gen-after-query';
      perfEndRun(perfRun);
    }
    return;
  }
  if (!Array.isArray(list)) list = [];
  if (!queryCacheHit) rememberQueryResult(fp, list);
  if (perfRun) {
    perfRun.meta.rowCount = list.length;
    perfRun.meta.queryCacheHit = queryCacheHit;
    perfMeasure(perfRun, 'query:filter-sort', 'query:start', { rowCount: list.length, cached: queryCacheHit });
  }
  state._visibleList = list;
  state._visibleListView = state.activeView;

  perfMark(perfRun, 'chrome:start');
  const isWish = state.activeView === "wishlist";
  syncTablePhoneLayout();
  syncTableDensity((v) => applyColumnVisibility(v), state.activeView);
  syncTablePhoneStickyChrome();
  const statusHdr = document.getElementById("statusHeader");
  if (statusHdr) {
    const label = isWish ? "Tracking" : "Status";
    const arrow = statusHdr.querySelector(".sort-arrow");
    statusHdr.textContent = label;
    if (arrow) statusHdr.appendChild(arrow);
  }
  const priceHdr = document.getElementById("priceHeader");
  if (priceHdr) {
    priceHdr.title = isWish
      ? "Sort by best discount (ITAD cross-store price, then Steam). Shift+click header to sort by deal price."
      : "";
  }
  document.getElementById("tableWrap").classList.toggle("cleanup-active", state.cleanupModeActive && state.activeView === "library");
  const selectAll = document.getElementById("selectAllVisible");
  if (selectAll) {
    selectAll.disabled = false;
    selectAll.checked = list.length > 0 && list.every(g => state.selectedKeys.has(gameKey(g)));
  }

  if (state.focusedRowIndex >= list.length) state.focusedRowIndex = list.length - 1;
  if (state.focusedRowIndex < 0 && list.length) state.focusedRowIndex = 0;

  let anchorIndex = opts?.anchorIndex;
  if (anchorIndex == null && state._pendingFocusKey) {
    const pidx = list.findIndex(g => gameKey(g) === state._pendingFocusKey);
    if (pidx >= 0) anchorIndex = pidx;
  }
  if (perfRun && anchorIndex != null) perfRun.meta.resolvedAnchorIndex = anchorIndex;

  if (anchorIndex != null) setRowAdAnchor(anchorIndex);
  else clearRowAdAnchor();

  perfMeasure(perfRun, 'chrome:dom-prep', 'chrome:start');
  perfMark(perfRun, 'paint:start');
  // resetScroll is opt-in only (opts.resetScroll). Do not tie it to force:true —
  // force only busts the fingerprint cache; scrolling to tableShell before picks
  // paint made tab switches land mid-picks when the grid expanded afterward.
  paintTableBody(list, {
    resetScroll: !!opts?.resetScroll && anchorIndex == null,
    anchorIndex,
    bustVirtualCache: force,
  });
  if (list.length > 0 && !isTablePainted(list)) {
    console.warn("[renderTable] tbody empty after paint, retrying sync");
    paintTableBody(list, { anchorIndex, bustVirtualCache: force });
  }
  perfMeasure(perfRun, 'paint:body', 'paint:start', {
    tbodyRows: tbodyRowCount(),
    paintPath: perfRun?.meta?.paintPath,
    syncPaintRows: perfRun?.meta?.syncPaintRows,
    virtualWindow: perfRun?.meta?.virtualWindow,
  });

  const rowCountEl = document.getElementById("rowCount");
  const rowAnim = rowCountEl?.querySelector('[data-count-target^="rowcount-"]');
  if (!rowAnim || !isSurfaceAnimating(rowAnim)) {
    renderRowCountEl(rowCountEl, state.activeView, list);
  }
  const rowCountTopEl = document.getElementById("rowCountTop");
  if (rowCountTopEl) rowCountTopEl.textContent = formatRowCountText(state.activeView, list);
  perfMark(perfRun, 'post:start');
  updateBulkBar();
  buildAlphaNav(list);
  consumePendingFocus(list);
  if (hasPendingScrollTarget() && !scrollDeferredToRefreshFilterUI()) {
    scheduleScrollAfterLayoutSettled();
  }
  perfMeasure(perfRun, 'post:bulk-alpha-focus', 'post:start');
  _tableFingerprint = fp;
  _lastRenderedView = state.activeView;
  // Cursor's embedded browser sometimes settles layout late on first paint —
  // tbody is populated but cells render blank until a window resize triggers
  // a layout recompute. A no-op scrollTo forces that recompute without
  // changing the user's scroll position. Skip when a smooth drill scroll just
  // ran — it can cancel the in-flight smooth animation.
  if (list.length > 0 && !_lastConsumeWasSmooth && !hasPendingScrollTarget()) {
    window.scrollTo(window.scrollX, window.scrollY);
  }
  perfMeasure(perfRun, 'renderTable:total', 'renderTable:start', {
    tbodyRows: tbodyRowCount(),
    fingerprint: fp.slice(0, 80) + (fp.length > 80 ? '…' : ''),
  });
  perfEndRun(perfRun);
  } finally {
    if (loaderToken) endRowLoader(loaderToken);
  }
}
