/**
 * ITAD deal surface gating — wishlist/dashboard UI hidden until ITAD connected.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { state } from '../js/state.js';
import {
  isItadDealsAvailable,
  clearItadDealPrefs,
  syncItadDealSurfaces,
  _resetItadDealGateForTests,
} from '../js/itad-deal-gate.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';
import { buildWishlistStatsHtml } from '../js/dashboard-cards.js';
import { loadItadPrices } from '../js/library-load.js';
import * as apiClient from '../js/api-client.js';
import { fetcherFreshness } from '../js/fetcher/freshness.js';

beforeEach(() => {
  _resetItadDealGateForTests();
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
  state.libraryMeta = { ...(state.libraryMeta || {}), itad: null };
  state.itadByKey = {};
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
  vi.restoreAllMocks();
  _resetItadDealGateForTests();
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
  it('hides deal radar targets and shows ITAD CTA when disconnected', async () => {
    await syncItadDealSurfaces({ rerender: false });
    expect(document.documentElement.dataset.itadDeals).toBe('0');
    expect(document.getElementById('dashboardWishlistStats').classList.contains('hidden')).toBe(true);
    expect(document.querySelector('[data-tab="wishlistDeals"]').classList.contains('hidden')).toBe(true);
    expect(document.getElementById('wishlistItadCta').classList.contains('hidden')).toBe(false);
    expect(buildWishlistStatsHtml()).toBe('');
  });

  it('shows deal surfaces when ITAD is connected', async () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    vi.spyOn(apiClient, 'dataFetch').mockResolvedValue({
      ok: false,
      json: async () => null,
    });
    await syncItadDealSurfaces({ rerender: false });
    expect(document.documentElement.dataset.itadDeals).toBe('1');
    expect(document.getElementById('dashboardWishlistStats').classList.contains('hidden')).toBe(false);
    expect(document.querySelector('[data-tab="wishlistDeals"]').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('wishlistItadCta').classList.contains('hidden')).toBe(true);
  });

  it('keeps Wishlist Deals pick tab hidden on library and itch even when ITAD is connected', async () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    vi.spyOn(apiClient, 'dataFetch').mockResolvedValue({
      ok: false,
      json: async () => null,
    });
    for (const view of ['library', 'itch']) {
      state.activeView = view;
      await syncItadDealSurfaces({ rerender: false });
      expect(document.querySelector('[data-tab="wishlistDeals"]').classList.contains('hidden')).toBe(true);
    }
  });
});

describe('loadItadPrices / auth heal', () => {
  const fixture = {
    fetched_at: '2026-11-26T12:00:00Z',
    by_key: { 'steam:1': { price: 9.99 } },
  };

  it('leaves meta null when ITAD is disconnected', async () => {
    state.libraryMeta.itad = { fetched_at: '2026-01-01T00:00:00Z', by_key: {} };
    setAuthStatusSnapshot([{ key: 'itad', status: 'disconnected' }]);
    const fetchSpy = vi.spyOn(apiClient, 'dataFetch');
    await loadItadPrices();
    expect(state.libraryMeta.itad).toBeNull();
    expect(state.itadByKey).toEqual({});
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('restores meta via syncItadDealSurfaces after ITAD connects', async () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'disconnected' }]);
    await loadItadPrices();
    expect(state.libraryMeta.itad).toBeNull();

    vi.spyOn(apiClient, 'dataFetch').mockImplementation(async (url) => {
      if (String(url).includes('itad_prices.json')) {
        return { ok: true, json: async () => fixture };
      }
      return { ok: false, json: async () => null };
    });

    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    await syncItadDealSurfaces({ rerender: false });

    expect(state.libraryMeta.itad).toEqual(fixture);
    const fresh = fetcherFreshness({ key: 'itad', metaKey: 'itad' });
    expect(fresh.status).not.toBe('missing');
    expect(fresh.ageLabel).not.toBe(' - ');
    expect(fresh.iso).toBe(fixture.fetched_at);
  });

  it('reloads when already connected but meta is still null', async () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    state.libraryMeta.itad = { fetched_at: '2026-11-26T10:00:00Z', by_key: {} };
    await syncItadDealSurfaces({ rerender: false });

    state.libraryMeta.itad = null;
    const fetchSpy = vi.spyOn(apiClient, 'dataFetch').mockImplementation(async (url) => {
      if (String(url).includes('itad_prices.json')) {
        return { ok: true, json: async () => fixture };
      }
      return { ok: false, json: async () => null };
    });

    await syncItadDealSurfaces({ rerender: false });
    expect(fetchSpy).toHaveBeenCalled();
    expect(state.libraryMeta.itad).toEqual(fixture);
  });
});
