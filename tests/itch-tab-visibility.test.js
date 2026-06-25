/**
 * itch.io top-nav tab visibility — quarantined until API key / library data.
 */

import { describe, expect, it, beforeEach, vi, afterEach } from 'vitest';

vi.mock('../js/chart-loader.js', () => ({
  ensureChartJs: vi.fn(() => Promise.resolve()),
}));

import { state } from '../js/state.js';
import { refreshConnections, isItchTabAvailable } from '../js/connections.js';
import { applyItchTabVisibility } from '../js/filters-ui.js';
import { loadActiveView, saveActiveView } from '../js/prefs.js';

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

  it('stays available when disconnected but a cached itch catalog exists', async () => {
    mockAuthStatus([
      { key: 'itch', status: 'disconnected' },
      { key: 'itch_local', status: 'disconnected' },
    ]);
    state.itchGames = [{ store: 'itch', id: 'a', name: 'Demo Game' }];
    await refreshConnections();
    expect(isItchTabAvailable()).toBe(true);
  });
});

describe('applyItchTabVisibility', () => {
  beforeEach(() => {
    state.itchGames = [];
    state.dashboardDataReady = false;
    state.activeView = 'library';
    state.prefs = state.prefs || {};
    saveActiveView('library');
    document.body.innerHTML = `
      <button type="button" class="view-tab" data-view="itch">itch.io</button>
      <button type="button" class="view-tab" data-view="dashboard">Dashboard</button>
      <div id="bulkBar" class="hidden"><span id="bulkCount"></span></div>
      <div id="viewLoadingOverlay"></div>
      <div id="viewLoadingLabel"></div>`;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    state.dashboardDataReady = false;
  });

  it('keeps the itch tab visible but marks it for the dashboard jump when itch is not set up', async () => {
    mockAuthStatus([]);
    await refreshConnections();
    applyItchTabVisibility();
    const tab = document.querySelector('.view-tab[data-view="itch"]');
    expect(tab.classList.contains('hidden')).toBe(false);
    expect(tab.classList.contains('itch-tab-jump')).toBe(true);
  });

  it('clears the jump marker after itch is connected', async () => {
    mockAuthStatus([{ key: 'itch', status: 'connected' }]);
    await refreshConnections();
    applyItchTabVisibility();
    const tab = document.querySelector('.view-tab[data-view="itch"]');
    expect(tab.classList.contains('hidden')).toBe(false);
    expect(tab.classList.contains('itch-tab-jump')).toBe(false);
  });

  it('does not redirect away from itch during boot before data is known', async () => {
    state.activeView = 'itch';
    saveActiveView('itch');
    state.dashboardDataReady = false;
    mockAuthStatus([{ key: 'itch', status: 'disconnected' }]);
    await refreshConnections();
    applyItchTabVisibility();
    expect(state.activeView).toBe('itch');
    expect(loadActiveView()).toBe('itch');
  });

  it('redirects from itch to dashboard when disconnected and library is empty', async () => {
    state.activeView = 'itch';
    saveActiveView('itch');
    state.dashboardDataReady = true;
    mockAuthStatus([{ key: 'itch', status: 'disconnected' }]);
    await refreshConnections();
    applyItchTabVisibility();
    expect(loadActiveView()).toBe('dashboard');
  });

  it('keeps itch view when disconnected but cached library exists', async () => {
    state.activeView = 'itch';
    saveActiveView('itch');
    state.dashboardDataReady = true;
    state.itchGames = [{ store: 'itch', id: 'a', name: 'Demo Game' }];
    mockAuthStatus([
      { key: 'itch', status: 'disconnected' },
      { key: 'itch_local', status: 'disconnected' },
    ]);
    await refreshConnections();
    applyItchTabVisibility();
    expect(loadActiveView()).toBe('itch');
  });
});
