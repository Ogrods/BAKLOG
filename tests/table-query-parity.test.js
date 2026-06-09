/**
 * Parity guard for js/table-query.js (find_table_query_worker_parity).
 *
 * table-query.js is the DOM-free, worker-safe filter/sort module. To stay
 * importable from table-query.worker.js it re-implements primitives that also
 * live in the main-thread display modules (game-core.js, deals.js, genres.js).
 * Two copies = silent drift risk on every change (a deal/genre/sort tweak in
 * one file but not the other). This test pins the table-query copies to the
 * canonical implementations over a representative game corpus so any divergence
 * fails CI instead of shipping wrong rows.
 *
 * If a primitive legitimately needs to differ, update BOTH sides and the
 * corpus here in the same change.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { displayCurrency } from '../js/currency.js';

import * as coreCanon from '../js/game-core.js';
import * as dealsCanon from '../js/deals.js';
import * as genresCanon from '../js/genres.js';

import * as tq from '../js/table-query.js';

// --- Corpus -----------------------------------------------------------------
// Each game exercises a different branch: itad all-time low, itad 1-year low
// (the drift that prompted the deal fix), steam-discount fallback, manual
// discount with no price, FX currency mismatch, hltb override, itch
// classifications, and platform tokens mixed into genres.
const GAMES = [
  {
    store: 'steam', id: 1, name: 'Hades',
    steam_review_percent: 93, hltb_main_hours: 22, playtime_minutes: 0,
    discount_percent: 20, release_date: '2020-09-17',
    genres: ['Action', 'Indie', 'Windows', 'Unity'], classification: 'game',
  },
  {
    store: 'steam', id: 2, name: 'Old RPG',
    steam_review_percent: 60, hltb_main_hours: 80, playtime_minutes: 600,
    release_date: '2008-01-01', genres: ['RPG', 'Linux'],
  },
  {
    store: 'wishlist', id: 3, name: 'Wishlisted Gem',
    steam_review_percent: 88, hltb_main_hours: 12, release_date: '2022-05-01',
    genres: ['Adventure', 'Godot'],
  },
  {
    store: 'gog', id: 4, name: 'No Reviews',
    release_date: '2015', genres: ['Strategy', 'Soundtrack'],
  },
  {
    store: 'itch', id: 5, name: 'Some Tool',
    classification: 'tool', genres: ['Tool'],
  },
  {
    store: 'itch', id: 6, name: 'Itch Game',
    classification: 'game', genres: ['Platformer', 'HTML5'], steam_review_percent: 75,
  },
  {
    store: 'steam', id: 7, name: 'Priced EUR',
    price: '19.99', currency: 'EUR', steam_review_percent: 70,
  },
  {
    store: 'steam', id: 8, name: 'Manual Deal',
    manual: true, discount_percent: 30, steam_review_percent: 82,
  },
  {
    store: 'steam', id: 9, name: 'Has Amount',
    price_amount: 14.5, currency: 'USD', steam_review_percent: 84, hltb_main_hours: 6,
  },
  {
    store: 'wishlist', id: 10, name: 'Year Low Deal',
    steam_review_percent: 91,
  },
];

const ITAD = {
  'steam:1': { price: 12.5, cut: 20, is_historical_low: true },
  // 1-year low, NOT all-time — the exact case table-query used to mis-handle.
  'wishlist:3': { price: 9.99, cut: 50, is_historical_low_year: true },
  'wishlist:10': { price: 5.0, cut: 75, is_historical_low: false, is_historical_low_year: true },
  'steam:9': { price: 14.0, cut: 10 },
};

const PERSONAL = {
  'steam:1': { status: 'backlog' },
  'steam:2': { status: 'finished' },
  'wishlist:3': { status: 'backlog', hltb_override: 8 },
};

function setupState() {
  // Unique data version so getPersonal()'s memo never returns a stale record
  // cached by an earlier test file under the same key.
  window._dataVersion = Date.now();
  state.personal = { ...PERSONAL };
  state.itadByKey = { ...ITAD };
  state.crossStoreHiddenKeys = new Set();
  state.crossStorePlaytimeByKey = new Map();
  state.playedTitleNorms = new Set();
  state.ownedNormNames = new Set([coreCanon.normalizeNameForDedup('Wishlisted Gem')]);
  state.libraryMeta = { itad: { currency: 'USD' } };
  state.prefs = {
    dealOnSaleOnly: false,
    dealHistoricalLowOnly: false,
    dealHideOwned: false,
    dealMinDiscount: 0,
    dealMaxPrice: 100,
  };
}

// ctx the table-query primitives expect, mirroring the live state above.
function tqCtx() {
  return {
    personal: state.personal,
    itadByKey: state.itadByKey,
    ownedNormNames: state.ownedNormNames,
    displayCurrency: displayCurrency(),
    prefs: state.prefs,
    combinedPlaytime: new Map(),
    playedTitleNorms: state.playedTitleNorms,
  };
}

beforeEach(setupState);

describe('game-core primitive parity', () => {
  it('normalizeNameForDedup matches', () => {
    for (const g of GAMES) {
      expect(tq.normalizeNameForDedup(g.name)).toBe(coreCanon.normalizeNameForDedup(g.name));
    }
  });

  it('ratingValue matches', () => {
    for (const g of GAMES) {
      expect(tq.ratingValue(g)).toBe(coreCanon.ratingValue(g));
    }
  });

  it('parseReleaseForSort matches', () => {
    for (const g of GAMES) {
      expect(tq.parseReleaseForSort(g.release_date)).toBe(coreCanon.parseReleaseForSort(g.release_date));
    }
  });

  it('hltbMain matches (incl. personal hltb_override)', () => {
    for (const g of GAMES) {
      expect(tq.hltbMain(state.personal, g)).toBe(coreCanon.hltbMain(g));
    }
  });

  it('priorityScore matches', () => {
    const ctx = tqCtx();
    for (const g of GAMES) {
      expect(tq.priorityScore(ctx, g)).toBe(coreCanon.priorityScore(g));
    }
  });

  it('itchIsGame matches', () => {
    for (const g of GAMES) {
      expect(tq.itchIsGame(g)).toBe(coreCanon.itchIsGame(g));
    }
  });

  it('isCleanupCandidate matches', () => {
    const ctx = tqCtx();
    for (const g of GAMES) {
      expect(tq.isCleanupCandidate(ctx, g)).toBe(coreCanon.isCleanupCandidate(g));
    }
  });
});

describe('deals primitive parity', () => {
  it('comparableStorePrice matches deals.gameComparablePrice', () => {
    const ccy = displayCurrency();
    for (const g of GAMES) {
      expect(tq.comparableStorePrice(g, ccy)).toBe(dealsCanon.gameComparablePrice(g, ccy));
    }
  });

  it('getDealInfo matches on the fields filtering/sorting reads', () => {
    const ccy = displayCurrency();
    for (const g of GAMES) {
      const a = tq.getDealInfo(state.itadByKey, g, ccy);
      const b = dealsCanon.getDealInfo(g);
      if (a === null || b === null) {
        expect(a).toEqual(b);
        continue;
      }
      expect({ price: a.price, cut: a.cut, isHistoricalLow: a.isHistoricalLow })
        .toEqual({ price: b.price, cut: b.cut, isHistoricalLow: b.isHistoricalLow });
    }
  });

  it('historical-low parity holds for a 1-year-low-only deal (regression)', () => {
    const yearLow = GAMES.find(g => g.id === 3);
    const a = tq.getDealInfo(state.itadByKey, yearLow, displayCurrency());
    const b = dealsCanon.getDealInfo(yearLow);
    expect(a.isHistoricalLow).toBe(true);
    expect(b.isHistoricalLow).toBe(true);
  });

  it('effectiveDiscountPercent matches', () => {
    const ctx = tqCtx();
    for (const g of GAMES) {
      expect(tq.effectiveDiscountPercent(ctx, g)).toBe(dealsCanon.effectiveDiscountPercent(g));
    }
  });

  it('effectiveSortPrice matches', () => {
    const ctx = tqCtx();
    for (const g of GAMES) {
      expect(tq.effectiveSortPrice(ctx, g)).toBe(dealsCanon.effectiveSortPrice(g));
    }
  });

  it('isOwnedByTitle matches', () => {
    for (const g of GAMES) {
      expect(tq.isOwnedByTitle(state.ownedNormNames, g.name)).toBe(dealsCanon.isOwnedByTitle(g.name));
    }
  });

  it('passesDealFilters matches across pref configurations', () => {
    const configs = [
      { dealOnSaleOnly: true },
      { dealHistoricalLowOnly: true },
      { dealHideOwned: true },
      { dealMinDiscount: 40 },
      { dealMaxPrice: 10 },
      { dealHistoricalLowOnly: true, dealMaxPrice: 8 },
    ];
    for (const cfg of configs) {
      state.prefs = {
        dealOnSaleOnly: false,
        dealHistoricalLowOnly: false,
        dealHideOwned: false,
        dealMinDiscount: 0,
        dealMaxPrice: 100,
        ...cfg,
      };
      const ctx = tqCtx();
      for (const g of GAMES) {
        expect(tq.passesDealFilters(ctx, g)).toBe(dealsCanon.passesDealFilters(g));
      }
    }
  });
});

describe('genre canonicalization parity', () => {
  it('genres.js strips the extended platform/non-genre tokens', () => {
    // These tokens used to leak through table-query.js own NON_GENRE_TOKENS copy.
    expect(genresCanon.gameGenresCanonical({ genres: ['Action', 'Unity', 'HTML5'] })).toEqual(['Action']);
    expect(genresCanon.gameGenresCanonical({ genres: ['Strategy', 'Soundtrack', 'Godot'] })).toEqual(['Strategy']);
  });

  it('queryGames genre filter agrees with genres.gameGenresCanonical', () => {
    const ctx = {
      view: 'library',
      prefs: { genreFilters: ['Action'], genreFilterMode: 'OR', coopFilterMode: 'off' },
      params: { q: '', status: '', unplayed: false, earlyAccess: false, minRating: 0, maxHours: 200 },
      personal: {},
      hiddenKeys: new Set(),
      ownedNormNames: new Set(),
      itadByKey: {},
      cleanupModeActive: false,
      sortKey: 'name',
      sortDir: 1,
    };
    const out = tq.queryGames({ source: GAMES, ctx });
    const expected = GAMES.filter(g => genresCanon.gameGenresCanonical(g).includes('Action'));
    expect(out.map(g => g.id).sort()).toEqual(expected.map(g => g.id).sort());
  });
});
