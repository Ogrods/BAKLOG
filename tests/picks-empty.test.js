/**
 * Picks drawer empty state — renders without fetch_*.py script names.
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { state } from '../js/state.js';
import { renderPicks, effectivePicksTab } from '../js/picks-ui.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';

function setupPicksDom() {
  document.body.innerHTML = `
    <div id="pickMeta"></div>
    <div id="picksGrid"></div>
    <button class="pick-tab active" data-tab="topRated" data-pick-view="library"></button>
    <div id="quickWinMaxWrap"></div>
    <span id="picksLimitGroup"></span>
  `;
}

beforeEach(() => {
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  state.prefs = {
    picksTab: 'topRated',
    libraryPicksTab: 'topRated',
    viewPicksLimits: { library: 16 },
    quickWinMaxHours: 15,
  };
  state.sessionPrefs = { crossStoreDedup: false };
  state.personal = {};
  state.itadByKey = {};
  state.crossStoreHiddenKeys = new Set();
  state.wishlistCrossStoreHiddenKeys = new Set();
  if (typeof window !== 'undefined') window._dataVersion = (window._dataVersion || 0) + 1;
  state.activeView = 'library';
  state.dashboardDataReady = true;
  setupPicksDom();
});

afterEach(() => {
  document.body.innerHTML = '';
});

describe('renderPicks empty library', () => {
  it('shows empty note in picksGrid with no script names', () => {
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).toContain('No games match this tab yet');
    expect(grid?.innerHTML).not.toMatch(/fetch_.*\.py/);
    expect(grid?.innerHTML).not.toContain('.py');
  });

  it('wishlist deals tab uses Fetcher health wording when wishlist is empty', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    state.activeView = 'wishlist';
    state.prefs.picksTab = 'wishlistDeals';
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).toContain('Fetcher health');
    expect(grid?.innerHTML).toContain('Connect a store');
    expect(grid?.innerHTML).not.toMatch(/fetch_.*\.py/);
  });

  it('omits user-hidden and cross-store-hidden wishlist games from deals cards', () => {
    setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
    state.activeView = 'wishlist';
    state.prefs.picksTab = 'wishlistDeals';
    state.wishlistGames = [
      { store: 'wishlist', id: '1262350', name: 'SIGNALIS', steam_review_percent: 96 },
      { store: 'wishlist', id: 'other', name: 'Other Deal', steam_review_percent: 82 },
    ];
    state.itadByKey = {
      'wishlist:1262350': { price: 4.99, cut: 75, shop: 'Steam' },
      'wishlist:other': { price: 14.99, cut: 25, shop: 'Steam' },
    };
    state.personal = { 'wishlist:1262350': { hidden: true } };
    renderPicks();
    let grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).not.toContain('SIGNALIS');
    expect(grid?.innerHTML).toContain('Other Deal');

    state.personal = {};
    state.wishlistCrossStoreHiddenKeys = new Set(['wishlist:other']);
    if (typeof window !== 'undefined') window._dataVersion = (window._dataVersion || 0) + 1;
    renderPicks();
    grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).toContain('SIGNALIS');
    expect(grid?.innerHTML).not.toContain('Other Deal');
  });

  it('falls back from wishlist deals tab when ITAD is disconnected', () => {
    setAuthStatusSnapshot([]);
    state.activeView = 'wishlist';
    state.prefs.picksTab = 'wishlistDeals';
    expect(effectivePicksTab()).toBe('topRated');
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).toContain('Connect ITAD in Connections');
  });
});
