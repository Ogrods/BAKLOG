/** runAllStale batch queue: order, eligibility, cancel, and API guards. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as fh from '../js/fetcher-health.js';
import { state } from '../js/state.js';

const {
  fetcherRunner,
  staleSweepRank,
  resolveStaleSweepKeys,
  fetcherFreshness,
} = fh;

const STALE_ISO = new Date(Date.now() - 31 * 86400000).toISOString();

describe('staleSweepRank', () => {
  it('orders known library stores before unknown keys', () => {
    expect(staleSweepRank('epic')).toBeLessThan(staleSweepRank('psn'));
    expect(staleSweepRank('psn')).toBeLessThan(staleSweepRank('steam'));
    expect(staleSweepRank('steam')).toBeLessThan(staleSweepRank('unknown'));
  });
});

describe('resolveStaleSweepKeys', () => {
  const sources = [
    { key: 'steam', metaKey: 'steam' },
    { key: 'epic', metaKey: 'epic' },
    { key: 'psn', metaKey: 'psn' },
  ];

  beforeEach(() => {
    state.libraryMeta = {
      steam: { fetched_at: STALE_ISO },
      epic: { fetched_at: STALE_ISO },
      psn: { fetched_at: STALE_ISO },
    };
  });

  it('returns stale keys in sweep rank order', () => {
    const keys = resolveStaleSweepKeys(sources, {
      freshnessStatus: (src) => fetcherFreshness(src).status,
      credentialsSatisfied: () => true,
      hasRunState: () => false,
      cooldownMs: () => 0,
      disconnected: () => false,
    });
    expect(keys).toEqual(['epic', 'psn', 'steam']);
  });

  it('excludes disconnected fetchers', () => {
    const keys = resolveStaleSweepKeys(sources, {
      freshnessStatus: (src) => fetcherFreshness(src).status,
      credentialsSatisfied: () => true,
      hasRunState: () => false,
      cooldownMs: () => 0,
      disconnected: (key) => key === 'psn',
    });
    expect(keys).toEqual(['epic', 'steam']);
  });
});

describe('runBatchKeys (Pro bulk stale queue)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div>';
    localStorage.clear();
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('runs keys sequentially in order', async () => {
    const order = [];
    vi.spyOn(fetcherRunner, 'waitForQueueSlot').mockResolvedValue(undefined);
    await fetcherRunner.runBatchKeysForTest(['epic', 'psn', 'steam'], {
      logPrefix: 'run stale',
      runFn: async (key) => {
        order.push(key);
        return true;
      },
    });
    expect(order).toEqual(['epic', 'psn', 'steam']);
  });

  it('aborts when cancel epoch bumps mid-batch', async () => {
    const order = [];
    vi.spyOn(fetcherRunner, 'waitForQueueSlot').mockResolvedValue(undefined);
    await fetcherRunner.runBatchKeysForTest(['epic', 'psn', 'steam'], {
      logPrefix: 'run stale',
      runFn: async (key) => {
        order.push(key);
        if (order.length === 1) fetcherRunner.bumpCancelEpochForTest();
        return true;
      },
    });
    expect(order).toEqual(['epic']);
  });
});

describe('fetcherRunner.runAllStale', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div>';
    localStorage.clear();
    sessionStorage.clear();
    state.libraryMeta = {};
    fetcherRunner.invalidateApiProbe();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('no-ops when API is unavailable', async () => {
    state.libraryMeta.steam = { game_count: 1, fetched_at: STALE_ISO };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false })));
    await fetcherRunner.probeApi(true);
    const order = [];
    await fetcherRunner.runAllStale();
    expect(order).toEqual([]);
  });

  it('no-ops when nothing is stale', async () => {
    state.libraryMeta.steam = { game_count: 1, fetched_at: new Date().toISOString() };
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
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
              cmd: 'fetch.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
    await fetcherRunner.probeApi(true);
    await expect(fetcherRunner.runAllStale()).resolves.toBeUndefined();
  });
});
