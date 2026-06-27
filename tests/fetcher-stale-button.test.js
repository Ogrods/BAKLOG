import { describe, expect, it, vi, beforeEach } from 'vitest';
import * as authGate from '../js/auth-gate.js';
import { fetcherRunner, renderDashboardFetcherHealth } from '../js/fetcher-health.js';
import { state } from '../js/state.js';

const STALE_ISO = new Date(Date.now() - 31 * 86400000).toISOString();

function stubFetcherApi(keys = ['steam']) {
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    const u = String(url);
    if (u.includes('/api/runs')) {
      return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
    }
    if (u.includes('/api/fetchers')) {
      return {
        ok: true,
        json: async () => ({
          fetchers: keys.map((key) => ({
            key,
            label: key,
            metaKey: key,
            group: 'library',
            color: '#000',
            cmd: 'fetch.py',
            available: true,
          })),
        }),
      };
    }
    if (u.includes('manifest.json')) {
      return { ok: true, json: async () => ({ fetchers: [] }) };
    }
    if (u.includes('/api/config')) {
      return { ok: true, json: async () => ({ ok: true }) };
    }
    return { ok: false };
  }));
}

describe('Pro run stale button', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div>';
    state.prefs.fetcherHealthShowConnected = false;
    state.prefs.fetcherHealthShowStaleMissing = false;
    state.libraryMeta = { steam: { game_count: 1, fetched_at: STALE_ISO } };
    stubFetcherApi(['steam']);
    fetcherRunner.invalidateApiProbe();
  });

  it('omits Run stale for free tier', async () => {
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    expect(document.querySelector('.fh-run-stale')).toBeNull();
  });

  it('renders Run stale for Pro when stale fetchers exist', async () => {
    vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    const btn = document.querySelector('.fh-run-stale');
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Run stale \(1\)/);
    expect(btn.disabled).toBe(false);
  });

  it('disables Run stale for Pro when all fetchers are fresh', async () => {
    state.libraryMeta.steam.fetched_at = new Date().toISOString();
    vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    const btn = document.querySelector('.fh-run-stale');
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Run stale \(0\)/);
    expect(btn.disabled).toBe(true);
  });

  it('disables Run stale when API probe fails (readonly)', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    const btn = document.querySelector('.fh-run-stale');
    expect(btn).toBeTruthy();
    expect(btn.disabled).toBe(true);
    expect(document.querySelector('.fh-readonly-banner')).toBeTruthy();
  });
});
