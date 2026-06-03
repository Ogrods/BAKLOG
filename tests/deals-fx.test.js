/**
 * FX-converted wishlist rows — comparable sort/filter prices.
 */

import { describe, expect, it } from 'vitest';
import { gameComparablePrice, effectiveSortPrice } from '../js/deals.js';

describe('gameComparablePrice', () => {
  it('prefers price_amount over parsed formatted price', () => {
    const g = { price: '£45.00', price_amount: 58.12, currency: 'USD' };
    expect(gameComparablePrice(g)).toBe(58.12);
  });

  it('falls back to parsing price string', () => {
    expect(gameComparablePrice({ price: '$9.99' })).toBe(9.99);
  });
});

describe('effectiveSortPrice with FX', () => {
  it('orders converted amounts not raw symbol numbers', () => {
    const cheap = { price: '$30.00', price_amount: 30, currency: 'USD' };
    const pricey = { price: '£45.00', price_amount: 58, currency: 'USD' };
    expect(effectiveSortPrice(cheap)).toBeLessThan(effectiveSortPrice(pricey));
  });
});
