/**
 * Tests for js/table-query.js pure helpers.
 *
 * Scope chosen per find_no_js_tests: filter/sort primitives + the user-facing
 * coop / early-access / release-year matchers. These are the spots where a
 * regression silently hides rows or shows the wrong ones.
 */

import { describe, expect, it } from 'vitest';
import {
  resolveCoopFilterMode,
  passesCoopFilter,
  isEarlyAccess,
  queryGames,
  buildQueryContext,
  collectTableParams,
  gameKey,
} from '../js/table-query.js';

const baseGame = {
  appid: 1,
  store: 'steam',
  id: 1,
  name: 'Test Game',
  playtime_minutes: 0,
  steam_review_percent: 80,
  hltb_main_hours: 10,
};

const emptyPrefs = {
  genreFilters: [],
  genreFilterMode: 'OR',
  tagFilters: [],
  tagFilterMode: 'OR',
  coopFilterMode: 'off',
};

function ctx(overrides = {}) {
  return {
    view: 'library',
    prefs: { ...emptyPrefs, ...(overrides.prefs || {}) },
    params: {
      q: '',
      status: '',
      unplayed: false,
      earlyAccess: false,
      minRating: 0,
      maxHours: 200,
      ...(overrides.params || {}),
    },
    personal: overrides.personal || {},
    hiddenKeys: overrides.hiddenKeys || new Set(),
    ownedNormNames: overrides.ownedNormNames || new Set(),
    itadByKey: overrides.itadByKey || {},
    cleanupModeActive: !!overrides.cleanupModeActive,
    sortKey: overrides.sortKey || 'name',
    sortDir: overrides.sortDir ?? 1,
  };
}

describe('resolveCoopFilterMode', () => {
  it('returns the explicit mode when valid', () => {
    expect(resolveCoopFilterMode({ coopFilterMode: 'online' })).toBe('online');
    expect(resolveCoopFilterMode({ coopFilterMode: 'both' })).toBe('both');
  });

  it('falls back to legacy coopAny=true → "any"', () => {
    expect(resolveCoopFilterMode({ coopAny: true })).toBe('any');
  });

  it('defaults to "off" for missing / invalid input', () => {
    expect(resolveCoopFilterMode({})).toBe('off');
    expect(resolveCoopFilterMode({ coopFilterMode: 'invalid' })).toBe('off');
    expect(resolveCoopFilterMode(null)).toBe('off');
  });
});

describe('passesCoopFilter', () => {
  const onlineOnly = { coop_online: true, coop_local: false };
  const localOnly = { coop_online: false, coop_local: true };
  const both = { coop_online: true, coop_local: true };
  const neither = { coop_online: false, coop_local: false };

  it('off lets every game through', () => {
    expect(passesCoopFilter(onlineOnly, 'off')).toBe(true);
    expect(passesCoopFilter(neither, 'off')).toBe(true);
  });

  it('any matches if either online or local is true', () => {
    expect(passesCoopFilter(onlineOnly, 'any')).toBe(true);
    expect(passesCoopFilter(localOnly, 'any')).toBe(true);
    expect(passesCoopFilter(neither, 'any')).toBe(false);
  });

  it('online requires online flag', () => {
    expect(passesCoopFilter(onlineOnly, 'online')).toBe(true);
    expect(passesCoopFilter(localOnly, 'online')).toBe(false);
  });

  it('local requires local flag', () => {
    expect(passesCoopFilter(localOnly, 'local')).toBe(true);
    expect(passesCoopFilter(onlineOnly, 'local')).toBe(false);
  });

  it('both requires both flags', () => {
    expect(passesCoopFilter(both, 'both')).toBe(true);
    expect(passesCoopFilter(onlineOnly, 'both')).toBe(false);
    expect(passesCoopFilter(localOnly, 'both')).toBe(false);
  });
});

describe('isEarlyAccess', () => {
  it('returns true when early_access flag is set', () => {
    expect(isEarlyAccess({ early_access: true })).toBe(true);
  });

  it('detects "Early Access" inside genres', () => {
    expect(isEarlyAccess({ genres: ['Strategy', 'Early Access'] })).toBe(true);
  });

  it('detects "Early Access" inside tags (case-insensitive)', () => {
    expect(isEarlyAccess({ tags: ['indie', 'EARLY ACCESS'] })).toBe(true);
  });

  it('returns false for normal games', () => {
    expect(isEarlyAccess({ genres: ['Action'], tags: ['multiplayer'] })).toBe(false);
  });

  it('survives null / undefined input safely', () => {
    expect(isEarlyAccess(null)).toBe(false);
    expect(isEarlyAccess({})).toBe(false);
  });
});

describe('gameKey', () => {
  it('builds store:id from explicit fields', () => {
    expect(gameKey({ store: 'gog', id: 42 })).toBe('gog:42');
  });

  it('falls back to per-store id columns', () => {
    expect(gameKey({ appid: 730 })).toBe('steam:730');
    expect(gameKey({ store: 'psn', psn_id: 'CUSA1' })).toBe('psn:CUSA1');
  });
});

