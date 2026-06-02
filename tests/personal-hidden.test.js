import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { queryGames } from '../js/table-query.js';
import {
  getPersonal,
  setGameHidden,
  countUserHiddenGames,
  listUserHiddenEntries,
  addManualGame,
  removeManualGame,
  loadManualGames,
  findOrphanPersonalKeys,
  setPersonalByKey,
} from '../js/personal-storage.js';
import { gameKey } from '../js/game-core.js';

const steamGame = { store: 'steam', id: 99, name: 'Hidden Test', playtime_minutes: 0 };

function ctx(personal, view = 'library') {
  return {
    view,
    prefs: { genreFilters: [], genreFilterMode: 'OR', coopFilterMode: 'off' },
    params: { q: '', status: '', unplayed: false, earlyAccess: false, minRating: 0, maxHours: 200 },
    personal,
    hiddenKeys: new Set(),
    ownedNormNames: new Set(),
    itadByKey: {},
    cleanupModeActive: false,
    sortKey: 'name',
    sortDir: 1,
  };
}

beforeEach(() => {
  state.personal = {};
  state.allGames = [steamGame];
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
});

describe('hidden personal field', () => {
  it('defaults hidden to false', () => {
    expect(getPersonal(steamGame).hidden).toBe(false);
  });

  it('setGameHidden persists on the key', () => {
    setGameHidden(steamGame, true, { silent: true });
    expect(state.personal[gameKey(steamGame)].hidden).toBe(true);
    expect(getPersonal(steamGame).hidden).toBe(true);
  });

  it('filters hidden rows out of library query', () => {
    setGameHidden(steamGame, true, { silent: true });
    const out = queryGames({ source: [steamGame], ctx: ctx(state.personal) });
    expect(out).toHaveLength(0);
  });

  it.each([
    ['wishlist', { store: 'wishlist', id: 'w1', name: 'Wish Hidden', manual: true }],
    ['itch', { store: 'itch', id: 'i1', name: 'Itch Hidden', playtime_minutes: 0 }],
  ])('filters hidden rows out of %s query', (view, game) => {
    setGameHidden(game, true, { silent: true });
    const out = queryGames({ source: [game], ctx: ctx(state.personal, view) });
    expect(out).toHaveLength(0);
  });

  it('getPersonal does not mutate stored entry', () => {
    state.personal = { 'steam:99': { status: 'backlog' } };
    window._dataVersion = 1;
    getPersonal(steamGame);
    expect(Object.keys(state.personal['steam:99'])).toEqual(['status']);
    expect(getPersonal(steamGame).hidden).toBe(false);
  });

  it('findOrphanPersonalKeys treats hidden-only as hasData', () => {
    setPersonalByKey('steam:missing', 'hidden', true, { silent: true });
    const orphans = findOrphanPersonalKeys();
    expect(orphans.some(o => o.key === 'steam:missing' && o.hasData)).toBe(true);
  });

  it('countUserHiddenGames and listUserHiddenEntries', () => {
    setGameHidden(steamGame, true, { silent: true });
    expect(countUserHiddenGames()).toBe(1);
    const list = listUserHiddenEntries();
    expect(list).toHaveLength(1);
    expect(list[0].key).toBe('steam:99');
  });
});

describe('manual remove', () => {
  it('removeManualGame drops from manual array', () => {
    const manual = { store: 'steam', id: 'manual-x', name: 'Custom', manual: true };
    addManualGame(manual);
    expect(loadManualGames().length).toBe(1);
    removeManualGame('steam', 'manual-x');
    expect(loadManualGames().length).toBe(0);
  });
});
