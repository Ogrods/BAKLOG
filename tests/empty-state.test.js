/**
 * Tests for table empty-state copy when zero rows match filters.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { loadSessionPrefs } from '../js/prefs.js';
import { buildTableEmptyStateHtml } from '../js/table-empty-state.js';

beforeEach(() => {
  state.sessionPrefs = loadSessionPrefs();
  state.activeView = 'library';
  state.allGames = [{ store: 'steam', id: 1, name: 'Hades' }];
  state.wishlistGames = [];
  state.itchGames = [{ store: 'itch', id: 'x', name: 'A Game', classification: 'game' }];
  state.prefs = {
    storeFilter: '',
    wishlistStoreFilter: '',
    releaseYearFilter: '',
    hltbBucket: null,
    genreFilters: [],
  };
});

describe('buildTableEmptyStateHtml', () => {
  it('shows filter message and clear button when filters are active', () => {
    state.sessionPrefs.search = 'zzznomatch';
    const html = buildTableEmptyStateHtml('library', 13);
    expect(html).toContain('No games match your filters');
    expect(html).toContain('data-table-clear-filters');
    expect(html).not.toContain('data-table-show-itch-nongames');
  });

  it('offers show non-games on itch when hide-non-games filter is on', () => {
    state.activeView = 'itch';
    state.sessionPrefs.itchHideNonGames = true;
    state.sessionPrefs.search = 'zzznomatch';
    const html = buildTableEmptyStateHtml('itch', 13);
    expect(html).toContain('data-table-clear-filters');
    expect(html).toContain('data-table-show-itch-nongames');
  });

  it('shows neutral library hint when library is empty and no filters', () => {
    state.sessionPrefs.crossStoreDedup = false;
    state.sessionPrefs.itchHideNonGames = false;
    state.allGames = [];
    const html = buildTableEmptyStateHtml('library', 13);
    expect(html).toContain('Your library is empty');
    expect(html).toContain('Connections');
    expect(html).not.toContain('data-table-clear-filters');
  });

  it('shows neutral itch hint when itch catalog is empty', () => {
    state.sessionPrefs.crossStoreDedup = false;
    state.sessionPrefs.itchHideNonGames = false;
    state.itchGames = [];
    const html = buildTableEmptyStateHtml('itch', 13);
    expect(html).toContain('No itch.io library loaded');
    expect(html).not.toContain('data-table-clear-filters');
  });
});
