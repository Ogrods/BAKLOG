/**
 * State integrity across add/remove (re-audit bucket 4).
 *
 * Confirms the three storage layers stay distinct: manual[] (full custom game
 * objects), personal{} (per-key overlays incl. hidden), and the in-memory
 * catalogs. Also pins multi-tab behavior: personal syncs across tabs via the
 * storage event, manual[] does not.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('manual[] vs personal{} vs hidden', () => {
  let state;
  let storage;
  let gameKey;

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    ({ state } = await import('../js/state.js'));
    storage = await import('../js/personal-storage.js');
    ({ gameKey } = await import('../js/game-core.js'));
    state.personal = {};
    state.allGames = [];
    state.wishlistGames = [];
    state.itchGames = [];
    window._dataVersion = 0;
  });

  it('hiding a pulled row writes personal{} only; manual[] and the catalog are untouched', () => {
    const pulled = { store: 'steam', id: 5, name: 'Pulled', playtime_minutes: 0 };
    state.allGames = [pulled];
    storage.setGameHidden(pulled, true, { silent: true });

    expect(state.personal[gameKey(pulled)].hidden).toBe(true);
    expect(storage.loadManualGames()).toHaveLength(0);
    // The game object still lives in the catalog (hidden is a render-time filter).
    expect(state.allGames).toHaveLength(1);
  });

  it('a custom row lives in manual[] and is keyed in personal{} only once edited', () => {
    const custom = { store: 'gog', id: 'manual-z', name: 'Zed', manual: true, playtime_minutes: 0 };
    storage.addManualGame(custom);
    expect(storage.loadManualGames()).toHaveLength(1);
    expect(state.personal[gameKey(custom)]).toBeUndefined();

    storage.setPersonal(custom, 'status', 'next', { silent: true });
    expect(state.personal[gameKey(custom)].status).toBe('next');
  });

  it('removing a custom row drops manual[] but leaves an orphan personal entry until cleared', () => {
    const custom = { store: 'gog', id: 'manual-z', name: 'Zed', manual: true, playtime_minutes: 0 };
    storage.addManualGame(custom);
    storage.setPersonal(custom, 'status', 'next', { silent: true });
    const key = gameKey(custom);

    storage.removeManualGame('gog', 'manual-z');
    expect(storage.loadManualGames()).toHaveLength(0);
    // The personal overlay survives a bare removeManualGame — bulkRemove is what
    // also deletes state.personal[key]; findOrphanPersonalKeys surfaces the rest.
    expect(state.personal[key]).toBeDefined();
    state.allGames = [];
    expect(storage.findOrphanPersonalKeys().some(o => o.key === key)).toBe(true);
  });
});

describe('multi-tab sync boundary', () => {
  let state;
  let storage;

  beforeEach(async () => {
    vi.resetModules();
    localStorage.clear();
    ({ state } = await import('../js/state.js'));
    storage = await import('../js/personal-storage.js');
    state.personal = { 'steam:1': { status: 'backlog' } };
    localStorage.setItem(storage.personalStorageKey(), JSON.stringify(state.personal));
    storage.installPersonalStorageSync();
  });

  it('a personal storage event from another tab updates state.personal', () => {
    const incoming = { 'steam:1': { status: 'playing' } };
    window.dispatchEvent(new StorageEvent('storage', {
      key: storage.personalStorageKey(),
      newValue: JSON.stringify(incoming),
      storageArea: localStorage,
    }));
    expect(state.personal['steam:1'].status).toBe('playing');
  });

  it('a manual-games storage event does NOT update the in-memory manual cache (documented gap)', () => {
    // installPersonalStorageSync only listens for the personal key, so manual
    // adds in another tab are not reflected until a reload. This pins the
    // current behavior referenced by the p2_deferred_ux_surfaces follow-up.
    const manualKey = storage.manualStorageKey?.();
    expect(storage.loadManualGames()).toHaveLength(0);
    if (manualKey) {
      const incoming = [{ store: 'gog', id: 'manual-from-tab-b', name: 'Tab B', manual: true }];
      localStorage.setItem(manualKey, JSON.stringify(incoming));
      window.dispatchEvent(new StorageEvent('storage', {
        key: manualKey,
        newValue: JSON.stringify(incoming),
        storageArea: localStorage,
      }));
    }
    // No live reaction: state did not pull the new manual row from the event.
    expect(state.allGames.some(g => g.id === 'manual-from-tab-b')).toBe(false);
  });
});
