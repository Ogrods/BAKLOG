/**
 * Tests for js/prefs.js — persisted prefs load/migrate and per-view sort.
 */

import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { state, PREFS_KEY } from '../js/state.js';
import { prefsStorageKey } from '../js/profiles.js';
import {
  loadPrefs,
  loadSessionPrefs,
  getSavedSortForView,
  persistCurrentSort,
  savePrefs,
  VIEW_SORT_DEFAULTS,
} from '../js/prefs.js';

beforeEach(() => {
  localStorage.clear();
  state.prefs = {};
  state.activeView = 'library';
  state.sortKey = 'name';
  state.sortDir = 1;
});

describe('savePrefs quota handling', () => {
  let setItemSpy;
  let warn;

  beforeEach(() => {
    setItemSpy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      const err = new Error('quota');
      err.name = 'QuotaExceededError';
      throw err;
    });
    warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    setItemSpy.mockRestore();
    warn.mockRestore();
  });

  it('does not throw when localStorage write exceeds quota', () => {
    state.prefs = { picksLimit: 8 };
    expect(() => savePrefs()).not.toThrow();
    expect(warn).toHaveBeenCalled();
  });
});

describe('loadPrefs', () => {
  it('returns defaults on malformed JSON', () => {
    localStorage.setItem(prefsStorageKey(), '{not json');
    const p = loadPrefs();
    expect(p.picksTab).toBe('topRated');
    expect(p.coopFilterMode).toBe('off');
  });

  it('merges stored values with defaults', () => {
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ dealMinDiscount: 25, picksLimit: 8 }));
    const p = loadPrefs();
    expect(p.dealMinDiscount).toBe(25);
    expect(p.picksLimit).toBe(8);
    expect(p.dealOnSaleOnly).toBe(false);
  });

  it('strips legacy persisted keys', () => {
    localStorage.setItem(
      prefsStorageKey(),
      JSON.stringify({
        crossStoreDedup: false,
        itchHideNonGames: false,
        tagFilters: ['x'],
        tagFilterMode: 'AND',
        coopFilterMode: 'off',
      }),
    );
    const p = loadPrefs();
    expect(p.crossStoreDedup).toBeUndefined();
    expect(p.itchHideNonGames).toBeUndefined();
    expect(p.tagFilters).toBeUndefined();
    expect(p.tagFilterMode).toBeUndefined();
  });

  it('coerces legacy coopAny when stored coopFilterMode is invalid', () => {
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ coopFilterMode: 'legacy', coopAny: true }));
    const p = loadPrefs();
    expect(p.coopFilterMode).toBe('any');
    expect(p.coopAny).toBeUndefined();
  });

  it('invalid coopFilterMode falls back via coopAny or off', () => {
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ coopFilterMode: 'bogus' }));
    expect(loadPrefs().coopFilterMode).toBe('off');
  });

  it('defaults autoFetchOnConnect true and autoFetchStale24h true', () => {
    const p = loadPrefs();
    expect(p.autoFetchOnConnect).toBe(true);
    expect(p.autoFetchStale24h).toBe(true);
  });

  it('clamps itadAutoRefreshIntervalMin to 15-60 and snaps to step 5', () => {
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ itadAutoRefreshIntervalMin: 10 }));
    expect(loadPrefs().itadAutoRefreshIntervalMin).toBe(15);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ itadAutoRefreshIntervalMin: 72 }));
    expect(loadPrefs().itadAutoRefreshIntervalMin).toBe(60);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ itadAutoRefreshIntervalMin: 23 }));
    expect(loadPrefs().itadAutoRefreshIntervalMin).toBe(25);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ itadAutoRefreshIntervalMin: 'nope' }));
    expect(loadPrefs().itadAutoRefreshIntervalMin).toBe(15);
  });

  it('flips legacy rowHeroBackdrop=false on once for users predating the default', () => {
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ rowHeroBackdrop: false }));
    const p = loadPrefs();
    expect(p.rowHeroBackdrop).toBe(true);
    expect(p.rowHeroBackdropDefaulted).toBe(true);
  });

  it('respects a deliberate rowHeroBackdrop=false once the marker is set', () => {
    localStorage.setItem(
      prefsStorageKey(),
      JSON.stringify({ rowHeroBackdrop: false, rowHeroBackdropDefaulted: true }),
    );
    expect(loadPrefs().rowHeroBackdrop).toBe(false);
  });

  it('clamps claimsAutoRefreshIntervalMin to 30-360 and snaps to step 30', () => {
    expect(loadPrefs().claimsAutoRefreshIntervalMin).toBe(120);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ claimsAutoRefreshIntervalMin: 10 }));
    expect(loadPrefs().claimsAutoRefreshIntervalMin).toBe(30);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ claimsAutoRefreshIntervalMin: 500 }));
    expect(loadPrefs().claimsAutoRefreshIntervalMin).toBe(360);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ claimsAutoRefreshIntervalMin: 100 }));
    expect(loadPrefs().claimsAutoRefreshIntervalMin).toBe(90);
    localStorage.setItem(prefsStorageKey(), JSON.stringify({ claimsAutoRefreshIntervalMin: 'nope' }));
    expect(loadPrefs().claimsAutoRefreshIntervalMin).toBe(120);
  });
});

describe('getSavedSortForView', () => {
  it('returns saved sort when valid', () => {
    state.prefs.viewSorts = { library: { key: 'playtime', dir: -1 } };
    expect(getSavedSortForView('library')).toEqual({ key: 'playtime', dir: -1 });
  });

  it('returns view default when missing or invalid dir', () => {
    expect(getSavedSortForView('library')).toEqual({ ...VIEW_SORT_DEFAULTS.library });
    state.prefs.viewSorts = { library: { key: 'name', dir: 2 } };
    expect(getSavedSortForView('library')).toEqual({ ...VIEW_SORT_DEFAULTS.library });
  });

  it('returns null for unknown view', () => {
    expect(getSavedSortForView('dashboard')).toBeNull();
  });
});

describe('persistCurrentSort', () => {
  it('writes active view sort into prefs and localStorage', () => {
    state.activeView = 'wishlist';
    state.sortKey = 'deal_price';
    state.sortDir = -1;
    persistCurrentSort();
    expect(state.prefs.viewSorts.wishlist).toEqual({ key: 'deal_price', dir: -1 });
    const stored = JSON.parse(localStorage.getItem(prefsStorageKey()));
    expect(stored.viewSorts.wishlist.key).toBe('deal_price');
  });

  it('no-ops for views without sort defaults', () => {
    state.activeView = 'dashboard';
    state.prefs.viewSorts = {};
    persistCurrentSort();
    expect(state.prefs.viewSorts).toEqual({});
  });
});

describe('loadSessionPrefs', () => {
  it('returns fresh non-persisted session defaults', () => {
    const s = loadSessionPrefs();
    expect(s.crossStoreDedup).toBe(true);
    expect(s.itchHideNonGames).toBe(true);
    expect(s.search).toBe('');
    expect(s.maxHours).toBe(200);
  });
});
