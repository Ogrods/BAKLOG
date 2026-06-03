import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  fetcherFreshness,
  humanizeAge,
  diffItadDeals,
  maybeAutoRefreshItad,
  ITAD_AUTO_REFRESH_INTERVAL_MS,
  serverChipState,
  fetchWithTimeout,
  markReconnectRequired,
  clearReconnectRequired,
  dismissReconnectRequired,
  isProviderReconnectRequired,
  reconnectRequiredForFetcherKey,
  syncReconnectFromAuthStatus,
  noteAuthCooldownStrike,
  authCooldownDurationMs,
} from '../js/fetcher-health.js';
import { state } from '../js/state.js';

vi.mock('../js/connections.js', () => ({
  FETCHER_AUTH_PROVIDER: { gog: 'gog', psn: 'psn' },
  isProviderConnected: vi.fn(() => false),
  noteFetcherAuthFailure: vi.fn(() => false),
  showReconnectBanner: vi.fn(),
}));

import { isProviderConnected } from '../js/connections.js';

describe('humanizeAge', () => {
  it('formats seconds and minutes', () => {
    expect(humanizeAge(30_000)).toBe('30s');
    expect(humanizeAge(120_000)).toBe('2m');
  });
});

describe('fetcherFreshness', () => {
  it('marks missing when no fetched_at', () => {
    state.libraryMeta = { steam: { game_count: 10 } };
    const result = fetcherFreshness({ metaKey: 'steam', countFn: null });
    expect(result.status).toBe('missing');
  });

  it('marks fresh for recent fetch', () => {
    state.libraryMeta = {
      steam: { game_count: 10, fetched_at: new Date().toISOString() },
    };
    const result = fetcherFreshness({ metaKey: 'steam', countFn: null });
    expect(result.status).toBe('fresh');
  });

  it('uses tighter thresholds for ITAD', () => {
    const thirtyMinAgo = new Date(Date.now() - 30 * 60_000).toISOString();
    state.libraryMeta = {
      itad: { fetched_at: thirtyMinAgo, by_key: { 'wishlist:1': {} } },
    };
    expect(fetcherFreshness({ metaKey: 'itad', countFn: null }).status).toBe('fresh');

    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60_000).toISOString();
    state.libraryMeta.itad.fetched_at = twoHoursAgo;
    expect(fetcherFreshness({ metaKey: 'itad', countFn: null }).status).toBe('recent');

    const sevenHoursAgo = new Date(Date.now() - 7 * 60 * 60_000).toISOString();
    state.libraryMeta.itad.fetched_at = sevenHoursAgo;
    expect(fetcherFreshness({ metaKey: 'itad', countFn: null }).status).toBe('stale');
  });
});

describe('diffItadDeals', () => {
  it('counts new sales and historical lows', () => {
    const prev = {
      'wishlist:1': { cut: 0, is_historical_low: false },
      'wishlist:2': { cut: 20, is_historical_low: false },
    };
    const next = {
      'wishlist:1': { cut: 25, is_historical_low: true },
      'wishlist:2': { cut: 20, is_historical_low: true },
      'wishlist:3': { cut: 10, is_historical_low: false },
    };
    expect(diffItadDeals(prev, next)).toEqual({ newSales: 2, newHistoricalLows: 2 });
  });

  it('returns zero when nothing changed', () => {
    const data = { 'wishlist:1': { cut: 10, is_historical_low: true } };
    expect(diffItadDeals(data, data)).toEqual({ newSales: 0, newHistoricalLows: 0 });
  });
});

