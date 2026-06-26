/**
 * Tests for js/deals.js — ITAD/Steam deal resolution, filters, scoring, badges.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { AFFILIATE_CREDENTIALS } from '../js/affiliate.js';
import {
  parsePriceLike,
  getDealInfo,
  cutBucketClass,
  dealScore,
  passesDealFilters,
  effectiveDiscountPercent,
  effectiveSortPrice,
  isStealDeal,
  dealShopShort,
  shopSlug,
  dealLowBadgeHtml,
  priceLowStarHtml,
  dealHeroCardHtml,
  applyItadPriceSnapshot,
  slimItadSnapshot,
  buildOwnedNormNames,
  isOwnedByTitle,
} from '../js/deals.js';

const baseGame = {
  store: 'wishlist',
  id: 'wl-1',
  name: 'Deal Game',
  steam_review_percent: 85,
};

function resetState() {
  state.itadByKey = {};
  state.itadPriceDroppedKeys = new Set();
  state.ownedNormNames = new Set();
  state.allGames = [];
  state.crossStoreHiddenKeys = new Set();
  state.prefs = {
    dealOnSaleOnly: false,
    dealHistoricalLowOnly: false,
    dealHideOwned: false,
    dealMinDiscount: 0,
    dealMaxPrice: 100,
  };
}

beforeEach(() => {
  resetState();
});

describe('parsePriceLike', () => {
  it('passes through numbers', () => {
    expect(parsePriceLike(12.5)).toBe(12.5);
  });
  it('parses currency strings', () => {
    expect(parsePriceLike('$12.34')).toBe(12.34);
  });
  it('returns null for empty or unparseable', () => {
    expect(parsePriceLike(null)).toBeNull();
    expect(parsePriceLike('nope')).toBeNull();
  });
});

describe('getDealInfo', () => {
  it('prefers ITAD with all-time low kind', () => {
    state.itadByKey['wishlist:wl-1'] = {
      price: 9.99,
      regular: 39.99,
      cut: 75,
      is_historical_low: true,
      is_historical_low_year: false,
      shop: 'Steam',
      url: 'https://store.steampowered.com/app/1',
    };
    const d = getDealInfo(baseGame);
    expect(d?.source).toBe('itad');
    expect(d?.lowKind).toBe('all');
    expect(d?.isHistoricalLow).toBe(true);
  });

  it('passes ITAD historical low amounts through', () => {
    state.itadByKey['wishlist:wl-1'] = {
      price: 9.99,
      regular: 39.99,
      cut: 75,
      is_historical_low: true,
      history_low_all: 7.49,
      history_low_year: 8.99,
      shop: 'Steam',
    };
    const d = getDealInfo(baseGame);
    expect(d?.historyLowAll).toBe(7.49);
    expect(d?.historyLowYear).toBe(8.99);
  });

  it('uses year low when only is_historical_low_year', () => {
    state.itadByKey['wishlist:wl-1'] = {
      price: 14,
      regular: 20,
      cut: 30,
      is_historical_low: false,
      is_historical_low_year: true,
      shop: 'GOG',
    };
    expect(getDealInfo(baseGame)?.lowKind).toBe('year');
  });

  it('falls back to Steam price and discount on wishlist row', () => {
    const g = { ...baseGame, price: '$19.99', price_initial: '$39.99', discount_percent: 50 };
    const d = getDealInfo(g);
    expect(d?.source).toBe('steam');
    expect(d?.cut).toBe(50);
    expect(d?.shop).toBe('Steam');
  });

  it('returns null when no pricing', () => {
    expect(getDealInfo({ ...baseGame, price: null, discount_percent: 0 })).toBeNull();
  });

  it('tags itch.io fallback store_url when affiliate is live', () => {
    const prev = AFFILIATE_CREDENTIALS.itch;
    AFFILIATE_CREDENTIALS.itch = 'eob7ZQcpthHDp';
    try {
      const g = {
        ...baseGame,
        price: '$4.99',
        discount_percent: 20,
        store_url: 'https://dev.itch.io/sale-game',
      };
      const d = getDealInfo(g);
      expect(d?.url).toContain('ac=eob7ZQcpthHDp');
    } finally {
      AFFILIATE_CREDENTIALS.itch = prev;
    }
  });
});

describe('cutBucketClass', () => {
  it('maps cut depth to CSS classes', () => {
    expect(cutBucketClass(0)).toBe('');
    expect(cutBucketClass(25)).toBe('');
    expect(cutBucketClass(50)).toBe('deal-cut-big');
    expect(cutBucketClass(75)).toBe('deal-cut-huge');
  });
});

describe('dealScore and isOwnedByTitle', () => {
  it('ranks historical low + high rating above plain cut', () => {
    state.itadByKey['wishlist:wl-1'] = {
      price: 10,
      cut: 40,
      is_historical_low: true,
      shop: 'Steam',
    };
    const plain = { ...baseGame, id: 'wl-2', name: 'Plain', steam_review_percent: 50 };
    state.itadByKey['wishlist:wl-2'] = { price: 10, cut: 60, shop: 'Steam' };
    expect(dealScore(baseGame)).toBeGreaterThan(dealScore(plain));
  });

  it('penalizes titles already in library', () => {
    state.itadByKey['wishlist:wl-1'] = { price: 10, cut: 80, shop: 'Steam' };
    state.allGames = [{ store: 'steam', id: 1, appid: 1, name: 'Deal Game' }];
    buildOwnedNormNames();
    expect(isOwnedByTitle('Deal Game')).toBe(true);
    expect(dealScore(baseGame)).toBeLessThan(0);
  });
});

describe('passesDealFilters', () => {
  beforeEach(() => {
    state.itadByKey['wishlist:wl-1'] = { price: 15, cut: 50, shop: 'Steam' };
  });

  it('dealOnSaleOnly rejects zero-cut rows', () => {
    state.prefs.dealOnSaleOnly = true;
    state.itadByKey['wishlist:wl-1'] = { price: 15, cut: 0, shop: 'Steam' };
    expect(passesDealFilters(baseGame)).toBe(false);
  });

  it('dealHistoricalLowOnly requires historical low', () => {
    state.prefs.dealHistoricalLowOnly = true;
    expect(passesDealFilters(baseGame)).toBe(false);
    state.itadByKey['wishlist:wl-1'].is_historical_low = true;
    expect(passesDealFilters(baseGame)).toBe(true);
  });

  it('dealMinDiscount enforces floor', () => {
    state.prefs.dealMinDiscount = 60;
    expect(passesDealFilters(baseGame)).toBe(false);
    state.itadByKey['wishlist:wl-1'].cut = 65;
    expect(passesDealFilters(baseGame)).toBe(true);
  });

  it('dealMaxPrice blocks expensive deals', () => {
    state.prefs.dealMaxPrice = 10;
    expect(passesDealFilters(baseGame)).toBe(false);
  });

  it('manual wishlist with discount but no price passes max-price when on sale', () => {
    state.prefs.dealOnSaleOnly = true;
    state.prefs.dealMaxPrice = 5;
    const manual = {
      ...baseGame,
      manual: true,
      price: null,
      discount_percent: 25,
    };
    delete state.itadByKey['wishlist:wl-1'];
    expect(passesDealFilters(manual)).toBe(true);
  });

  it('dealHideOwned skips library matches', () => {
    state.prefs.dealHideOwned = true;
    state.allGames = [{ store: 'steam', id: 1, appid: 1, name: 'Deal Game' }];
    buildOwnedNormNames();
    expect(passesDealFilters(baseGame)).toBe(false);
  });
});

describe('effectiveDiscountPercent, effectiveSortPrice, isStealDeal', () => {
  it('reads cut from deal info', () => {
    state.itadByKey['wishlist:wl-1'] = { price: 10, cut: 55, shop: 'Steam' };
    expect(effectiveDiscountPercent(baseGame)).toBe(55);
    expect(effectiveSortPrice(baseGame)).toBe(10);
  });

  it('isStealDeal requires rating, cut or historical low', () => {
    state.itadByKey['wishlist:wl-1'] = { price: 10, cut: 55, shop: 'Steam' };
    expect(isStealDeal(baseGame)).toBe(true);
    const weak = { ...baseGame, steam_review_percent: 50 };
    state.itadByKey['wishlist:wl-1'] = { price: 10, cut: 30, shop: 'Steam' };
    expect(isStealDeal(weak)).toBe(false);
  });
});

describe('dealShopShort and shopSlug', () => {
  it('maps known shops and truncates long names', () => {
    expect(dealShopShort('Steam')).toBe('Steam');
    expect(dealShopShort('Green Man Gaming')).toBe('GMG');
    expect(dealShopShort('Some Very Long Store Name Here')).toMatch(/…$/);
    expect(shopSlug('Epic Games Store')).toBe('epic');
  });
});

describe('dealLowBadgeHtml and priceLowStarHtml', () => {
  it('includes historical low amount in tooltip', () => {
    const html = dealLowBadgeHtml({ lowKind: 'all', historyLowAll: 4.99 });
    expect(html).toContain('4.99');
    const star = priceLowStarHtml({ lowKind: 'year', historyLowYear: 12.5 });
    expect(star).toContain('12.5');
  });

  it('renders all-time, year, generic low, and empty', () => {
    expect(dealLowBadgeHtml({ lowKind: 'all' })).toContain('all-time');
    expect(dealLowBadgeHtml({ lowKind: 'year' })).toContain('1yr');
    expect(dealLowBadgeHtml({ isHistoricalLow: true })).toContain('low');
    expect(dealLowBadgeHtml(null)).toBe('');
    expect(priceLowStarHtml({ lowKind: 'all' })).toContain('★');
    expect(priceLowStarHtml(null)).toBe('');
  });
});

describe('dealHeroCardHtml', () => {
  it('omits HLTB stat when missing or zero', () => {
    state.itadByKey['wishlist:wl-1'] = { price: 8.99, regular: 14.99, cut: 40, shop: 'Steam' };
    const noHltb = dealHeroCardHtml({ ...baseGame, hltb_main_hours: null });
    expect(noHltb).not.toContain('deal-hero-stat-dot-hltb');
    const zeroHltb = dealHeroCardHtml({ ...baseGame, hltb_main_hours: 0 });
    expect(zeroHltb).not.toContain('deal-hero-stat-dot-hltb');
  });

  it('shows HLTB stat when hours are positive', () => {
    state.itadByKey['wishlist:wl-1'] = { price: 8.99, regular: 14.99, cut: 40, shop: 'Steam' };
    const html = dealHeroCardHtml({ ...baseGame, hltb_main_hours: 12 });
    expect(html).toContain('deal-hero-stat-dot-hltb');
    expect(html).toContain('12h');
  });
});

describe('applyItadPriceSnapshot and slimItadSnapshot', () => {
  it('marks keys when price drops', () => {
    applyItadPriceSnapshot({ a: { price: 20, cut: 10 } }, { a: { price: 15, cut: 20 } });
    expect(state.itadPriceDroppedKeys.has('a')).toBe(true);
    expect(state.itadPriceDroppedKeys.has('b')).toBe(false);
  });

  it('slimItadSnapshot keeps price and cut only', () => {
    expect(slimItadSnapshot({ x: { price: 9, cut: 40, shop: 'Steam' } })).toEqual({
      x: { price: 9, cut: 40 },
    });
  });
});
