import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { rebuildAllGamesFromMetas } from '../js/library-load.js';

beforeEach(() => {
  state.libraryMeta = {};
  state.allGames = [];
  state.itchGames = [];
});

describe('nintendo library stale migration on load', () => {
  it('clears stale flags and tags nintendo_legacy when merging catalog rows', () => {
    state.libraryMeta.nintendo = {
      games: [
        { id: '1', nintendo_id: '1', name: 'Fresh Title', store: 'nintendo' },
        {
          id: '2',
          nintendo_id: '2',
          name: 'Old eShop Title',
          store: 'nintendo',
          stale: true,
          stale_since: '2026-06-15T00:00:00+00:00',
        },
      ],
    };
    rebuildAllGamesFromMetas();
    const legacy = state.allGames.find(g => g.id === '2');
    const fresh = state.allGames.find(g => g.id === '1');
    expect(fresh?.stale).toBeFalsy();
    expect(legacy?.stale).toBeFalsy();
    expect(legacy?.nintendo_legacy).toBe(true);
    expect(legacy?.stale_since).toBeUndefined();
  });
});
