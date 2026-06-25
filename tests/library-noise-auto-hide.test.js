/**
 * End-to-end: noise rows stay in catalog but are hidden from library queries.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { queryGames } from '../js/table-query.js';
import { seedNoiseAutoHidden } from '../js/personal-storage.js';

const goodGame = { store: 'steam', id: 1, name: 'Hades', playtime_minutes: 0 };
const noiseGame = { store: 'steam', id: 2, name: 'YouTube', playtime_minutes: 0 };

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
  state.allGames = [goodGame, noiseGame];
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
});

describe('seedNoiseAutoHidden', () => {
  it('keeps noise in catalog but excludes it from library query', () => {
    expect(state.allGames.map(g => g.name).sort()).toEqual(['Hades', 'YouTube']);
    const before = queryGames({ source: state.allGames, ctx: ctx(state.personal) });
    expect(before.map(g => g.name)).toContain('YouTube');

    seedNoiseAutoHidden(state.allGames);

    const after = queryGames({ source: state.allGames, ctx: ctx(state.personal) });
    expect(after.map(g => g.name)).toEqual(['Hades']);
    expect(state.allGames.map(g => g.name)).toContain('YouTube');
  });

  it('is idempotent when noise is already hidden', () => {
    seedNoiseAutoHidden(state.allGames);
    const personalAfterFirst = JSON.stringify(state.personal);
    seedNoiseAutoHidden(state.allGames);
    expect(JSON.stringify(state.personal)).toBe(personalAfterFirst);
  });
});
