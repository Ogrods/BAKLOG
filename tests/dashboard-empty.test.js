/**
 * Dashboard wishlist deal radar empty layout — three cards, no script names.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { buildWishlistStatsHtml } from '../js/dashboard-cards.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';

beforeEach(() => {
  state.wishlistGames = [];
  setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
});

describe('buildWishlistStatsHtml empty wishlist', () => {
  it('renders three deal cards instead of one full-width message', () => {
    const html = buildWishlistStatsHtml();
    expect(html).toContain("Today&apos;s top deal");
    expect(html).toContain('Sale scoreboard');
    expect(html).toContain('Steals waiting');
    expect(html).not.toContain('sm:col-span-3');
    expect(html).not.toContain('fetch_wishlist');
    expect(html).not.toMatch(/fetch_.*\.py/);
    expect(html).not.toContain('.py');
  });

  it('uses user-friendly wishlist empty hint on hero card', () => {
    const html = buildWishlistStatsHtml();
    expect(html).toContain('wishlist fetcher');
    expect(html).toContain('Connect a store');
  });

  it('returns empty html when ITAD is not connected', () => {
    setAuthStatusSnapshot([]);
    expect(buildWishlistStatsHtml()).toBe('');
  });
});