describe('maybeAutoRefreshItad', () => {
  beforeEach(() => {
    state.prefs = {};
    state.libraryMeta = {
      itad: {
        fetched_at: new Date(Date.now() - 2 * ITAD_AUTO_REFRESH_INTERVAL_MS).toISOString(),
        by_key: { 'wishlist:1': {} },
      },
    };
  });

  it('returns early before 7am local', () => {
    const runFn = vi.fn();
    const ok = maybeAutoRefreshItad({
      getHour: () => 6,
      isApiAvailable: () => true,
      stateFor: () => null,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('returns early if last auto-run was less than 60min ago', () => {
    const runFn = vi.fn();
    const now = Date.now();
    const ok = maybeAutoRefreshItad({
      getHour: () => 10,
      now,
      getLastRun: () => now - 30 * 60_000,
      isApiAvailable: () => true,
      stateFor: () => null,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('queues itad when stale and gates pass', () => {
    const runFn = vi.fn();
    const setLastRun = vi.fn();
    const now = 4_000_000_000;
    const ok = maybeAutoRefreshItad({
      getHour: () => 10,
      now,
      getLastRun: () => 0,
      setLastRun,
      isApiAvailable: () => true,
      stateFor: () => null,
      runFn,
    });
    expect(ok).toBe(true);
    expect(runFn).toHaveBeenCalledWith('itad', { auto: true });
    expect(setLastRun).toHaveBeenCalledWith(now);
  });

  it('respects itadAutoRefreshDisabled pref', () => {
    state.prefs.itadAutoRefreshDisabled = true;
    const runFn = vi.fn();
    expect(maybeAutoRefreshItad({
      getHour: () => 10,
      isApiAvailable: () => true,
      stateFor: () => null,
      runFn,
    })).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });
});

describe('serverChipState', () => {
  it('maps launching and cancelling to running chip state', () => {
    expect(serverChipState('launching')).toBe('running');
    expect(serverChipState('cancelling')).toBe('running');
    expect(serverChipState('running')).toBe('running');
    expect(serverChipState('queued')).toBe('queued');
    expect(serverChipState('done')).toBeNull();
  });
});

describe('fetchWithTimeout', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('resolves when fetch completes before timeout', async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ ok: true }));
    vi.stubGlobal('fetch', fetchMock);
    const p = fetchWithTimeout('/api/runs', {}, 1000);
    await expect(p).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/runs',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('rejects with server not responding when fetch hangs', async () => {
    vi.useRealTimers();
    vi.stubGlobal('fetch', (_url, opts) => new Promise((_, reject) => {
      opts.signal.addEventListener('abort', () => {
        reject(Object.assign(new Error('Aborted'), { name: 'AbortError' }));
      });
    }));
    await expect(fetchWithTimeout('/api/runs', {}, 30)).rejects.toThrow('server not responding');
  });
});

describe('reconnect-required state', () => {
  beforeEach(() => {
    localStorage.clear();
    clearReconnectRequired('gog');
    clearReconnectRequired('psn');
    isProviderConnected.mockReturnValue(false);
  });

  it('marks provider reconnect-required and maps to fetcher key', () => {
    markReconnectRequired('gog');
    expect(isProviderReconnectRequired('gog')).toBe(true);
    expect(reconnectRequiredForFetcherKey('gog')).toBe(true);
    expect(reconnectRequiredForFetcherKey('steam')).toBe(false);
  });

  it('dismiss hides reconnect-required until cleared', () => {
    markReconnectRequired('psn');
    dismissReconnectRequired('psn');
    expect(isProviderReconnectRequired('psn')).toBe(false);
    expect(localStorage.getItem('baklog-reconnect-dismissed')).toContain('psn');
  });

  it('clear on connected provider', () => {
    markReconnectRequired('gog');
    isProviderConnected.mockReturnValue(true);
    expect(isProviderReconnectRequired('gog')).toBe(false);
  });

  it('syncReconnectFromAuthStatus marks expired providers', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({
      ok: true,
      json: () => Promise.resolve({
        providers: [
          { key: 'gog', status: 'expired' },
          { key: 'psn', status: 'connected' },
        ],
      }),
    })));
    await syncReconnectFromAuthStatus();
    expect(isProviderReconnectRequired('gog')).toBe(true);
    expect(isProviderReconnectRequired('psn')).toBe(false);
  });

  it('max auth cooldown strike marks reconnect-required', () => {
    const maxStrikes = 3;
    for (let i = 0; i < maxStrikes - 1; i++) noteAuthCooldownStrike('gog');
    expect(isProviderReconnectRequired('gog')).toBe(false);
    noteAuthCooldownStrike('gog');
    expect(isProviderReconnectRequired('gog')).toBe(true);
    expect(authCooldownDurationMs(maxStrikes)).toBe(60 * 60_000);
  });

  it('clearReconnectRequired removes state and dismiss flag', () => {
    markReconnectRequired('gog');
    dismissReconnectRequired('gog');
    clearReconnectRequired('gog');
    markReconnectRequired('gog');
    expect(isProviderReconnectRequired('gog')).toBe(true);
  });
});
