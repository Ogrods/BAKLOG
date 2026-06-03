/**
 * Tests for js/library-watch.js — arm, dismiss, and catalog match.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { state } from '../js/state.js';
import { profileScopedStorageKey } from '../js/profiles.js';
import {
  armLibraryWatch,
  dismissLibraryWatch,
  checkLibraryWatches,
  hasArmedWatches,
  listArmedWatches,
  PICO_PARK_WATCH,
} from '../js/library-watch.js';

const WATCH_LS_KEY = profileScopedStorageKey('baklog-library-watch');

const TEST_WATCH = {
  id: 'test-game',
  name: 'Test Game',
  store: 'steam',
  appids: [42],
};

function readWatches() {
  return JSON.parse(localStorage.getItem(WATCH_LS_KEY) || '{}').watches || [];
}

beforeEach(() => {
  localStorage.clear();
  state.libraryMeta.steam = { games: [] };
  document.body.innerHTML =
    '<div id="libraryWatchBanner" class="migration-banner library-watch-banner hidden"></div>';
  vi.stubGlobal('Notification', undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('armLibraryWatch', () => {
  it('adds a watch and dedupes by id', () => {
    armLibraryWatch(TEST_WATCH);
    armLibraryWatch({ ...TEST_WATCH, name: 'Duplicate' });
    const watches = readWatches();
    expect(watches).toHaveLength(1);
    expect(watches[0].id).toBe('test-game');
    expect(watches[0].armedAt).toBeTruthy();
    expect(hasArmedWatches()).toBe(true);
    expect(listArmedWatches()[0].name).toBe('Test Game');
  });
});

describe('dismissLibraryWatch', () => {
  it('removes a watch by id', () => {
    armLibraryWatch(TEST_WATCH);
    dismissLibraryWatch('test-game');
    expect(readWatches()).toHaveLength(0);
    expect(hasArmedWatches()).toBe(false);
  });
});

describe('checkLibraryWatches', () => {
  it('fires when a watched appid appears in the Steam catalog', () => {
    armLibraryWatch(TEST_WATCH);
    state.libraryMeta.steam = {
      games: [{ appid: 42, name: 'Test Game Found' }],
    };
    const fired = checkLibraryWatches();
    expect(fired).toBe(true);
    expect(readWatches()).toHaveLength(0);
    const banner = document.getElementById('libraryWatchBanner');
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.textContent).toContain('Test Game Found');
    expect(banner.textContent).toContain('Steam library');
  });

  it('returns false when catalog has no match', () => {
    armLibraryWatch(TEST_WATCH);
    state.libraryMeta.steam = { games: [{ appid: 99, name: 'Other' }] };
    expect(checkLibraryWatches()).toBe(false);
    expect(readWatches()).toHaveLength(1);
  });

  it('matches any appid in PICO_PARK_WATCH', () => {
    armLibraryWatch(PICO_PARK_WATCH);
    state.libraryMeta.steam = {
      games: [{ appid: 453090, name: 'Pico Park Classic' }],
    };
    expect(checkLibraryWatches()).toBe(true);
    expect(readWatches()).toHaveLength(0);
  });
});
