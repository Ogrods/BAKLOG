import { state } from './state.js';
import { escapeHtml, escapeAttr } from './dom-util.js';
import {
  collectTableParams,
  queryGames,
  queryGamesAsync,
  buildQueryContext,
  querySourceForView,
} from './table-query.js';
import { buildStatusSelect, STATUS_LABELS } from './row-templates.js';
import {
  gameKey,
  alphaBucket,
  isHiddenGem,
  coverFallbackFor,
  storeLinkHtml,
  storeUrlForGame,
  storeBadgeHtml,
  wishlistBadgeHtml,
  wishlistStatusSelectHtml,
  coopPillsHtml,
  earlyAccessRibbonHtml,
  earlyAccessPillHtml,
  priorityScore,
  formatHours,
  formatDate,
  formatReleaseDate,
  itchIsGame,
  findGameByKey,
  renderBulkStatusButtons,
  recomputeCrossStoreHidden,
} from './game-core.js';
import {
  isCleanupCandidate,
  isOwnedByTitle,
  getItadForGame,
  getDealInfo,
  priceLowStarHtml,
  dealDroppedBadgeHtml,
  cutBucketClass,
} from './deals.js';
import { isPlatformToken } from './genres.js';
import { syncCoverFits } from './covers.js';
import {
  getPersonal,
  setPersonal,
  savePersonal,
  bumpPersonalMemo,
} from './personal-storage.js';
import { getCoopFilterMode } from './prefs.js';
import { renderSummary, switchView, renderTagChips, hideViewLoading } from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
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
  if (row) row.classList.add("row-focused", "row-picked");
  return row;
}

