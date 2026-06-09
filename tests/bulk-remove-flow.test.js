/**
 * Bulk Remove + undo end-to-end surface (re-audit bucket 2).
 *
 * Drives the real bulkRemove() / bulkSetStatus() / performUndo() against the
 * hydrated index.html so the custom-vs-pulled branch, the 12s undo toast, and
 * the manual+personal restore snapshot all run through their production paths.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';

let state;
let bulkRemove;
let bulkSetStatus;
let performUndo;
let canUndo;
let hideUndoToast;
let addManualGame;
let loadManualGames;
let setPersonal;
let gameKey;

const pulled = { store: 'steam', id: 100, name: 'Pulled Game', playtime_minutes: 0 };
const custom = { store: 'gog', id: 'manual-custom', name: 'Custom Game', manual: true, playtime_minutes: 0 };

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  vi.useFakeTimers();
  vi.stubGlobal('confirm', vi.fn(() => true));
  hydrateIndexDocument();

  ({ state } = await import('../js/state.js'));
  ({ bulkRemove, bulkSetStatus, performUndo, canUndo, hideUndoToast } = await import('../js/table-ui.js'));
  ({ addManualGame, loadManualGames, setPersonal } = await import('../js/personal-storage.js'));
  ({ gameKey } = await import('../js/game-core.js'));

  state.personal = {};
  state.allGames = [pulled, custom];
  state.wishlistGames = [];
  state.itchGames = [];
  state.selectedKeys = new Set();
  state.activeView = 'library';
  window._dataVersion = 0;
  addManualGame(custom);
});

afterEach(() => {
  hideUndoToast();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('bulkRemove custom vs pulled branching', () => {
  it('deletes custom rows but only hides pulled rows', () => {
    state.selectedKeys = new Set([gameKey(pulled), gameKey(custom)]);
    bulkRemove();

    // Custom entry is gone from the manual catalog and its personal key cleared.
    expect(loadManualGames()).toHaveLength(0);
    expect(state.personal[gameKey(custom)]).toBeUndefined();
    // Pulled entry is hidden, not deleted.
    expect(state.personal[gameKey(pulled)].hidden).toBe(true);
    expect(state.selectedKeys.size).toBe(0);
  });

  it('silently skips selected keys that resolve to no game', () => {
    state.selectedKeys = new Set([gameKey(pulled), 'steam:does-not-exist']);
    expect(() => bulkRemove()).not.toThrow();
    expect(state.personal[gameKey(pulled)].hidden).toBe(true);
    expect(state.personal['steam:does-not-exist']).toBeUndefined();
  });

  it('does nothing when the user cancels the confirm dialog', () => {
    globalThis.confirm.mockReturnValueOnce(false);
    state.selectedKeys = new Set([gameKey(pulled), gameKey(custom)]);
    bulkRemove();
    expect(loadManualGames()).toHaveLength(1);
    expect(state.personal[gameKey(pulled)]?.hidden).toBeFalsy();
  });
});

describe('remove undo symmetry', () => {
  it('undo restores both the deleted custom row and the hidden pulled row', () => {
    state.selectedKeys = new Set([gameKey(pulled), gameKey(custom)]);
    bulkRemove();
    expect(canUndo()).toBe(true);

    performUndo();
    expect(loadManualGames()).toHaveLength(1);
    expect(loadManualGames()[0].id).toBe('manual-custom');
    expect(state.personal[gameKey(pulled)]?.hidden).toBeFalsy();
  });

  it('the 12s undo toast auto-dismisses', () => {
    state.selectedKeys = new Set([gameKey(pulled)]);
    bulkRemove();
    const toast = document.getElementById('undoToast');
    expect(toast.classList.contains('hidden')).toBe(false);

    vi.advanceTimersByTime(12000);
    expect(toast.classList.contains('hidden')).toBe(true);
  });
});

describe('cleanup-mode Skip is independent of Remove', () => {
  it('bulkSetStatus("skip") sets status and pushes its own undo', () => {
    state.selectedKeys = new Set([gameKey(pulled)]);
    bulkSetStatus('skip');
    expect(state.personal[gameKey(pulled)].status).toBe('skip');
    // The pulled row is still present (Skip is a status, not a removal).
    expect(state.personal[gameKey(pulled)].hidden).toBeFalsy();

    expect(canUndo()).toBe(true);
    performUndo();
    expect(state.personal[gameKey(pulled)]?.status ?? 'backlog').toBe('backlog');
  });
});

describe('cleanup-mode visibility setup', () => {
  it('setPersonal can mark a row skipped without hiding it', () => {
    setPersonal(pulled, 'status', 'skip', { silent: true });
    expect(state.personal[gameKey(pulled)].status).toBe('skip');
    expect(state.personal[gameKey(pulled)].hidden).toBeFalsy();
  });
});
