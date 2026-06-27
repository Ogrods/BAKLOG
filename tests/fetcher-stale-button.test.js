import { describe, expect, it, vi, beforeEach } from 'vitest';
import * as authGate from '../js/auth-gate.js';
import { fetcherRunner, renderDashboardFetcherHealth } from '../js/fetcher-health.js';
import { state } from '../js/state.js';

describe('Pro run stale button', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div>';
    state.prefs.fetcherHealthShowConnected = false;
    state.prefs.fetcherHealthShowStaleMissing = false;
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'steam',
              label: 'Steam',
              metaKey: 'steam',
              group: 'library',
              color: '#000',
              cmd: 'fetch_games.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
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
    expect(btn.textContent).toMatch(/Run stale/);
  });
});
