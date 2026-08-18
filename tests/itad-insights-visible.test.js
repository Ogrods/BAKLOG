/**
 * Dashboard insight/marquee deal lines use the same visible wishlist as the radar.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';
import { buildInsightPool, buildMarqueeItems } from '../js/dashboard-insights.js';
import { getLibrarySnapshot, invalidateLibrarySnapshot } from '../js/sabermetrics.js';

const signalis = {
  store: 'wishlist',
  id: '1262350',
  name: 'SIGNALIS',
  steam_review_percent: 96,
  steam_review_count: 20000,
};
const otherDeal = {
  store: 'wishlist',
  id: 'other',
  name: 'Other Deal',
  steam_review_percent: 82,
};

function seed() {
  setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
  state.personal = {};
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.wishlistGames = [signalis, otherDeal];
  state.itadByKey = {
    'wishlist:1262350': {
      price: 4.99,
      regular: 19.99,
      cut: 75,
      is_historical_low: true,
      shop: 'Steam',
    },
    'wishlist:other': { price: 14.99, regular: 19.99, cut: 25, shop: 'Steam' },
  };
  state.prefs = { ...(state.prefs || {}), metricsDisabled: [] };
  invalidateLibrarySnapshot();
}

beforeEach(() => {
  seed();
});

describe('insight and marquee deal lines ignore hidden wishlist rows', () => {
  it('buildInsightPool Top deal skips a user-hidden wishlist game', () => {
    state.personal = { 'wishlist:1262350': { hidden: true } };
    const pool = buildInsightPool([]);
    const html = pool.map((e) => e.html).join(' ');
    expect(html).not.toContain('SIGNALIS');
    expect(html).toContain('Other Deal');
  });

  it('buildMarqueeItems top deal skips a cross-store-hidden wishlist game', () => {
    state.wishlistCrossStoreHiddenKeys = new Set(['wishlist:1262350']);
    const games = [{ store: 'steam', id: '1', name: 'Lib', playtime_minutes: 0 }];
    const snap = getLibrarySnapshot(games);
    const items = buildMarqueeItems(games, snap);
    const blob = items.map((it) => `${it.label} ${it.valueHtml || it.value || ''}`).join(' ');
    expect(blob).not.toContain('SIGNALIS');
    expect(blob).toContain('Other Deal');
  });
});
