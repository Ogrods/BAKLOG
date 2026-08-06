/**
 * Picks grid must keep a fixed tile count when a sponsored pick slot is shown.
 */

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { state } from '../js/state.js';
import { renderPicks } from '../js/picks-ui.js';
import { setAuthStatusSnapshot } from '../js/connections-status.js';
import { dismissSponsoredDeal, __resetDismissedSponsorsForTest, __setSponsorsForTest } from '../js/sponsored-deals.js';
import * as authGate from '../js/auth-gate.js';

function setupPicksDom() {
  document.body.innerHTML = `
    <div id="pickMeta"></div>
    <div id="picksGrid"></div>
    <button class="pick-tab active" data-tab="wishlistDeals" data-pick-view="wishlist"></button>
    <div id="quickWinMaxWrap"></div>
    <span id="picksLimitGroup"></span>
  `;
}

function wishlistDeal(name, price = 9.99, cut = 50) {
  const id = String(name).toLowerCase().replace(/\s+/g, '-');
  return {
    store: 'steam',
    id,
    name,
    steam_review_percent: 80,
    wishlist_store: 'steam',
    _itadKey: `steam:${id}`,
    _price: price,
    _cut: cut,
  };
}

beforeEach(() => {
  __resetDismissedSponsorsForTest();
  setAuthStatusSnapshot([{ key: 'itad', status: 'connected' }]);
  vi.spyOn(authGate, 'isPro').mockReturnValue(false);
  state.allGames = [];
  state.itchGames = [];
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.crossStoreHiddenKeys = new Set();
  state.ownedNormNames = new Set();
  state.prefs = {
    picksTab: 'wishlistDeals',
    viewPicksLimits: { wishlist: 16 },
    quickWinMaxHours: 15,
  };
  state.activeView = 'wishlist';
  __setSponsorsForTest({
    version: 2,
    ads: {
      'ad-picks-test': {
        kind: 'sponsor',
        title: 'Rustbloom',
        tagline: 'On sale',
        cta: 'Grab it',
        url: 'https://example.com/deal',
        enabled: true,
      },
    },
    locations: { 'wish-pick': ['ad-picks-test'] },
  });
  state.wishlistGames = Array.from({ length: 20 }, (_, i) => wishlistDeal(`Game ${i + 1}`, 10 + i, 40));
  state.itadByKey = Object.fromEntries(
    state.wishlistGames.map(g => [g._itadKey, { price: g._price, cut: g._cut, shop: 'Steam' }]),
  );
  setupPicksDom();
});

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
  state.sponsoredDeals = [];
});

describe('renderPicks sponsored slot', () => {
  it('renders exactly picksLimit tiles when a picks sponsor is eligible', () => {
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid.children.length).toBe(16);
    expect(grid.querySelectorAll('.sponsored-pick-card').length).toBe(1);
    expect(grid.querySelectorAll('.pick-card:not(.sponsored-pick-card)').length).toBe(15);
    expect(document.getElementById('pickMeta').textContent).toBe('16 of 20');
    const sponsor = grid.querySelector('.sponsored-pick-card');
    expect(sponsor.querySelector('.deal-flag-cut')).toBeTruthy();
    expect(sponsor.querySelector('.text-slate-100')?.textContent).toMatch(/^\$\d+\.\d{2}$/);
  });

  it('renders picksLimit deal cards when no sponsor is eligible', () => {
    __setSponsorsForTest({ version: 2, ads: {}, locations: {} });
    renderPicks();
    const grid = document.getElementById('picksGrid');
    expect(grid.children.length).toBe(16);
    expect(grid.querySelectorAll('.sponsored-pick-card').length).toBe(0);
    expect(document.getElementById('pickMeta').textContent).toBe('16 of 20');
  });

  it('dismiss removes sponsor and refills grid incrementally', () => {
    renderPicks();
    const grid = document.getElementById('picksGrid');
    const beforeCards = [...grid.querySelectorAll('.pick-card:not(.sponsored-pick-card)')];
    expect(beforeCards.length).toBe(15);

    dismissSponsoredDeal('ad-picks-test');
    renderPicks();

    expect(grid.querySelectorAll('.sponsored-pick-card').length).toBe(0);
    expect(grid.querySelectorAll('.pick-card:not(.sponsored-pick-card)').length).toBe(16);
    expect(document.getElementById('pickMeta').textContent).toBe('16 of 20');
    const afterCards = [...grid.querySelectorAll('.pick-card:not(.sponsored-pick-card)')];
    for (let i = 0; i < 15; i++) {
      expect(afterCards[i]).toBe(beforeCards[i]);
    }
  });
});