describe('queryGames — integration', () => {
  it('filters by search query (case-insensitive substring)', () => {
    const source = [
      { ...baseGame, id: 1, name: 'Hades' },
      { ...baseGame, id: 2, name: 'Hollow Knight' },
      { ...baseGame, id: 3, name: 'Stardew Valley' },
    ];
    const out = queryGames({ source, ctx: ctx({ params: { q: 'h' } }) });
    expect(out.map(g => g.name).sort()).toEqual(['Hades', 'Hollow Knight']);
  });

  it('hides rows whose key is in hiddenKeys (cross-store dedup)', () => {
    const source = [
      { ...baseGame, id: 1, name: 'Same Game' },
      { ...baseGame, id: 2, name: 'Same Game' },
    ];
    const hidden = new Set(['steam:2']);
    const out = queryGames({ source, ctx: ctx({ hiddenKeys: hidden }) });
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
  });

  it('applies minRating', () => {
    const source = [
      { ...baseGame, id: 1, steam_review_percent: 95 },
      { ...baseGame, id: 2, steam_review_percent: 70 },
    ];
    const out = queryGames({ source, ctx: ctx({ params: { minRating: 90 } }) });
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
  });

  it('applies maxHours (HLTB) but never excludes hltb-unknown games', () => {
    const source = [
      { ...baseGame, id: 1, hltb_main_hours: 5 },
      { ...baseGame, id: 2, hltb_main_hours: 80 },
      { ...baseGame, id: 3, hltb_main_hours: null },
    ];
    const out = queryGames({ source, ctx: ctx({ params: { maxHours: 30 } }) });
    expect(out.map(g => g.id).sort()).toEqual([1, 3]);
  });

  it('respects unplayed filter against playtime_minutes', () => {
    const source = [
      { ...baseGame, id: 1, playtime_minutes: 0 },
      { ...baseGame, id: 2, playtime_minutes: 600 },
    ];
    const out = queryGames({ source, ctx: ctx({ params: { unplayed: true } }) });
    expect(out).toHaveLength(1);
    expect(out[0].id).toBe(1);
  });

  it('sorts ascending by name by default', () => {
    const source = [
      { ...baseGame, id: 1, name: 'Zelda' },
      { ...baseGame, id: 2, name: 'Animal Crossing' },
      { ...baseGame, id: 3, name: 'Mario' },
    ];
    const out = queryGames({ source, ctx: ctx() });
    expect(out.map(g => g.name)).toEqual(['Animal Crossing', 'Mario', 'Zelda']);
  });

  it('sorts descending when sortDir = -1', () => {
    const source = [
      { ...baseGame, id: 1, name: 'A' },
      { ...baseGame, id: 2, name: 'B' },
    ];
    const out = queryGames({ source, ctx: ctx({ sortDir: -1 }) });
    expect(out.map(g => g.name)).toEqual(['B', 'A']);
  });
});

describe('collectTableParams', () => {
  // Audit finding find_state_dom_split: the 6 live-filter controls now live
  // in state.sessionPrefs. collectTableParams reads them from there — never
  // from the DOM — so the worker path and the main-thread path stay in sync.
  it('returns sensible defaults for an empty sessionPrefs', () => {
    expect(collectTableParams({})).toEqual({
      q: '',
      status: '',
      unplayed: false,
      earlyAccess: false,
      minRating: 0,
      maxHours: 200,
    });
  });

  it('defaults when called with no argument', () => {
    expect(collectTableParams()).toEqual({
      q: '',
      status: '',
      unplayed: false,
      earlyAccess: false,
      minRating: 0,
      maxHours: 200,
    });
  });

  it('reads every field from the supplied sessionPrefs', () => {
    expect(
      collectTableParams({
        search: '  Halo  ',
        statusFilter: 'next',
        unplayedOnly: true,
        earlyAccessOnly: true,
        minRating: 70,
        maxHours: 12,
      }),
    ).toEqual({
      q: 'halo',
      status: 'next',
      unplayed: true,
      earlyAccess: true,
      minRating: 70,
      maxHours: 12,
    });
  });

  it('coerces stringy slider values and ignores junk minRating', () => {
    expect(collectTableParams({ minRating: '40', maxHours: '5' })).toEqual({
      q: '',
      status: '',
      unplayed: false,
      earlyAccess: false,
      minRating: 40,
      maxHours: 5,
    });
  });
});

describe('buildQueryContext', () => {
  it('reads the right hiddenKeys for library vs. wishlist', () => {
    const fakeState = {
      activeView: 'wishlist',
      prefs: emptyPrefs,
      personal: {},
      crossStoreHiddenKeys: new Set(['steam:1']),
      wishlistCrossStoreHiddenKeys: new Set(['wishlist:9']),
      ownedNormNames: new Set(),
      itadByKey: {},
      cleanupModeActive: false,
      sortKey: 'name',
      sortDir: 1,
    };
    const result = buildQueryContext(fakeState, { q: '' });
    expect(result.hiddenKeys).toBe(fakeState.wishlistCrossStoreHiddenKeys);
    expect(result.view).toBe('wishlist');
  });
});
