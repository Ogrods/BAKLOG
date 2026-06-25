/**
 * Table query filter/sort micro-benchmarks (main-thread queryGames path).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { syntheticSteamGames } from './fixtures/synthetic-games.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const budget = JSON.parse(fs.readFileSync(path.join(root, 'perf-budget.json'), 'utf8'));

describe('table query perf', () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it('queryGames on 2000 rows stays under budget', async () => {
    const { queryGames, buildQueryContext, collectTableParams } = await import('../js/table-query.js');
    const { state } = await import('../js/state.js');
    state.activeView = 'library';
    state.allGames = syntheticSteamGames(2000);
    state.prefs = {
      storeFilter: '',
      genreFilters: [],
      genreFilterMode: 'any',
      dealOnSaleOnly: false,
      dealHistoricalLowOnly: false,
      dealHideOwned: false,
      dealMinDiscount: 0,
      dealMaxPrice: 100,
      hltbBucket: null,
      releaseYearFilter: '',
      coopFilterMode: 'off',
    };
    state.sessionPrefs = { search: '' };
    state.sortKey = 'name';
    state.sortDir = 1;
    state.personal = {};
    state.crossStoreHiddenKeys = new Set();
    state.wishlistCrossStoreHiddenKeys = new Set();
    state.ownedNormNames = new Set();
    state.itadByKey = new Map();
    state.combinedPlaytime = new Map();
    state.cleanupModeActive = false;

    const params = collectTableParams(state.sessionPrefs);
    const ctx = {
      ...buildQueryContext(state, params),
      hiddenKeys: state.crossStoreHiddenKeys,
      ownedNormNames: state.ownedNormNames,
    };
    const t0 = performance.now();
    const list = queryGames({ source: state.allGames, ctx });
    const ms = performance.now() - t0;
    expect(list.length).toBeGreaterThan(0);
    expect(ms).toBeLessThan(budget.tableQueryMs['2000']);
  });
});