export function scrollToRowIndex(idx, { smooth = false } = {}) {
  const list = state._visibleList || sortedGames(filteredGames());
  if (!list.length || idx < 0 || idx >= list.length) return;
  // Smooth scroll through thousands of fixed rows forces a layout pass per frame.
  const useSmooth = smooth && list.length <= FIRST_CHUNK;
  requestScrollToIndex(list, idx, { smooth: useSmooth });
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
    <button type="button" data-undo-action="undo">Undo</button>
    <button type="button" class="undo-toast-dismiss" data-undo-action="dismiss" aria-label="Dismiss">×</button>
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

// === Row helpers ===
export function updateHasTagsIndicatorInPlace(tr, g) {
  if (!tr) return;
  const meta = tr.querySelector(".row-meta");
  if (!meta) return;
  const tags = getPersonal(g).tags || [];
  const dot = meta.querySelector(".has-tags-dot");
  if (tags.length) {
    const tooltip = tags.join(", ").slice(0, 160);
    const label = `${tags.length} tag${tags.length === 1 ? "" : "s"}`;
    if (dot) {
      dot.title = tooltip;
      dot.textContent = label;
    } else {
      meta.insertAdjacentHTML(
        "beforeend",
        `<span class="has-tags-dot" title="${escapeAttr(tooltip)}" aria-label="Has tags">${label}</span>`,
      );
    }
  } else if (dot) {
    dot.remove();
  }
}

export function updateHasNotesIndicatorInPlace(tr, g) {
  if (!tr) return;
  const meta = tr.querySelector(".row-meta");
  if (!meta) return;
  const notes = String(getPersonal(g).notes || "").trim();
  const dot = meta.querySelector(".has-notes-dot");
  if (notes) {
    const tooltip = notes.slice(0, 160);
    if (dot) {
      dot.title = tooltip;
    } else {
      const tagsDot = meta.querySelector(".has-tags-dot");
      const html = `<span class="has-notes-dot" title="${escapeAttr(tooltip)}" aria-label="Has notes">&#9998; note</span>`;
      if (tagsDot) tagsDot.insertAdjacentHTML("beforebegin", html);
      else meta.insertAdjacentHTML("beforeend", html);
    }
  } else if (dot) {
    dot.remove();
  }
}

export function updateRowInPlace(tr, g) {
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const key = gameKey(g);
  const selected = state.selectedKeys.has(key);
  const focused = tr.classList.contains("row-focused");
  tr.className = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}`;
}

export function tagCellHtml(g) {
  const key = gameKey(g);
  const p = getPersonal(g);
  const chips = (p.tags || []).map(t => `<span class="row-tag tag-chip">${escapeHtml(t)}<button type="button" class="row-tag-remove tag-chip-remove" data-game-key="${escapeAttr(key)}" data-tag="${escapeAttr(t)}" title="Remove tag" aria-label="Remove tag">×</button></span>`).join("");
  return `${chips}<button type="button" class="row-tag-add tag-chip-add" data-game-key="${escapeAttr(key)}" title="Add a tag">+ tag</button>`;
}

export function updateTagCellInPlace(tr, g) {
  if (!tr) return;
  const wrap = tr.querySelector(".tag-chip-wrap");
  if (wrap) wrap.innerHTML = tagCellHtml(g);
}

let _tagChipsRefreshTimer = null;
export function scheduleTagChipsRefresh() {
  clearTimeout(_tagChipsRefreshTimer);
  _tagChipsRefreshTimer = setTimeout(renderTagChips, 150);
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

export function formatPrice(g) {
  const itad = getItadForGame(g);
  if (itad?.price_str) {
    const onSale = (itad.cut || 0) > 0;
    const cutTxt = onSale ? ` (-${itad.cut}%)` : "";
    const bucket = onSale ? cutBucketClass(itad.cut) : "";
    const priceInner = onSale
      ? `<span class="price-cut font-semibold ${bucket}">${escapeHtml(itad.price_str)}${escapeHtml(cutTxt)}</span>`
      : escapeHtml(itad.price_str);
    const d = getDealInfo(g);
    const lowStar = d ? priceLowStarHtml(d) : "";
    const dropBadge = dealDroppedBadgeHtml(g).replace(/^/, "&nbsp;");
    const shopHtml = itad.shop ? `@ ${escapeHtml(itad.shop)}` : "";
    const dealUrl = itad.url || (d && d.url) || null;
    const linkOpen = dealUrl
      ? `<a href="${escapeAttr(dealUrl)}" target="_blank" rel="noopener" class="deal-price-link flex flex-col items-end leading-tight" title="Open this deal on ${escapeAttr(itad.shop || "store")}">`
      : `<div class="flex flex-col items-end leading-tight">`;
    const linkClose = dealUrl ? `</a>` : `</div>`;
    // Star sits outside the link so it never picks up the link's underline,
    // pointer cursor, or click target. The tooltip still works on hover.
    return `<div class="deal-price-row flex items-start justify-end gap-1">${lowStar}${linkOpen}
      <span class="whitespace-nowrap">${priceInner}${dropBadge}</span>
      ${shopHtml ? `<span class="text-[10px] text-slate-400 truncate w-full text-right" title="${escapeAttr(itad.shop)}">${shopHtml}</span>` : ""}
    ${linkClose}</div>`;
  }
  if (!g.price && g.discount_percent == null) return "—";
  const base = g.price || "N/A";
  const cut = g.discount_percent || 0;
  if (cut > 0) {
    const bucket = cutBucketClass(cut);
    return `<span class="price-cut font-semibold ${bucket}">${escapeHtml(base)} (-${cut}%)</span>`;
  }
  return escapeHtml(base);
}

// === Focus helpers ===
export function focusGame(key) {
  state.pickedKey = key;
  const targetIsWishlist = String(key).startsWith("wishlist:");
  const targetIsItch = String(key).startsWith("itch:");
  const targetView = targetIsWishlist ? "wishlist" : targetIsItch ? "itch" : "library";
  const crossingView = state.activeView !== targetView;

  // Whether we're switching views or not, the user's intent is "show me this
  // game." Active navigation filters in the target view can hide the row, so
  // clear them up-front. This makes the row guaranteed-visible and means
  // consumePendingFocus / the same-view branch below can rely on the list
  // containing the key. Pre-2026-06 versions of this code papered over the
  // problem with a scroll-to-top fallback; that was the bandaid we're removing.
  const targetList = crossingView ? null : visibleListForKeyboard();
  const alreadyVisible = targetList && targetList.findIndex(g => gameKey(g) === key) >= 0;
  if (!alreadyVisible) {
    dashResetLibraryFiltersExceptDedup();
  }

  if (crossingView) {
    state._pendingFocusKey = key;
    state._drillHideOverlay = true;
    switchView(targetView);
    return;
  }

  // Same-view jump.
  const list = visibleListForKeyboard();
  let idx = list.findIndex(g => gameKey(g) === key);
  if (idx < 0) {
    // After the filter reset above the row should be in the list. If it
    // still isn't, the key doesn't exist in the data set at all — log loudly
    // so we don't silently scroll to the wrong place.
    console.warn('[focusGame] key not found in visible list even after filter reset', { key, view: state.activeView, listLen: list.length });
    state._pendingFocusKey = key;
    renderTable();
    return;
  }
  state.focusedRowIndex = idx;
  const existing = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (existing) {
    markFocusedRow(key);
    scrollRowToCenter(existing, { smooth: true });
    return;
  }
  scrollToRowIndex(idx, { smooth: true });
}

function consumePendingFocus(list) {
  const key = state._pendingFocusKey;
  if (!key) return;
  state._pendingFocusKey = null;
  const idx = list.findIndex(g => gameKey(g) === key);
  const run = perfActiveRun();
  if (run) run.meta.pendingKeyFound = idx >= 0;
  if (idx < 0) {
    console.warn('[consumePendingFocus] pending key not in painted list — anchor lost', {
      key,
      view: state.activeView,
      listLen: list.length,
    });
    if (state._drillHideOverlay) {
      state._drillHideOverlay = false;
      hideViewLoading();
    }
    state._anchorScrollHandled = -1;
    return;
  }
  state.pickedKey = key;
  state.focusedRowIndex = idx;
  // paintTableBody already scrolled to scrollTopForRowCenter(idx) and painted
  // the window around the anchor. If the row is in the DOM, just mark + run
  // finishDrillScroll (no second scrollTo, no second paintVirtualSlice).
  if (state._anchorScrollHandled === idx) {
    state._anchorScrollHandled = -1;
    const row = document.querySelector(`tr[data-row-index="${idx}"]`);
    if (row) {
      markFocusedRow(key);
      focusRow(key);
      finishDrillScroll(key, false, state._drillHideOverlay);
      if (run) run.meta.anchorReused = true;
      return;
    }
  }
  state._anchorScrollHandled = -1;
  requestScrollToIndex(list, idx, {
    smooth: false,
    hideOverlayOnComplete: state._drillHideOverlay,
  });
}

export function scrollFocusedRow() {
  const list = visibleListForKeyboard();
  const idx = state.focusedRowIndex;
  if (idx < 0 || !list[idx]) return;
  const key = gameKey(list[idx]);
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (row) {
    scrollRowToCenter(row);
    focusRow(key);
    return;
  }
  scrollToRowIndex(idx);
}

/**
 * Re-anchor the picked/focused row after a cross-view drill-in.
 *
 * paintTableBody scrolls to scrollTopForRowCenter(anchorIdx) BEFORE the
 * deferred picks/summary render. When picks then paints above the table the
 * layout shifts down and the row falls off-screen (or appears below the
 * fold). Calling this from the deferred deferChrome path after picks has
 * settled re-measures the row's live position and snaps it back to center.
 *
 * Uses getBoundingClientRect (live) so it's correct regardless of how much
 * the layout shifted. No-op if no pickedKey or the row isn't painted.
 */
export function reanchorPickedRow() {
  const key = state.pickedKey;
  if (!key) return;
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (!row) return;
  scrollRowToCenter(row, { smooth: false });
}

export function focusRow(key) {
  const row = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
  if (!row) return;
  document.querySelectorAll("tr.row-focused").forEach(r => r.classList.remove("row-focused"));
  row.classList.add("row-focused");
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
    store: state.prefs.storeFilter || "",
    wstore: state.prefs.wishlistStoreFilter || "",
    releaseYear: state.prefs.releaseYearFilter || "",
    hltbBucket: state.prefs.hltbBucket ?? null,
    gen: state.prefs.genreFilters || [],
    gm: state.prefs.genreFilterMode,
    tags: state.prefs.tagFilters || [],
    tm: state.prefs.tagFilterMode,
    deal: [state.prefs.dealOnSaleOnly, state.prefs.dealHistoricalLowOnly, state.prefs.dealHideOwned, state.prefs.dealMinDiscount, state.prefs.dealMaxPrice],
    coop: getCoopFilterMode(),
    cleanup: !!state.cleanupModeActive,
    score: !!state.prefs.showScoreColumn,
    dedupe: !!state.sessionPrefs.crossStoreDedup,
    ihng: !!state.sessionPrefs.itchHideNonGames,
    lib: state.allGames.length,
    wl: state.wishlistGames.length,
    itch: state.itchGames.length,
    dv: window._dataVersion || 0,
  });
}

export function invalidateTableCache() {
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

let _renderTableGen = 0;
let _paintGen = 0;
/** Scroll is deferred until the target row exists in the virtual window. */
let _pendingScroll = null;
const FIRST_CHUNK = 50;
/** Must match .games-table tbody tr { height } in app.css */
const ROW_HEIGHT = 76;
const TABLE_COLSPAN = 13;
const VIRTUAL_OVERSCAN = 10;
let _virtualList = null;
let _virtualCtx = null;
let _virtualWindow = { start: 0, end: 0 };
/** Which list reference the current _virtualWindow was painted from. Used so a
 *  resort (same indices, different rows at those indices) doesn't trigger the
 *  early-return inside paintVirtualSlice and leave stale rows on screen. */
let _virtualWindowList = null;
let _virtualScrollRaf = 0;
let _virtualScrollBound = false;

function cancelPaintJobs() {
  _paintGen++;
  if (_virtualScrollRaf) {
    cancelAnimationFrame(_virtualScrollRaf);
    _virtualScrollRaf = 0;
  }
  _pendingScroll = null;
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
  return shell.offsetTop + (thead?.offsetHeight ?? 48);
}

function scrollTopForRowCenter(idx) {
  const rowCenterY = getRow0DocY() + idx * ROW_HEIGHT + ROW_HEIGHT / 2;
  return Math.max(0, rowCenterY - window.innerHeight * 0.42);
}

function computeVirtualRange(listLen, preferIdx = null) {
  const minRows = Math.ceil(window.innerHeight / ROW_HEIGHT) + VIRTUAL_OVERSCAN * 2;
  let start;
  let end;
  if (preferIdx != null && preferIdx >= 0) {
    start = Math.max(0, preferIdx - VIRTUAL_OVERSCAN);
    end = Math.min(listLen, preferIdx + minRows + VIRTUAL_OVERSCAN);
  } else {
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const row0 = getRow0DocY();
    start = Math.max(0, Math.floor((scrollY - row0) / ROW_HEIGHT) - VIRTUAL_OVERSCAN);
    end = Math.min(listLen, Math.ceil((scrollY + window.innerHeight - row0) / ROW_HEIGHT) + VIRTUAL_OVERSCAN);
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
    tryCompletePendingScroll(_virtualList);
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
  const topH = start * ROW_HEIGHT;
  const botH = (list.length - end) * ROW_HEIGHT;
  tbody.innerHTML =
    virtualSpacerHtml("top", topH) +
    appendChunk(list, start, end, ctx) +
    virtualSpacerHtml("bottom", botH);
  if (run) {
    run._lastChunkRange = { start, end, count: end - start };
    run._lastChunkHtmlMs = performance.now() - t0;
    recordChunkPaint("virtual-window", 0);
    run.meta.virtualWindow = { start, end, total: list.length, domRows: end - start };
  }
  scheduleCoverFitSync(tbody);
}

function finishDrillScroll(key, smooth, hideOverlayOnComplete) {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      const el = document.querySelector(`tr[data-row-key="${CSS.escape(key)}"]`);
      if (el) scrollRowToCenter(el, { smooth });
      if (hideOverlayOnComplete) {
        state._drillHideOverlay = false;
        hideViewLoading();
      }
    });
  });
}

function tryCompletePendingScroll(list) {
  if (!_pendingScroll || _pendingScroll.paintGen !== _paintGen) return false;
  const { idx, key, smooth, hideOverlayOnComplete } = _pendingScroll;
  const row = document.querySelector(`tr[data-row-index="${idx}"]`);
  if (!row) return false;
  _pendingScroll = null;
  markFocusedRow(key);
  focusRow(key);
  finishDrillScroll(key, smooth, hideOverlayOnComplete);
  return true;
}

/** Scroll to row index; virtual lists jump by scroll position instead of painting 0..idx. */
function requestScrollToIndex(list, idx, { smooth = false, hideOverlayOnComplete = false } = {}) {
  if (!list.length || idx < 0 || idx >= list.length) return;
  const key = gameKey(list[idx]);
  state.focusedRowIndex = idx;
  state.pickedKey = key;

  if (usesVirtualScroll(list)) {
    window.scrollTo({ top: scrollTopForRowCenter(idx), behavior: smooth ? "smooth" : "auto" });
    if (_virtualList === list) {
      const { start, end } = computeVirtualRange(list.length, idx);
      paintVirtualSlice(start, end);
    }
    const row = document.querySelector(`tr[data-row-index="${idx}"]`);
    if (row) {
      markFocusedRow(key);
      focusRow(key);
      finishDrillScroll(key, smooth, hideOverlayOnComplete);
      return;
    }
    _pendingScroll = { idx, key, smooth, hideOverlayOnComplete, paintGen: _paintGen };
    scheduleVirtualScrollUpdate();
    return;
  }

  const existing = document.querySelector(`tr[data-row-index="${idx}"]`);
  if (existing) {
    markFocusedRow(key);
    focusRow(key);
    scrollRowToCenter(existing, { smooth });
    if (hideOverlayOnComplete) {
      state._drillHideOverlay = false;
      hideViewLoading();
    }
    return;
  }
  const tbody = document.getElementById("tbody");
  if (!tbody) return;
  const ctx = {
    isWish: state.activeView === "wishlist",
    showScore: !!state.prefs.showScoreColumn,
  };
  const rendered = tbodyRowCount();
  if (idx + 1 - rendered <= FIRST_CHUNK) {
    tbody.insertAdjacentHTML("beforeend", appendChunk(list, rendered, idx + 1, ctx));
    timeSyncCoverFits(tbody);
    const row = document.querySelector(`tr[data-row-index="${idx}"]`);
    if (row) {
      markFocusedRow(key);
      focusRow(key);
      scrollRowToCenter(row, { smooth });
      if (hideOverlayOnComplete) {
        state._drillHideOverlay = false;
        hideViewLoading();
      }
    }
    return;
  }
  _pendingScroll = { idx, key, smooth, hideOverlayOnComplete, paintGen: _paintGen };
  tryCompletePendingScroll(list);
}

function tbodyRowCount() {
  return document.getElementById("tbody")?.querySelectorAll("tr[data-row-index]").length || 0;
}

function appendChunk(list, start, end, ctx) {
  const run = perfActiveRun();
  const t0 = run ? performance.now() : 0;
  const out = [];
  for (let i = start; i < end; i++) out.push(tableRowHtml(list[i], i, ctx));
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

function tableRowHtml(g, idx, { isWish, showScore }) {
  const p = getPersonal(g);
  const lowConf = g.hltb_match_confidence != null && g.hltb_match_confidence < 0.75;
  const hiddenGem = isHiddenGem(g);
  const key = gameKey(g);
  const headerFallback = coverFallbackFor(g);
  const cleanup = state.activeView === "library" && isCleanupCandidate(g);
  const ownedWish = state.activeView === "wishlist" && isOwnedByTitle(g.name);
  const selected = state.selectedKeys.has(key);
  const focused = idx === state.focusedRowIndex;
  const cls = `${rowClass(g, lowConf)}${cleanup ? " cleanup-candidate" : ""}${selected ? " row-selected" : ""}${focused ? " row-focused" : ""}`;
  return `<tr data-row-key="${escapeAttr(key)}" data-row-index="${idx}" class="${cls}">
      <td class="p-2 text-center"><input type="checkbox" class="row-select rounded" data-game-key="${escapeAttr(key)}" ${selected ? "checked" : ""} /></td>
      <td class="p-2"><span class="cover-wrap${window.coverLandscapeAttr(g.library_image || headerFallback)}"><img class="cover${window.coverLandscapeAttr(g.library_image || headerFallback)}" src="${g.library_image || headerFallback}" data-fallback="${escapeAttr(headerFallback)}" data-name="${escapeAttr(g.name)}" alt="" loading="lazy" onload="window.markLandscape(this)" onerror="window.coverFallback(this)" />${earlyAccessRibbonHtml(g, { label: "EA" })}</span></td>
      <td class="p-2 game-name-cell">
        <div class="flex items-center gap-2">
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5 min-w-0">
              ${storeLinkHtml(g, "text-sky-400 hover:underline font-medium game-name truncate flex-1 min-w-0", escapeHtml(g.name))}
              ${ownedWish ? '<span class="text-amber-400 text-xs shrink-0" title="You already own this (matched by title)">owned</span>' : ""}
            </div>
            <div class="row-meta mt-1 flex items-center gap-1.5 flex-wrap">
              ${state.activeView === "wishlist" ? wishlistBadgeHtml(g) : storeBadgeHtml(g)}
              ${coopPillsHtml(g)}
              ${String(p.notes || "").trim() ? `<span class="has-notes-dot" title="${escapeAttr(String(p.notes).slice(0, 160))}" aria-label="Has notes">&#9998; note</span>` : ""}
              ${(p.tags || []).length ? `<span class="has-tags-dot" title="${escapeAttr((p.tags || []).join(", ").slice(0, 160))}" aria-label="Has tags">${(p.tags || []).length} tag${(p.tags || []).length === 1 ? "" : "s"}</span>` : ""}
            </div>
            ${lowConf && g.hltb_name ? `<div class="text-xs text-amber-400">HLTB match: ${escapeHtml(g.hltb_name)}</div>` : ""}
          </div>
          <div class="flex items-center gap-1.5 shrink-0">
            ${earlyAccessPillHtml(g)}
            ${hiddenGem ? '<span class="text-purple-400 shrink-0" style="cursor: default" title="Hidden gem: 90%+ rated and unplayed">✦</span>' : ""}
          </div>
        </div>
      </td>
      ${isWish ? `<td class="p-2">${wishlistStatusSelectHtml(g, p)}</td>` : `<td class="p-2">${buildStatusSelect(key, p.status)}</td>`}
      <td class="col-score p-2 text-right">${priorityScore(g).toFixed(1)}</td>
      <td class="col-played p-2 text-right text-slate-300">${formatHours(g.playtime_minutes)}</td>
      <td class="p-2 text-right">
        <button data-hltb-edit="${escapeAttr(key)}" class="bg-slate-700 hover:bg-slate-600 px-2 py-1 rounded text-xs" style="cursor: pointer" title="Open HowLongToBeat (Shift+click to override main hours)">${hltbLabel(g)}</button>
      </td>
      <td class="p-2 text-right">${g.steam_review_percent != null ? `${g.steam_review_percent}%` : "—"}</td>
      <td class="p-2 text-right">${formatPrice(g)}</td>
      <td class="p-2 text-slate-300">${formatReleaseDate(g.release_date)}</td>
      <td class="col-lastplayed p-2 text-slate-300">${formatDate(g.last_played)}</td>
      <td class="p-2 text-slate-400 text-xs truncate" title="${(g.genres || []).filter(x => !isPlatformToken(x)).join(", ")}">${(g.genres || []).filter(x => !isPlatformToken(x)).slice(0, 2).join(", ") || "—"}</td>
      <td class="p-2 notes-cell">
        <div class="tag-chip-wrap flex flex-wrap gap-1 mb-1">${tagCellHtml(g)}</div>
        <input type="text" data-game-key="${escapeAttr(key)}" data-field="notes" value="${escapeAttr(p.notes)}" placeholder="Notes..." class="notes-input bg-slate-700 border border-slate-600 rounded text-xs w-full px-2 py-1" />
      </td>
    </tr>`;
}

function paintTableBody(list, opts = {}) {
  const tbody = document.getElementById("tbody");
  if (!tbody) return;
  cancelPaintJobs();
  state._anchorScrollHandled = -1;
  const run = perfActiveRun();
  if (run) perfMark(run, 'paint:start');
  if (opts.resetScroll) {
    const shell = document.getElementById("tableShell");
    if (shell) window.scrollTo({ top: shell.offsetTop - 8, behavior: "auto" });
  }
  const isWish = state.activeView === "wishlist";
  const showScore = !!state.prefs.showScoreColumn;
  const ctx = { isWish, showScore };

  if (!list.length) {
    _virtualList = null;
    _virtualCtx = null;
    _virtualWindow = { start: 0, end: 0 };
    _virtualWindowList = null;
    tbody.innerHTML = "";
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
    return;
  }

  const anchorIdx = typeof opts.anchorIndex === "number" ? opts.anchorIndex : -1;
  _virtualList = list;
  _virtualCtx = ctx;
  ensureVirtualScrollBound();
  if (run) {
    run.meta.paintPath = anchorIdx >= 0 ? 'virtual+anchor' : 'virtual-window';
    run.meta.anchorIndex = anchorIdx >= 0 ? anchorIdx : undefined;
  }
  if (anchorIdx >= 0) {
    window.scrollTo({ top: scrollTopForRowCenter(anchorIdx), behavior: "auto" });
    // Flag so consumePendingFocus skips its own redundant scrollTo/paint pair.
    state._anchorScrollHandled = anchorIdx;
  }
  const { start, end } = computeVirtualRange(list.length, anchorIdx >= 0 ? anchorIdx : null);
  paintVirtualSlice(start, end);
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
    arrow.textContent = active ? arrowGlyph : "";
  });
}

export async function renderTable(opts) {
  const force = !!opts?.force;
  renderSortIndicators();
  const fp = tableFingerprint();
  if (!force && fp === _tableFingerprint && _lastRenderedView === state.activeView && state._visibleList && isTablePainted(state._visibleList)) {
    if (state._pendingFocusKey && state._visibleList) consumePendingFocus(state._visibleList);
    if (isTablePerfEnabled()) {
      console.log('[baklog-perf] renderTable skipped (fingerprint cache hit)', { view: state.activeView, fpLen: fp.length });
    }
    return;
  }
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
  const showScore = !!state.prefs.showScoreColumn;
  const isWish = state.activeView === "wishlist";
  const wrap = document.getElementById("tableWrap");
  wrap?.classList.toggle("table-hide-score", !showScore);
  wrap?.classList.toggle("table-hide-playtime", isWish);
  wrap?.classList.toggle("table-hide-lastplayed", isWish);
  const statusHdr = document.getElementById("statusHeader");
  if (statusHdr) statusHdr.textContent = isWish ? "Tracking" : "Status";
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

  perfMeasure(perfRun, 'chrome:dom-prep', 'chrome:start');
  perfMark(perfRun, 'paint:start');
  // resetScroll is opt-in only (opts.resetScroll). Do not tie it to force:true —
  // force only busts the fingerprint cache; scrolling to tableShell before picks
  // paint made tab switches land mid-picks when the grid expanded afterward.
  paintTableBody(list, {
    resetScroll: !!opts?.resetScroll && anchorIndex == null,
    anchorIndex,
  });
  if (list.length > 0 && !isTablePainted(list)) {
    console.warn("[renderTable] tbody empty after paint, retrying sync");
    paintTableBody(list, { anchorIndex });
  }
  perfMeasure(perfRun, 'paint:body', 'paint:start', {
    tbodyRows: tbodyRowCount(),
    paintPath: perfRun?.meta?.paintPath,
    syncPaintRows: perfRun?.meta?.syncPaintRows,
    virtualWindow: perfRun?.meta?.virtualWindow,
  });

  let base;
  if (state.activeView === "wishlist") {
    const onSale = list.filter(g => { const d = getDealInfo(g); return d && (d.cut || 0) > 0; }).length;
    const lows = list.filter(g => { const d = getDealInfo(g); return d && d.isHistoricalLow; }).length;
    const dealBits = [];
    if (onSale) dealBits.push(`${onSale} on sale`);
    if (lows) dealBits.push(`${lows} at historical low`);
    const tail = dealBits.length ? ` · ${dealBits.join(", ")}` : "";
    base = `Wishlist: ${list.length} of ${state.wishlistGames.length - state.wishlistCrossStoreHiddenKeys.size}${tail}`;
  } else if (state.activeView === "itch") {
    const total = state.itchGames.length;
    const gamesOnly = state.itchGames.filter(itchIsGame).length;
    const suffix = state.sessionPrefs.itchHideNonGames && gamesOnly !== total ? ` (${gamesOnly} games of ${total} items)` : "";
    base = `Itch.io: ${list.length} of ${state.itchGames.length}${suffix}`;
  } else {
    base = `Showing ${list.length} of ${state.allGames.filter(g => !state.crossStoreHiddenKeys.has(gameKey(g))).length} games`;
  }
  const extra = state.cleanupModeActive && state.activeView === "library" ? " · cleanup mode" : "";
  document.getElementById("rowCount").textContent = base + extra;
  perfMark(perfRun, 'post:start');
  updateBulkBar();
  buildAlphaNav(list);
  consumePendingFocus(list);
  perfMeasure(perfRun, 'post:bulk-alpha-focus', 'post:start');
  _tableFingerprint = fp;
  _lastRenderedView = state.activeView;
  // Cursor's embedded browser sometimes settles layout late on first paint —
  // tbody is populated but cells render blank until a window resize triggers
  // a layout recompute. A no-op scrollTo forces that recompute without
  // changing the user's scroll position. Harmless in real Chrome/Edge.
  if (list.length > 0) window.scrollTo(window.scrollX, window.scrollY);
  perfMeasure(perfRun, 'renderTable:total', 'renderTable:start', {
    tbodyRows: tbodyRowCount(),
    fingerprint: fp.slice(0, 80) + (fp.length > 80 ? '…' : ''),
  });
  perfEndRun(perfRun);
}
