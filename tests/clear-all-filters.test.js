/**
 * clearAllFilters must reset ITAD deal prefs the same way removeActiveFilter does.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';

describe('clearAllFilters deal prefs', () => {
  beforeEach(async () => {
    vi.resetModules();
    hydrateIndexDocument();
  });

  it('resets on-sale / historical-low / hide-owned / min discount / max price', async () => {
    const { state } = await import('../js/state.js');
    const { clearAllFilters } = await import('../js/filters-ui.js');

    state.prefs = {
      ...state.prefs,
      dealOnSaleOnly: true,
      dealHistoricalLowOnly: true,
      dealHideOwned: true,
      dealMinDiscount: 40,
      dealMaxPrice: 15,
      storeFilter: 'steam',
      genreFilters: ['Action'],
    };

    clearAllFilters();

    expect(state.prefs.dealOnSaleOnly).toBe(false);
    expect(state.prefs.dealHistoricalLowOnly).toBe(false);
    expect(state.prefs.dealHideOwned).toBe(false);
    expect(state.prefs.dealMinDiscount).toBe(0);
    expect(state.prefs.dealMaxPrice).toBe(100);
    expect(state.prefs.storeFilter).toBe('');
    expect(state.prefs.genreFilters).toEqual([]);
  });
});
