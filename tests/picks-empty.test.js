/**
 * Picks drawer empty state — renders without fetch_*.py script names.
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { state } from '../js/state.js';
import { renderPicks } from '../js/picks-ui.js';

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
  state.crossStoreHiddenKeys = new Set();
  state.wishlistCrossStoreHiddenKeys = new Set();
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
    state.activeView = 'wishlist';
    state.prefs.picksTab = 'wishlistDeals';
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid?.innerHTML).toContain('Fetcher health');
    expect(grid?.innerHTML).toContain('Connect a store');
    expect(grid?.innerHTML).not.toMatch(/fetch_.*\.py/);
  });
});
