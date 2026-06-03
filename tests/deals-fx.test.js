/**
 * FX-converted wishlist rows — comparable sort/filter prices.
 */

import { describe, expect, it } from 'vitest';
import { gameComparablePrice, effectiveSortPrice } from '../js/deals.js';
import { queryGames, buildQueryContext } from '../js/table-query.js';

describe('gameComparablePrice', () => {
  it('prefers price_amount over parsed formatted price', () => {
    const g = { price: '£45.00', price_amount: 58.12, currency: 'USD' };
    expect(gameComparablePrice(g)).toBe(58.12);
  });

  it('falls back to parsing price string', () => {
    expect(gameComparablePrice({ price: '$9.99' }, 'USD')).toBe(9.99);
  });

  it('returns null when native currency differs from display and no price_amount', () => {
    const g = { price: '¥5980', currency: 'JPY' };
    expect(gameComparablePrice(g, 'USD')).toBeNull();
  });
});

describe('effectiveSortPrice with FX', () => {
  it('orders converted amounts not raw symbol numbers', () => {
    const cheap = { price: '$30.00', price_amount: 30, currency: 'USD' };
    const pricey = { price: '£45.00', price_amount: 58, currency: 'USD' };
    expect(effectiveSortPrice(cheap)).toBeLessThan(effectiveSortPrice(pricey));
  });
});

describe('dealMaxPrice with mixed FX rows', () => {
  it('excludes unconverted JPY from max-price filter when display is USD', () => {
    const state = {
      activeView: 'wishlist',
      prefs: {
        dealMaxPrice: 50,
        dealOnSaleOnly: false,
        dealHistoricalLowOnly: false,
        dealMinDiscount: 0,
        dealHideOwned: false,
      },
      sessionPrefs: {},
      personal: {},
      crossStoreHiddenKeys: new Set(),
      wishlistCrossStoreHiddenKeys: new Set(),
      ownedNormNames: new Set(),
      itadByKey: {},
      cleanupModeActive: false,
      sortKey: 'name',
      sortDir: 1,
      crossStorePlaytimeByKey: new Map(),
      libraryMeta: { itad: { currency: 'USD' } },
    };
    const jpyOnly = { name: 'Big JPY', store: 'gog', id: '1', price: '¥5980', currency: 'JPY' };
    const usdConverted = {
      name: 'Small USD',
      store: 'gog',
      id: '2',
      price: '$30.00',
      price_amount: 30,
      currency: 'USD',
    };
    const ctx = buildQueryContext(state, {});
    const out = queryGames({ source: [jpyOnly, usdConverted], ctx });
    expect(out.map((g) => g.name)).toEqual(['Small USD']);
  });
});
