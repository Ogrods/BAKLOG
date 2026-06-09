/**
 * Tests for js/table-ui.js::tableFingerprint — cache invalidation inputs.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { loadSessionPrefs } from '../js/prefs.js';
import { tableFingerprint } from '../js/table-ui.js';

function resetState() {
  state.activeView = 'library';
  state.sortKey = 'name';
  state.sortDir = 1;
  state.sessionPrefs = loadSessionPrefs();
  state.prefs = {
    storeFilter: '',
    wishlistStoreFilter: '',
    releaseYearFilter: '',
    hltbBucket: null,
    genreFilters: [],
    genreFilterMode: 'OR',
    dealOnSaleOnly: false,
    dealHistoricalLowOnly: false,
    dealHideOwned: false,
    dealMinDiscount: 0,
    dealMaxPrice: 100,
    columns: {},
    coopFilterMode: 'off',
  };
  state.cleanupModeActive = false;
  state.allGames = [{ store: 'steam', id: 1, appid: 1, name: 'A' }];
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
}

beforeEach(() => {
  resetState();
});

describe('tableFingerprint', () => {
  it('is stable when tracked inputs are unchanged', () => {
    const a = tableFingerprint();
    const b = tableFingerprint();
    expect(a).toBe(b);
  });

  it('changes when sort, search, store filter, deal prefs, or coop mode change', () => {
    const base = tableFingerprint();
    state.sortKey = 'playtime';
    expect(tableFingerprint()).not.toBe(base);

    resetState();
    const b2 = tableFingerprint();
    state.sessionPrefs.search = 'zelda';
    expect(tableFingerprint()).not.toBe(b2);

    resetState();
    const b3 = tableFingerprint();
    state.prefs.storeFilter = 'steam';
    expect(tableFingerprint()).not.toBe(b3);

    resetState();
    const b4 = tableFingerprint();
    state.prefs.dealMinDiscount = 25;
    expect(tableFingerprint()).not.toBe(b4);

    resetState();
    const b5 = tableFingerprint();
    state.prefs.coopFilterMode = 'online';
    expect(tableFingerprint()).not.toBe(b5);

    resetState();
    const b6 = tableFingerprint();
    state.cleanupModeActive = true;
    expect(tableFingerprint()).not.toBe(b6);
  });

  it('changes when library row counts or data version change', () => {
    const base = tableFingerprint();
    state.allGames.push({ store: 'steam', id: 2, appid: 2, name: 'B' });
    expect(tableFingerprint()).not.toBe(base);

    resetState();
    const b2 = tableFingerprint();
    window._dataVersion = 3;
    expect(tableFingerprint()).not.toBe(b2);
  });
});
