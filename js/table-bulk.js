import { state } from './state.js';
import { escapeHtml } from './dom-util.js';
import {
  renderBulkStatusButtons,
  findGameByKey,
  getSameTitleKeysInRealm,
  recomputeCrossStoreHidden,
} from './game-core.js';
import { STATUS_LABELS } from './row-templates.js';
import {
  setPersonal,
  savePersonal,
  bumpPersonalMemo,
  removeManualGame,
  loadManualGames,
  saveManualGames,
  setGameHidden,
  addNintendoDroppedId,
  NINTENDO_DROPPED_KEY,
  HIDDEN_TITLE_NORMS_LIBRARY_KEY,
  HIDDEN_TITLE_NORMS_WISHLIST_KEY,
} from './personal-storage.js';
import { libraryLoadApi } from './library-load-api.js';
import { renderSummary } from './filters-ui.js';
import { renderPicks } from './picks-ui.js';
import { scheduleDashboardRender } from './dashboard.js';
import {
  invalidateTableCacheInPlace,
  renderTable,
  focusGame,
} from './table-ui.js';

function refreshAfterManualChange() {
  libraryLoadApi.refreshAfterManualChange();
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
  invalidateTableCacheInPlace();
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
  invalidateTableCacheInPlace();
  renderTable();
  const statusLabel = (STATUS_LABELS && STATUS_LABELS[status]) || status;
  pushUndo({
    label: `Set ${affectedKeys.length} game${affectedKeys.length === 1 ? "" : "s"} to ${statusLabel}`,
    undo: () => restorePersonalFromSnapshot(snap),
  });
}

function snapshotRemoveState(keys) {
  // Hiding a pulled row mirrors the hidden flag across same-realm title keys and
  // adds its title norm to the library or wishlist norms list. Capture both so
  // undo fully reverses the hide — otherwise applyHiddenTitleNorms re-hides the
  // row on the next merge and the "Removed N games" undo silently leaves it hidden.
  const expanded = new Set(keys);
  for (const key of keys) {
    const g = findGameByKey(key);
    if (g) for (const k of getSameTitleKeysInRealm(g)) expanded.add(k);
  }
  expanded.add(HIDDEN_TITLE_NORMS_LIBRARY_KEY);
  expanded.add(HIDDEN_TITLE_NORMS_WISHLIST_KEY);
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
  invalidateTableCacheInPlace();
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