// Cross-cutting event wiring. Currently hosts the global keyboard-shortcut
// handler. Bulk DOM event binding still lives in app.js#bindEvents until that
// surface is broken up — see js/app.js for the ~50 helpers it touches today.

import { state } from './state.js';

/**
 * Build the global keydown handler with explicit deps so this module stays
 * decoupled from app.js's private surface. Returns a function suitable for
 * `document.addEventListener("keydown", handler)`.
 *
 * Required deps (callbacks owned by app.js):
 *  - canUndo()                : boolean — whether the undo stack has entries
 *  - performUndo()            : run one step of the undo stack
 *  - closeFiltersDrawer()     : close the right-side filter drawer
 *  - updateBulkBar()          : refresh the bulk-action footer
 *  - renderTable()            : full table re-render
 *  - visibleListForKeyboard() : returns the current visible-row list
 *  - scrollToRowIndex(idx)    : scroll & focus the row at idx
 *  - openStoreForFocused()    : open the store page of the focused row
 *  - setPersonal(g, k, v)     : write a personal field
 *  - gameKey(g)               : canonical key for a game record
 *  - toggleSelection(key, on) : add/remove key from selection set
 */
export function createGlobalKeydownHandler(deps) {
  const {
    canUndo,
    performUndo,
    closeFiltersDrawer,
    updateBulkBar,
    renderTable,
    visibleListForKeyboard,
    scrollToRowIndex,
    openStoreForFocused,
    setPersonal,
    gameKey,
    toggleSelection,
  } = deps;

  return function handleGlobalKeydown(e) {
    // Ctrl/Cmd+Z runs the undo stack — checked before the input-blocker below
    // so it still works while a search/notes input has focus (matches OS).
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === "z") {
      if (!canUndo()) return;
      e.preventDefault();
      performUndo();
      return;
    }
    if (e.key === "Escape") {
      if (state.filtersDrawerOpen) { closeFiltersDrawer(); return; }
      if (!document.getElementById("addGameModal").classList.contains("hidden")) return;
      state.selectedKeys.clear();
      updateBulkBar();
      renderTable();
      return;
    }
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || tag === "select" || e.target.isContentEditable) {
      if (e.key === "/" && tag !== "input" && tag !== "textarea") { /* allow below */ }
      else return;
    }
    if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      document.getElementById("search").focus();
      return;
    }
    const list = visibleListForKeyboard();
    if (!list.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex + 1), list.length - 1);
      scrollToRowIndex(next);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      const next = Math.max((state.focusedRowIndex < 0 ? 0 : state.focusedRowIndex - 1), 0);
      scrollToRowIndex(next);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      openStoreForFocused();
      return;
    }
    if (state.activeView !== "library") return;
    const statusKeys = { b: "backlog", n: "next", p: "playing", u: "unfinished", l: "live", f: "finished", s: "skip" };
    if (statusKeys[e.key.toLowerCase()]) {
      e.preventDefault();
      const g = list[state.focusedRowIndex] || list[0];
      if (g) { setPersonal(g, "status", statusKeys[e.key.toLowerCase()]); renderTable(); }
      return;
    }
    if (e.key === " ") {
      e.preventDefault();
      const g = list[state.focusedRowIndex];
      if (!g) return;
      const key = gameKey(g);
      toggleSelection(key, !state.selectedKeys.has(key));
      renderTable();
    }
  };
}
