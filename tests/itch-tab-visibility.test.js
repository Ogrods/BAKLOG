/**
 * itch.io top-nav tab visibility — quarantined until API key / library data.
 */

import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';
import { state } from '../js/state.js';
import { refreshConnections, isItchTabAvailable } from '../js/connections.js';
import { applyItchTabVisibility } from '../js/filters-ui.js';

function mockAuthStatus(providers) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    if (u.includes('/api/auth/status')) {
      return Promise.resolve({
        ok: true,
        json: async () => ({ server_platform: 'win32', providers }),
      });
    }
    return Promise.reject(new Error(`unexpected fetch: ${u}`));
  });
}

describe('isItchTabAvailable', () => {
  beforeEach(() => {
    state.itchGames = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('is false when itch is disconnected and library is empty', async () => {
    mockAuthStatus([{ key: 'itch', status: 'disconnected' }]);
    await refreshConnections();
    expect(isItchTabAvailable()).toBe(false);
  });

  it('is true when itch is connected with zero games', async () => {
    mockAuthStatus([{ key: 'itch', status: 'connected' }]);
    await refreshConnections();
    expect(state.itchGames.length).toBe(0);
    expect(isItchTabAvailable()).toBe(true);
  });

  it('is true when itch is unverified with zero games', async () => {
    mockAuthStatus([{ key: 'itch', status: 'unverified' }]);
    await refreshConnections();
    expect(isItchTabAvailable()).toBe(true);
  });

  it('is true when disconnected but itch library has rows', async () => {
    mockAuthStatus([{ key: 'itch', status: 'disconnected' }]);
    state.itchGames = [{ store: 'itch', id: 'a', name: 'Demo Game' }];
    await refreshConnections();
    expect(isItchTabAvailable()).toBe(true);
  });
});

describe('applyItchTabVisibility', () => {
  beforeEach(() => {
    state.itchGames = [];
    state.activeView = 'library';
    state.prefs = state.prefs || {};
    state.prefs.activeView = 'library';
    document.body.innerHTML =
      '<button type="button" class="view-tab" data-view="itch">itch.io</button>';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('hides the itch tab when itch is not set up', async () => {
    mockAuthStatus([]);
    await refreshConnections();
    applyItchTabVisibility();
    const tab = document.querySelector('.view-tab[data-view="itch"]');
    expect(tab.classList.contains('hidden')).toBe(true);
  });

  it('shows the itch tab after itch is connected', async () => {
    mockAuthStatus([{ key: 'itch', status: 'connected' }]);
    await refreshConnections();
    const tab = document.querySelector('.view-tab[data-view="itch"]');
    expect(tab.classList.contains('hidden')).toBe(false);
  });
});
