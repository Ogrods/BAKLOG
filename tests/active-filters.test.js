import { describe, it, expect, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { loadSessionPrefs } from '../js/prefs.js';
import { collectActiveFilters } from '../js/active-filters.js';

beforeEach(() => {
  state.activeView = 'library';
  state.allGames = [];
  state.sessionPrefs = loadSessionPrefs();
  state.prefs = {
    storeFilter: '',
    wishlistStoreFilter: '',
    releaseYearFilter: '',
    hltbBucket: null,
    genreFilters: [],
  };
});

describe('collectActiveFilters', () => {
  it('omits dedup pill when library catalog is empty', () => {
    const pills = collectActiveFilters();
    expect(pills.some((p) => p.kind === 'dedup')).toBe(false);
  });

  it('includes dedup pill when library has games and dedup is on', () => {
    state.allGames = [{ store: 'steam', id: '1', name: 'Hades' }];
    const pills = collectActiveFilters();
    expect(pills.some((p) => p.kind === 'dedup')).toBe(true);
  });
});
