import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import * as authGate from '../js/auth-gate.js';
import {
  fetcherRunner,
  renderDashboardFetcherHealth,
} from '../js/fetcher-health.js';
import { lastRunFailedByKey } from '../js/fetcher-health-shared.js';
import { state } from '../js/state.js';

describe('Retry failed batch button', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div>';
    state.prefs.fetcherHealthShowConnected = false;
    state.prefs.fetcherHealthShowStaleMissing = false;
    lastRunFailedByKey.clear();
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

  afterEach(() => {
    lastRunFailedByKey.clear();
  });

  it('omits Retry failed when no fetchers failed', async () => {
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    expect(document.querySelector('.fh-run-failed')).toBeNull();
  });

  it('renders Retry failed when a fetcher is in failed state', async () => {
    lastRunFailedByKey.set('steam', Date.now());
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    const btn = document.querySelector('.fh-run-failed');
    expect(btn).toBeTruthy();
    expect(btn.textContent).toMatch(/Retry failed \(1\)/);
  });

  it('shows Retry failed on free tier but hides Pro Run stale', async () => {
    lastRunFailedByKey.set('steam', Date.now());
    vi.spyOn(authGate, 'isPro').mockReturnValue(false);
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();
    expect(document.querySelector('.fh-run-failed')).toBeTruthy();
    expect(document.querySelector('.fh-run-stale')).toBeNull();
  });
});
