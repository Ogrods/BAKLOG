/**
 * ITAD deal surface gating — wishlist/dashboard UI hidden until ITAD connected.
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { state } from '../js/state.js';
import {
  isItadDealsAvailable,
  clearItadDealPrefs,
  syncItadDealSurfaces,
} from '../js/itad-deal-gate.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';
import { buildWishlistStatsHtml } from '../js/dashboard-cards.js';

beforeEach(() => {
  setAuthStatusSnapshot([]);
  state.prefs = {
    dealOnSaleOnly: true,
    dealHistoricalLowOnly: true,
    dealHideOwned: true,
    dealMinDiscount: 25,
    dealMaxPrice: 10,
    sort: { wishlist: { key: 'deal_price', dir: -1 } },
    picksTab: 'wishlistDeals',
  };
  state.activeView = 'wishlist';
  state.wishlistGames = [];
  document.body.innerHTML = `
    <div id="dashboardWishlistStats"></div>
    <button class="pick-tab" data-tab="wishlistDeals" data-pick-view="wishlist"></button>
    <div id="wishlistItadCta" class="hidden"></div>
    <div id="wishlistDealRadar"></div>
    <th id="priceHeader"></th>
  `;
});

afterEach(() => {
  document.body.innerHTML = '';
  document.documentElement.removeAttribute('data-itad-deals');
});

describe('isItadDealsAvailable', () => {
  it('is false when ITAD is disconnected', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'disconnected' }]);
    expect(isItadDealsAvailable()).toBe(false);
  });

  it('is false when ITAD is unverified', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'unverified' }]);
    expect(isItadDealsAvailable()).toBe(false);
  });

  it('is true when ITAD is connected', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    expect(isItadDealsAvailable()).toBe(true);
  });
});

describe('clearItadDealPrefs', () => {
  it('resets deal filters and wishlist deal_price sort when gated', () => {
    const changed = clearItadDealPrefs();
    expect(changed).toBe(true);
    expect(state.prefs.dealOnSaleOnly).toBe(false);
    expect(state.prefs.sort.wishlist.key).toBe('steam');
  });
});

describe('syncItadDealSurfaces', () => {
  it('hides deal radar targets and shows ITAD CTA when disconnected', () => {
    syncItadDealSurfaces({ rerender: false });
    expect(document.documentElement.dataset.itadDeals).toBe('0');
    expect(document.getElementById('dashboardWishlistStats').classList.contains('hidden')).toBe(true);
    expect(document.querySelector('[data-tab="wishlistDeals"]').classList.contains('hidden')).toBe(true);
    expect(document.getElementById('wishlistItadCta').classList.contains('hidden')).toBe(false);
    expect(buildWishlistStatsHtml()).toBe('');
  });

  it('shows deal surfaces when ITAD is connected', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    syncItadDealSurfaces({ rerender: false });
    expect(document.documentElement.dataset.itadDeals).toBe('1');
    expect(document.getElementById('dashboardWishlistStats').classList.contains('hidden')).toBe(false);
    expect(document.querySelector('[data-tab="wishlistDeals"]').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('wishlistItadCta').classList.contains('hidden')).toBe(true);
  });
});
