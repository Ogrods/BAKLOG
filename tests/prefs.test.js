/**
 * Tests for js/prefs.js — persisted prefs load/migrate and per-view sort.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state, PREFS_KEY } from '../js/state.js';
import { prefsStorageKey } from '../js/profiles.js';
import {
  loadPrefs,
  loadSessionPrefs,
  getSavedSortForView,
  persistCurrentSort,
  VIEW_SORT_DEFAULTS,
} from '../js/prefs.js';

beforeEach(() => {
  localStorage.clear();
  state.prefs = {};
  state.activeView = 'library';
  state.sortKey = 'name';
  state.sortDir = 1;
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
