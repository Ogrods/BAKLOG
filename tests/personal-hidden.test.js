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
  applyHiddenTitleNorms,
  unhidePersonalKey,
} from '../js/personal-storage.js';
import { gameKey } from '../js/game-core.js';

const steamGame = { store: 'steam', id: 99, name: 'Hidden Test', playtime_minutes: 0 };
const fortniteSteam = { store: 'steam', id: 1, name: 'Fortnite', playtime_minutes: 0 };
const fortniteEpic = { store: 'epic', id: 'abc', name: 'Fortnite', playtime_minutes: 0 };

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

describe('cross-store hidden mirroring', () => {
  const fortniteWish = {
    store: 'wishlist',
    id: 'nintendo-icey',
    name: 'Fortnite',
    wishlist_store: 'nintendo',
  };

  beforeEach(() => {
    state.allGames = [fortniteSteam, fortniteEpic];
    state.wishlistGames = [fortniteWish];
  });

  it('setGameHidden on one copy hides every store copy of the title', () => {
    setGameHidden(fortniteSteam, true, { silent: true });
    expect(state.personal[gameKey(fortniteSteam)].hidden).toBe(true);
    expect(state.personal[gameKey(fortniteEpic)].hidden).toBe(true);
    expect(getPersonal(fortniteEpic).hidden).toBe(true);
    expect(Array.isArray(state.personal.__hidden_title_norms_v1)).toBe(true);
    expect(state.personal.__hidden_title_norms_v1).toContain('fortnite');
  });

  it('restore on one copy clears hidden on all store copies', () => {
    setGameHidden(fortniteSteam, true, { silent: true });
    setGameHidden(fortniteEpic, false, { silent: true });
    expect(state.personal[gameKey(fortniteSteam)].hidden).toBe(false);
    expect(state.personal[gameKey(fortniteEpic)].hidden).toBe(false);
    expect(state.personal.__hidden_title_norms_v1 || []).not.toContain('fortnite');
  });

  it('applyHiddenTitleNorms re-hides newly-added keys (key churn / new connection)', () => {
    setGameHidden(fortniteEpic, true, { silent: true });
    expect(state.personal.__hidden_title_norms_v1).toContain('fortnite');

    // Catalog changes: a new store copy appears later.
    const fortniteXbox = { store: 'xbox', id: 'x1', name: 'Fortnite', playtime_minutes: 0 };
    state.allGames = [fortniteSteam, fortniteEpic, fortniteXbox];

    // The norm-based hidden set should re-apply onto whatever keys exist now.
    applyHiddenTitleNorms({ silent: true });
    expect(state.personal[gameKey(fortniteXbox)].hidden).toBe(true);
  });

  it('wishlist hide does not hide owned library copies of the same title', () => {
    setGameHidden(fortniteWish, true, { silent: true });
    expect(state.personal[gameKey(fortniteWish)].hidden).toBe(true);
    expect(state.personal.__hidden_title_norms_wishlist_v1).toContain('fortnite');
    expect(state.personal.__hidden_title_norms_v1 || []).not.toContain('fortnite');
    expect(state.personal[gameKey(fortniteSteam)]?.hidden).not.toBe(true);
    expect(state.personal[gameKey(fortniteEpic)]?.hidden).not.toBe(true);
  });

  it('library hide does not hide wishlist copies of the same title', () => {
    setGameHidden(fortniteSteam, true, { silent: true });
    expect(state.personal[gameKey(fortniteSteam)].hidden).toBe(true);
    expect(state.personal[gameKey(fortniteWish)]?.hidden).not.toBe(true);
    expect(state.personal.__hidden_title_norms_wishlist_v1 || []).not.toContain('fortnite');
  });

  it('applyHiddenTitleNorms keeps wishlist and library realms separate', () => {
    setGameHidden(fortniteWish, true, { silent: true });
    const fortniteXbox = { store: 'xbox', id: 'x1', name: 'Fortnite', playtime_minutes: 0 };
    state.allGames = [fortniteSteam, fortniteEpic, fortniteXbox];
    applyHiddenTitleNorms({ silent: true });
    expect(state.personal[gameKey(fortniteWish)].hidden).toBe(true);
    expect(state.personal[gameKey(fortniteXbox)]?.hidden).not.toBe(true);
  });

  it('unhiding library copy leaves wishlist hide intact', () => {
    setGameHidden(fortniteWish, true, { silent: true });
    setGameHidden(fortniteSteam, true, { silent: true });
    setGameHidden(fortniteSteam, false, { silent: true });
    expect(state.personal[gameKey(fortniteSteam)].hidden).toBe(false);
    expect(state.personal[gameKey(fortniteEpic)].hidden).toBe(false);
    expect(state.personal[gameKey(fortniteWish)].hidden).toBe(true);
    expect(state.personal.__hidden_title_norms_wishlist_v1).toContain('fortnite');
  });

  it('orphan unhide clears sticky library title-norm', () => {
    state.allGames = [];
    state.wishlistGames = [];
    state.personal = {
      'steam:gone': {
        status: 'backlog',
        notes: '',
        priority: 0,
        hltb_override: null,
        hidden: true,
        hidden_title_norm: 'fortnite',
      },
      __hidden_title_norms_v1: ['fortnite'],
      __hidden_title_norms_migrated_v1: true,
      __hidden_title_norms_realm_split_v1: true,
      __hidden_title_norms_scrub_unused_v1: true,
    };
    unhidePersonalKey('steam:gone', { silent: true });
    expect(state.personal['steam:gone'].hidden).toBe(false);
    expect(state.personal.__hidden_title_norms_v1 || []).not.toContain('fortnite');
  });

  it('scrubUnusedHideNorms drops library norms with no remaining library hides', () => {
    state.allGames = [fortniteSteam];
    state.wishlistGames = [fortniteWish];
    state.personal = {
      [gameKey(fortniteWish)]: {
        status: 'backlog',
        notes: '',
        priority: 0,
        hltb_override: null,
        hidden: true,
        hidden_title_norm: 'fortnite',
      },
      // Pre-split pollution: library norm still lists fortnite though library is visible.
      __hidden_title_norms_v1: ['fortnite'],
      __hidden_title_norms_wishlist_v1: ['fortnite'],
      __hidden_title_norms_migrated_v1: true,
      __hidden_title_norms_realm_split_v1: true,
    };
    applyHiddenTitleNorms({ silent: true });
    expect(state.personal.__hidden_title_norms_v1 || []).not.toContain('fortnite');
    expect(state.personal.__hidden_title_norms_wishlist_v1).toContain('fortnite');
    expect(state.personal[gameKey(fortniteSteam)]?.hidden).not.toBe(true);
    expect(state.personal[gameKey(fortniteWish)].hidden).toBe(true);
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
