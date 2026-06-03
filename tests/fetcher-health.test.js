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
  refreshChipAgesInPlace,
  ensureAgeTicker,
  stopAgeTicker,
  startFastAgeTick,
  stopFastAgeTick,
  isFastAgeTickActive,
  isFetcherDisconnected,
  connectProviderForFetcher,
  fetcherRunner,
} from '../js/fetcher-health.js';
import { state } from '../js/state.js';

const connMock = vi.hoisted(() => ({
  statuses: {},
  loaded: true,
}));

vi.mock('../js/connections.js', () => ({
  FETCHER_AUTH_PROVIDER: {
    gog: 'gog',
    psn: 'psn',
    itad: 'itad',
    steam: 'steam',
    amazon: 'amazon',
  },
  isProviderConnected: vi.fn(() => false),
  noteFetcherAuthFailure: vi.fn(() => false),
  showReconnectBanner: vi.fn(),
  authStatusLoaded: () => connMock.loaded,
  providerStatus: (p) => connMock.statuses[p] ?? null,
  ingestAuthStatusProviders: vi.fn(),
}));

import { isProviderConnected, showReconnectBanner } from '../js/connections.js';

describe('isFetcherDisconnected', () => {
  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = {};
  });

  it('fails open when auth status not loaded', () => {
    connMock.loaded = false;
    connMock.statuses.gog = 'disconnected';
    expect(isFetcherDisconnected('gog')).toBe(false);
  });

  it('returns true for disconnected provider', () => {
    connMock.statuses.gog = 'disconnected';
    expect(isFetcherDisconnected('gog')).toBe(true);
  });

  it('returns false for connected or unverified', () => {
    connMock.statuses.gog = 'connected';
    expect(isFetcherDisconnected('gog')).toBe(false);
    connMock.statuses.gog = 'unverified';
    expect(isFetcherDisconnected('gog')).toBe(false);
  });

  it('returns false for enrichers without auth provider', () => {
    connMock.statuses.steam = 'disconnected';
    expect(isFetcherDisconnected('hltb')).toBe(false);
  });

  it('amazon requires both launcher and web disconnected', () => {
    connMock.statuses.amazon = 'disconnected';
    connMock.statuses.amazon_web = 'disconnected';
    expect(isFetcherDisconnected('amazon')).toBe(true);
    connMock.statuses.amazon = 'connected';
    expect(isFetcherDisconnected('amazon')).toBe(false);
  });

  it('connectProviderForFetcher picks amazon_web when disconnected', () => {
    connMock.statuses.amazon_web = 'disconnected';
    expect(connectProviderForFetcher('amazon')).toBe('amazon_web');
  });
});

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

  it('returns early when ITAD provider is disconnected', () => {
    connMock.statuses.itad = 'disconnected';
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

describe('fetcherRunner.run disconnected wall', () => {
  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = { gog: 'disconnected' };
    document.body.innerHTML = '<div id="fetcherRunLog"></div><div id="dashboardFetcherHealth"></div>';
    showReconnectBanner.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('does not POST when provider is disconnected', async () => {
    let runPosted = false;
    vi.stubGlobal('fetch', vi.fn(async (url, opts = {}) => {
      const u = String(url);
      if (u.includes('/api/runs') && !opts.method) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'gog',
              label: 'GOG',
              metaKey: 'gog',
              group: 'library',
              color: '#9d4edd',
              cmd: 'fetch_gog.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/run/') && opts.method === 'POST') {
        runPosted = true;
        return { ok: true, json: async () => ({ run_id: 'r1' }) };
      }
      return { ok: false };
    }));
    await fetcherRunner.probeApi(true);
    await fetcherRunner.run('gog');
    expect(runPosted).toBe(false);
    expect(showReconnectBanner).toHaveBeenCalledWith(['gog']);
    const log = document.querySelector('.fh-log-line');
    expect(log?.textContent).toMatch(/not connected/i);
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

function mountFetcherHealthSlot(steamAgeText = '5m') {
  document.body.innerHTML = `
    <div id="dashboardFetcherHealth">
      <button type="button" class="fh-chip" data-fetcher-key="steam">
        <span class="fh-chip-age">${steamAgeText}</span>
      </button>
      <button type="button" class="fh-chip" data-fetcher-key="gog">
        <span class="fh-chip-age">running</span>
      </button>
    </div>
  `;
}

describe('refreshChipAgesInPlace', () => {
  beforeEach(() => {
    stopAgeTicker();
    stopFastAgeTick();
    document.body.innerHTML = '';
    state.libraryMeta = {};
  });

  afterEach(() => {
    stopAgeTicker();
    stopFastAgeTick();
    document.body.innerHTML = '';
  });

  it('updates plain-age chip from logged fetched_at', () => {
    const fetchedAt = new Date(Date.now() - 3 * 60_000).toISOString();
    state.libraryMeta = { steam: { game_count: 10, fetched_at: fetchedAt } };
    mountFetcherHealthSlot('stale');
    const sources = [{ key: 'steam', metaKey: 'steam', countFn: null }];
    expect(refreshChipAgesInPlace({ sources, stateFor: () => null })).toBe(true);
    const age = document.querySelector('[data-fetcher-key="steam"] .fh-chip-age');
    expect(age.textContent).toBe('3m');
  });

  it('leaves running chip untouched', () => {
    const fetchedAt = new Date(Date.now() - 3 * 60_000).toISOString();
    state.libraryMeta = {
      steam: { game_count: 10, fetched_at: fetchedAt },
      gog: { game_count: 5, fetched_at: fetchedAt },
    };
    mountFetcherHealthSlot('3m');
    const sources = [
      { key: 'steam', metaKey: 'steam', countFn: null },
      { key: 'gog', metaKey: 'gog', countFn: null },
    ];
    refreshChipAgesInPlace({ sources, stateFor: (k) => (k === 'gog' ? 'running' : null) });
    expect(document.querySelector('[data-fetcher-key="gog"] .fh-chip-age').textContent).toBe('running');
  });

  it('clamps future fetched_at to 0s', () => {
    const future = new Date(Date.now() + 5_000).toISOString();
    state.libraryMeta = { steam: { game_count: 1, fetched_at: future } };
    mountFetcherHealthSlot('—');
    const sources = [{ key: 'steam', metaKey: 'steam', countFn: null }];
    refreshChipAgesInPlace({ sources, stateFor: () => null });
    expect(document.querySelector('[data-fetcher-key="steam"] .fh-chip-age').textContent).toBe('0s');
  });

  it('skips DOM writes when document is hidden', () => {
    const fetchedAt = new Date(Date.now() - 90_000).toISOString();
    state.libraryMeta = { steam: { game_count: 10, fetched_at: fetchedAt } };
    mountFetcherHealthSlot('old');
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    const sources = [{ key: 'steam', metaKey: 'steam', countFn: null }];
    expect(refreshChipAgesInPlace({ sources, stateFor: () => null })).toBe(true);
    expect(document.querySelector('[data-fetcher-key="steam"] .fh-chip-age').textContent).toBe('old');
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
  });

  it('returns false when panel is missing', () => {
    document.body.innerHTML = '';
    expect(refreshChipAgesInPlace({ sources: [], stateFor: () => null })).toBe(false);
  });
});

describe('age tickers', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: false });
    stopAgeTicker();
    stopFastAgeTick();
    document.body.innerHTML = '';
    state.libraryMeta = {};
  });

  afterEach(() => {
    stopAgeTicker();
    stopFastAgeTick();
    vi.useRealTimers();
    document.body.innerHTML = '';
  });

  it('ensureAgeTicker is idempotent', () => {
    const spy = vi.spyOn(globalThis, 'setInterval');
    ensureAgeTicker();
    expect(spy).toHaveBeenCalledTimes(1);
    ensureAgeTicker();
    expect(spy).toHaveBeenCalledTimes(1);
    stopAgeTicker();
    spy.mockRestore();
  });

  it('fast tick self-stops after 60 interval fires', () => {
    startFastAgeTick();
    expect(isFastAgeTickActive()).toBe(true);
    vi.advanceTimersByTime(60_000);
    expect(isFastAgeTickActive()).toBe(false);
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

describe('syncLogHeightToCard', () => {
  let matchMediaDesktop = true;

  beforeEach(() => {
    matchMediaDesktop = true;
    document.body.innerHTML = `
      <div id="fetcherRow" class="fh-row">
        <div id="dashboardFetcherHealth" class="dash-card dash-fetcher-health">
          <div class="fh-chips"></div>
        </div>
        <div id="fetcherRunLog" class="fh-log open">
          <div class="fh-log-head"></div>
          <div class="fh-log-body" data-role="body"></div>
        </div>
      </div>`;
    const card = document.getElementById('dashboardFetcherHealth');
    Object.defineProperty(card, 'offsetHeight', { configurable: true, value: 120 });
    vi.stubGlobal('matchMedia', (query) => ({
      matches: query.includes('768px') ? matchMediaDesktop : false,
      media: query,
    }));
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
  });

  it('sets log max-height to match the health card on desktop', () => {
    const log = document.getElementById('fetcherRunLog');
    fetcherRunner.syncLogHeightToCard();
    expect(log.style.maxHeight).toBe('120px');
    expect(log.style.height).toBe('120px');
  });

  it('clears inline height when matchMedia is mobile', () => {
    matchMediaDesktop = false;
    const log = document.getElementById('fetcherRunLog');
    log.style.maxHeight = '200px';
    log.style.height = '200px';
    fetcherRunner.syncLogHeightToCard();
    expect(log.style.maxHeight).toBe('');
    expect(log.style.height).toBe('');
  });
});
