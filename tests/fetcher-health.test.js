import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { ingestAuthStatusProviders } from '../js/connections.js';
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
  isFetcherReconnectRequired,
  reconnectProviderForFetcher,
  fetcherCredentialsSatisfied,
  connectProviderForFetcher,
  connectionsNavigateProvider,
  fetcherRunner,
  renderDashboardFetcherHealth,
  buildFetcherHealthRows,
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
    wishlistXbox: 'xbox_wishlist',
  },
  isProviderConnected: vi.fn(() => false),
  noteFetcherAuthFailure: vi.fn(() => false),
  showReconnectBanner: vi.fn(),
  authStatusLoaded: () => connMock.loaded,
  providerStatus: (p) => connMock.statuses[p] ?? null,
  ingestAuthStatusProviders: vi.fn(),
  groupRepFor: (key) => (key === 'gog_galaxy' ? 'gog' : key === 'amazon' ? 'amazon_web' : key === 'itch_local' ? 'itch' : key),
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

  it('gog not disconnected when gog_galaxy is connected', () => {
    connMock.statuses.gog = 'disconnected';
    connMock.statuses.gog_galaxy = 'connected';
    expect(isFetcherDisconnected('gog')).toBe(false);
    expect(fetcherCredentialsSatisfied('gog')).toBe(true);
  });

  it('gog reconnect suppressed when gog_galaxy is connected', () => {
    connMock.statuses.gog = 'expired';
    connMock.statuses.gog_galaxy = 'connected';
    markReconnectRequired('gog');
    expect(isFetcherReconnectRequired('gog')).toBe(false);
    expect(reconnectProviderForFetcher('gog')).toBe(null);
  });

  it('gog reconnect required when web session bad and no healthy sibling', () => {
    connMock.statuses.gog = 'connected';
    connMock.statuses.gog_galaxy = 'disconnected';
    markReconnectRequired('gog');
    expect(isFetcherReconnectRequired('gog')).toBe(true);
    expect(connectionsNavigateProvider('gog')).toBe('gog');
  });

  it('itch not disconnected when itch_local is connected', () => {
    connMock.statuses.itch = 'disconnected';
    connMock.statuses.itch_local = 'connected';
    expect(isFetcherDisconnected('itch')).toBe(false);
    expect(fetcherCredentialsSatisfied('itch')).toBe(true);
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
    connMock.statuses = {};
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

  it('returns early if last auto-run was less than the refresh interval ago', () => {
    const runFn = vi.fn();
    const now = Date.now();
    const ok = maybeAutoRefreshItad({
      getHour: () => 10,
      now,
      getLastRun: () => now - ITAD_AUTO_REFRESH_INTERVAL_MS / 2,
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
    fetcherRunner.flushLinesNow();
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

  it('stays reconnect-required while server status is still connected', () => {
    markReconnectRequired('gog');
    ingestAuthStatusProviders([{ key: 'gog', status: 'connected' }]);
    expect(isProviderReconnectRequired('gog')).toBe(true);
  });

  it('clearReconnectRequired drops reconnect flag after user reconnects', () => {
    markReconnectRequired('gog');
    clearReconnectRequired('gog');
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

  it('clears sticky failed chip state when provider reconnects', () => {
    fetcherRunner.markRunFailedForTest('wishlistXbox');
    markReconnectRequired('xbox_wishlist');
    expect(fetcherRunner.isRunFailedForTest('wishlistXbox')).toBe(true);
    document.dispatchEvent(new CustomEvent('baklog:auth-status', {
      detail: { providers: [{ key: 'xbox_wishlist', status: 'connected' }] },
    }));
    expect(fetcherRunner.isRunFailedForTest('wishlistXbox')).toBe(false);
    expect(isProviderReconnectRequired('xbox_wishlist')).toBe(false);
  });

  it('connected event does not clear failed chip without prior reconnect-required', () => {
    fetcherRunner.markRunFailedForTest('wishlistXbox');
    document.dispatchEvent(new CustomEvent('baklog:auth-status', {
      detail: { providers: [{ key: 'xbox_wishlist', status: 'connected' }] },
    }));
    expect(fetcherRunner.isRunFailedForTest('wishlistXbox')).toBe(true);
  });
});

describe('syncLogPanelChrome', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fetcherRunLog" class="fh-log open">
        <span class="fh-log-title" data-role="title">Fetcher log</span>
        <span class="fh-log-status queued" data-role="status">queued</span>
        <div class="fh-log-body" data-role="body"></div>
      </div>`;
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('maps launching to Launching title and launching badge', () => {
    fetcherRunner.syncLogPanelChrome({ label: 'Covers', key: 'steamCovers' }, 'launching');
    const title = document.querySelector('[data-role="title"]');
    const status = document.querySelector('[data-role="status"]');
    expect(title?.textContent).toBe('Launching: Covers');
    expect(status?.textContent).toBe('launching');
    expect(status?.classList.contains('launching')).toBe(true);
    expect(document.querySelector('.fh-log-body')?.getAttribute('data-running')).toBe('1');
  });

  it('maps queued with extra to Queued title and queue position badge', () => {
    fetcherRunner.syncLogPanelChrome(
      { label: 'Cross-store', key: 'crossStore' },
      'queued',
      '2 of 2 — waiting for Covers',
    );
    expect(document.querySelector('[data-role="title"]')?.textContent).toBe(
      'Queued: Cross-store',
    );
    expect(document.querySelector('[data-role="status"]')?.textContent).toBe(
      'queued · 2 of 2 — waiting for Covers',
    );
  });

  it('maps running to Running title and running badge', () => {
    fetcherRunner.syncLogPanelChrome({ label: 'HLTB', key: 'hltb' }, 'running', '12.3s');
    expect(document.querySelector('[data-role="title"]')?.textContent).toBe('Running: HLTB');
    expect(document.querySelector('[data-role="status"]')?.textContent).toBe('running · 12.3s');
    expect(document.querySelector('[data-role="status"]')?.classList.contains('running')).toBe(true);
  });

  it('maps cancelling to Running title with cancelling extra', () => {
    fetcherRunner.syncLogPanelChrome({ label: 'Nintendo', key: 'nintendo' }, 'cancelling');
    expect(document.querySelector('[data-role="title"]')?.textContent).toBe('Running: Nintendo');
    expect(document.querySelector('[data-role="status"]')?.textContent).toBe('running · cancelling');
  });

  it('maps done to done badge', () => {
    fetcherRunner.syncLogPanelChrome({ label: 'Steam', key: 'steam' }, 'done', '4.2s');
    expect(document.querySelector('[data-role="status"]')?.textContent).toBe('done · 4.2s');
    expect(document.querySelector('[data-role="status"]')?.classList.contains('done')).toBe(true);
  });
});

describe('SSE stream resume cursor', () => {
  it('streamUrl includes ?since after lines are recorded', () => {
    const runId = 'test-run-seq';
    fetcherRunner.recordLineSeqForTest(runId, 12);
    expect(fetcherRunner.streamUrlForTest(runId)).toBe('/api/stream/test-run-seq?since=12');
    expect(fetcherRunner.streamUrlForTest('fresh-run')).toBe('/api/stream/fresh-run');
  });
});

describe('log line caps and rAF batching', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fetcherRow" class="fh-row is-expanded">
        <div id="dashboardFetcherHealth"></div>
        <div id="fetcherRunLog" class="fh-log"></div>
      </div>`;
    fetcherRunner.reopenLogPanel();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  it('appendLine schedules a single rAF for a burst of lines', () => {
    const rafSpy = vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation(() => 42);
    fetcherRunner.appendLineForTest('a');
    fetcherRunner.appendLineForTest('b');
    fetcherRunner.appendLineForTest('c');
    expect(rafSpy).toHaveBeenCalledTimes(1);
    fetcherRunner.flushLinesNow();
    const text = document.querySelector('[data-role="body"]')?.textContent || '';
    expect(text).toContain('a');
    expect(text).toContain('b');
    expect(text).toContain('c');
  });

  it('evicts oldest DOM lines past LOG_DOM_CAP', () => {
    for (let i = 0; i < 4010; i++) {
      fetcherRunner.appendLineForTest(`line ${i}`);
    }
    fetcherRunner.flushLinesNow();
    const body = document.querySelector('[data-role="body"]');
    expect(body?.children.length).toBeLessThanOrEqual(4000);
    expect(body?.firstChild?.textContent).toContain('line 10');
  });

  it('logLevelKindForTest maps semantic levels to log line classes', () => {
    expect(fetcherRunner.logLevelKindForTest()).toEqual({
      cmd: 'cmd',
      output: 'stdout',
      info: 'meta',
      warn: 'warn',
      error: 'stderr',
    });
  });

  it.each([
    ['info', 'meta'],
    ['warn', 'warn'],
    ['error', 'stderr'],
    ['cmd', 'cmd'],
    ['output', 'stdout'],
  ])('logEventForTest(%s) renders fh-log-line %s', (level, kind) => {
    fetcherRunner.logEventForTest(level, `level-${level}`);
    fetcherRunner.flushLinesNow();
    const line = document.querySelector(`[data-role="body"] .fh-log-line.${kind}`);
    expect(line?.textContent).toBe(`level-${level}`);
  });
});

describe('reconcileRunStateFromSnapshot', () => {
  it('clears stale running chip when run finished in history', () => {
    fetcherRunner.markChipStateForTest('hltb', 'running', 'run-hltb-1');
    expect(fetcherRunner.stateFor('hltb')).toBe('running');
    fetcherRunner.reconcileRunStateFromSnapshot({
      active: null,
      queue: [],
      history: [
        {
          id: 'done1',
          key: 'hltb',
          status: 'done',
          exit_code: 0,
          ended_at: Date.now() / 1000,
        },
      ],
    });
    expect(fetcherRunner.stateFor('hltb')).toBeNull();
  });
});

describe('syncLogHeightToCard', () => {
  let matchMediaDesktop = true;

  beforeEach(() => {
    matchMediaDesktop = true;
    document.body.innerHTML = `
      <div id="fetcherRow" class="fh-row is-expanded">
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

  it('does not set height when fetcher row is collapsed', () => {
    const row = document.getElementById('fetcherRow');
    row.classList.remove('is-expanded');
    row.classList.add('is-collapsed');
    const log = document.getElementById('fetcherRunLog');
    fetcherRunner.syncLogHeightToCard();
    expect(log.style.maxHeight).toBe('');
    expect(log.style.height).toBe('');
  });
});

describe('fetcher bar collapse', () => {
  beforeEach(() => {
    state.prefs.fetcherCollapsed = true;
    document.body.innerHTML = `
      <div id="fetcherRow" class="fh-row">
        <div id="dashboardFetcherHealth">
          <div class="fh-bar" data-role="fetcher-bar">
            <span data-role="bar-status"></span>
            <span data-role="bar-tail"></span>
            <button type="button" data-role="bar-toggle"></button>
          </div>
        </div>
        <div id="fetcherRunLog" class="fh-log"></div>
      </div>`;
    fetcherRunner.applyFetcherRowLayout();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    state.prefs.fetcherCollapsed = true;
  });

  it('defaults to collapsed when fetcherCollapsed pref is true', () => {
    const row = document.getElementById('fetcherRow');
    expect(row.classList.contains('is-collapsed')).toBe(true);
    expect(row.classList.contains('is-expanded')).toBe(false);
    expect(document.getElementById('fetcherRunLog').classList.contains('open')).toBe(false);
  });

  it('expandPanel manual clears fetcherCollapsed pref', () => {
    fetcherRunner.expandPanel({ manual: true });
    expect(state.prefs.fetcherCollapsed).toBe(false);
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);
  });

  it('collapsePanel manual sets fetcherCollapsed pref', () => {
    fetcherRunner.expandPanel({ manual: true });
    fetcherRunner.collapsePanel({ manual: true });
    expect(state.prefs.fetcherCollapsed).toBe(true);
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);
  });

  it('appendLine updates bar tail while collapsed', () => {
    fetcherRunner.appendLineForTest('hello from fetcher');
    fetcherRunner.flushLinesNow();
    const tail = document.querySelector('[data-role="bar-tail"]');
    expect(tail?.textContent).toBe('hello from fetcher');
  });

  it('force expand without manual keeps pref collapsed for revert', () => {
    fetcherRunner.expandPanel({ manual: false });
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);
    expect(state.prefs.fetcherCollapsed).toBe(true);
    fetcherRunner.revertFetcherLayoutIfIdle();
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);
  });

  it('manual collapse mid-run suppresses auto-reopen from polling', () => {
    fetcherRunner.applyServerSnapshotInFlight({ active: { key: 'steam' } });
    fetcherRunner.expandPanel({ manual: false });
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);

    fetcherRunner.collapsePanel({ manual: true });
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);

    fetcherRunner.expandPanel({ manual: false });
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);

    fetcherRunner.applyServerSnapshotInFlight({});
  });

  it('clears auto-expand suppression once the fetcher goes idle', () => {
    fetcherRunner.applyServerSnapshotInFlight({ active: { key: 'steam' } });
    fetcherRunner.collapsePanel({ manual: true });
    fetcherRunner.expandPanel({ manual: false });
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);

    fetcherRunner.applyServerSnapshotInFlight({});
    fetcherRunner.revertFetcherLayoutIfIdle();
    fetcherRunner.expandPanel({ manual: false });
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);

    fetcherRunner.revertFetcherLayoutIfIdle();
  });

  it('bar toggle is the sole focusable control with aria-expanded', () => {
    const bar = document.querySelector('[data-role="fetcher-bar"]');
    const toggle = document.querySelector('[data-role="bar-toggle"]');
    expect(bar?.getAttribute('role')).toBeNull();
    expect(bar?.getAttribute('tabindex')).toBeNull();
    expect(toggle?.getAttribute('aria-expanded')).toBe('false');
  });

  it('bar toggle gains is-open class when expanded', () => {
    const toggle = document.querySelector('[data-role="bar-toggle"]');
    expect(toggle?.classList.contains('is-open')).toBe(false);
    fetcherRunner.expandPanel({ manual: true });
    fetcherRunner.updateFetcherBar();
    expect(toggle?.classList.contains('is-open')).toBe(true);
    fetcherRunner.collapsePanel({ manual: true });
    fetcherRunner.updateFetcherBar();
    expect(toggle?.classList.contains('is-open')).toBe(false);
  });

  it('toggleFetcherPanel from expanded collapses the row', () => {
    fetcherRunner.expandPanel({ manual: true });
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);
    fetcherRunner.toggleFetcherPanel({ manual: true });
    expect(document.getElementById('fetcherRow').classList.contains('is-collapsed')).toBe(true);
    expect(state.prefs.fetcherCollapsed).toBe(true);
  });
});

describe('log tail follow', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fetcherRow" class="fh-row is-expanded">
        <div id="dashboardFetcherHealth"></div>
        <div id="fetcherRunLog" class="fh-log"></div>
      </div>`;
    fetcherRunner.reopenLogPanel();
  });

  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('flushLinesNow scrolls when followTail is true even if not near bottom', () => {
    const body = document.querySelector('[data-role="body"]');
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 500 });
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 100 });
    body.scrollTop = 0;
    fetcherRunner.setFollowTailForTest(true);
    fetcherRunner.appendLineForTest('line one');
    fetcherRunner.flushLinesNow();
    expect(body.scrollTop).toBe(500);
  });

  it('flushLinesNow does not scroll when followTail is false', () => {
    const body = document.querySelector('[data-role="body"]');
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 500 });
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 100 });
    body.scrollTop = 50;
    fetcherRunner.setFollowTailForTest(false);
    fetcherRunner.appendLineForTest('line one');
    fetcherRunner.flushLinesNow();
    expect(body.scrollTop).toBe(50);
  });

  it('re-enables followTail after scroll-up idle', () => {
    vi.useFakeTimers();
    const body = document.querySelector('[data-role="body"]');
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 500 });
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 100 });
    body.scrollTop = 0;
    body.dispatchEvent(new Event('scroll'));
    fetcherRunner.appendLineForTest('before idle');
    fetcherRunner.flushLinesNow();
    expect(body.scrollTop).toBe(0);
    vi.advanceTimersByTime(12_000);
    fetcherRunner.appendLineForTest('after idle');
    fetcherRunner.flushLinesNow();
    expect(body.scrollTop).toBe(500);
    vi.useRealTimers();
  });
});

describe('failed chip routes to Connections', () => {
  const stubFetchers = (fetchers) => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return { ok: true, json: async () => ({ fetchers }) };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
  };

  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = {};
    document.body.innerHTML =
      '<div id="fetcherRunLog"></div><div id="dashboardFetcherHealth"></div>';
  });

  afterEach(() => {
    // Drain the sticky failed/reconnect state set during the test so later
    // suites start clean (reconnect event clears lastRunFailedByKey + flag).
    fetcherRunner.markChipStateForTest('wishlistXbox', null);
    markReconnectRequired('xbox_wishlist');
    document.dispatchEvent(new CustomEvent('baklog:auth-status', {
      detail: { providers: [{ key: 'xbox_wishlist', status: 'connected' }] },
    }));
    clearReconnectRequired('xbox_wishlist');
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
  });

  it('a freshly-failed auth chip routes clicks to Connections, not a re-run', async () => {
    stubFetchers([{
      key: 'wishlistXbox',
      label: 'WL Xbox',
      metaKey: 'wishlist_xbox',
      group: 'library',
      color: '#107c10',
      cmd: 'fetch_xbox_wishlist.py',
      available: true,
    }]);
    await fetcherRunner.probeApi(true);

    // Simulate the ~10s post-failure window: terminal 'failed' runState plus
    // the auth-failure bookkeeping (sticky failed + provider reconnect-required).
    connMock.statuses.xbox_wishlist = 'expired';
    markReconnectRequired('xbox_wishlist');
    fetcherRunner.markRunFailedForTest('wishlistXbox');
    fetcherRunner.markChipStateForTest('wishlistXbox', 'failed');

    renderDashboardFetcherHealth();

    const chip = document.querySelector('.fh-chip[data-fetcher-key="wishlistXbox"]');
    expect(chip).not.toBeNull();
    // Routes to Connections (data-fetcher-connect) instead of re-running.
    expect(chip.getAttribute('data-fetcher-connect')).toBe('xbox_wishlist');
    expect(chip.disabled).toBe(false);
    // Still visibly failed while the run-state flash lingers.
    expect(chip.classList.contains('fh-chip-failed')).toBe(true);
  });
});

describe('fetcher header popover', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="fetcherPopoverBackdrop" class="fetcher-popover-backdrop" hidden></div>
      <div id="fetcherPopover" class="fetcher-popover" role="dialog" hidden>
        <div class="fetcher-popover-head">
          <span class="fetcher-popover-title">Fetchers</span>
          <button type="button" class="fetcher-stat-layout-toggle" id="fetcherStatLayoutToggle">Layout</button>
          <button type="button" data-fetcher-popover-close aria-label="Close">&times;</button>
        </div>
        <div class="fetcher-popover-scroll">
          <div id="fetcherRow" class="fh-row fh-row--popover is-expanded">
            <div id="dashboardFetcherHealth"></div>
            <div id="fetcherRunLog" class="fh-log"></div>
          </div>
        </div>
      </div>
      <button type="button" id="fetcherGlobalStatus" aria-expanded="false" aria-controls="fetcherPopover"></button>`;
  });

  afterEach(() => {
    document.body.innerHTML = '';
    fetcherRunner.hideFetcherPopover?.();
  });

  it('showFetcherPopover opens dialog without dashboard switch', () => {
    const ok = fetcherRunner.showFetcherPopover();
    expect(ok).toBe(true);
    expect(document.getElementById('fetcherPopover').hidden).toBe(false);
    expect(document.getElementById('fetcherPopoverBackdrop').hidden).toBe(false);
    expect(document.getElementById('fetcherGlobalStatus').getAttribute('aria-expanded')).toBe('true');
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);
  });

  it('collapsePanel closes popover instead of collapsing row', () => {
    fetcherRunner.showFetcherPopover({ focusPanel: false });
    fetcherRunner.collapsePanel({ manual: true });
    expect(document.getElementById('fetcherPopover').hidden).toBe(true);
    expect(document.getElementById('fetcherGlobalStatus').getAttribute('aria-expanded')).toBe('false');
  });

  it('syncLogHeightToCard skips height sync when popover is mounted', () => {
    fetcherRunner.showFetcherPopover({ focusPanel: false });
    const log = document.getElementById('fetcherRunLog');
    log.classList.add('open');
    const card = document.getElementById('dashboardFetcherHealth');
    Object.defineProperty(card, 'offsetHeight', { configurable: true, value: 200 });
    log.style.maxHeight = '99px';
    log.style.height = '99px';
    fetcherRunner.syncLogHeightToCard();
    expect(log.style.maxHeight).toBe('');
    expect(log.style.height).toBe('');
  });

  it('toggleFetcherPopover opens then closes', () => {
    fetcherRunner.toggleFetcherPopover();
    expect(fetcherRunner.isFetcherPopoverOpen()).toBe(true);
    fetcherRunner.toggleFetcherPopover();
    expect(fetcherRunner.isFetcherPopoverOpen()).toBe(false);
  });

  it('console Collapse toggles only the log body, not the popover', () => {
    fetcherRunner.showFetcherPopover({ focusPanel: false });
    fetcherRunner.reopenLogPanel();
    const pop = document.getElementById('fetcherPopover');
    const log = document.getElementById('fetcherRunLog');
    const closeBtn = log.querySelector('[data-role="close"]');
    expect(pop.hidden).toBe(false);
    expect(log.classList.contains('fh-log--collapsed')).toBe(false);

    closeBtn.click();
    expect(log.classList.contains('fh-log--collapsed')).toBe(true);
    expect(closeBtn.textContent).toBe('Expand');
    expect(pop.hidden).toBe(false);
    expect(document.getElementById('fetcherRow').classList.contains('is-expanded')).toBe(true);

    closeBtn.click();
    expect(log.classList.contains('fh-log--collapsed')).toBe(false);
    expect(closeBtn.textContent).toBe('Collapse');
  });
});

describe('header pill ticker', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button type="button" id="fetcherGlobalStatus" class="fh-global-status fh-global-status-idle">
        <span id="fetcherGlobalStatusLive" class="sr-only" aria-live="polite"></span>
        <span id="fetcherGlobalStatusText" class="fh-global-status-label">Fetcher log</span>
        <span id="fetcherGlobalStatusTail" class="fh-global-status-tail" aria-hidden="true"></span>
      </button>
      <div id="fetcherRow" class="fh-row is-expanded">
        <div id="dashboardFetcherHealth"></div>
        <div id="fetcherRunLog" class="fh-log"></div>
      </div>`;
    fetcherRunner.reopenLogPanel();
  });

  afterEach(() => {
    document.body.innerHTML = '';
    fetcherRunner.markChipStateForTest('steam', null);
  });

  it('streams the latest log line into the tail while active', () => {
    const pill = document.getElementById('fetcherGlobalStatus');
    const tail = document.getElementById('fetcherGlobalStatusTail');
    fetcherRunner.markChipStateForTest('steam', 'running');
    expect(pill.classList.contains('fh-global-status-idle')).toBe(false);

    fetcherRunner.appendLineForTest('Fetched 10 games');
    expect(tail.textContent).toBe('Fetched 10 games');
    expect(pill.classList.contains('is-streaming')).toBe(true);
  });

  it('replaces the tail text in place when a new line arrives', () => {
    fetcherRunner.markChipStateForTest('steam', 'running');
    fetcherRunner.appendLineForTest('First line');
    fetcherRunner.appendLineForTest('Second line');
    expect(document.getElementById('fetcherGlobalStatusTail').textContent).toBe('Second line');
  });

  it('clears streaming state when the queue goes idle', () => {
    const pill = document.getElementById('fetcherGlobalStatus');
    const tail = document.getElementById('fetcherGlobalStatusTail');
    fetcherRunner.markChipStateForTest('steam', 'running');
    fetcherRunner.appendLineForTest('Working…');
    expect(pill.classList.contains('is-streaming')).toBe(true);

    fetcherRunner.markChipStateForTest('steam', null);
    expect(pill.classList.contains('is-streaming')).toBe(false);
    expect(tail.textContent).toBe('');
    expect(pill.classList.contains('fh-global-status-idle')).toBe(true);
  });
});

describe('fetcher stat strip', () => {
  const stubFetchers = (fetchers) => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return { ok: true, json: async () => ({ fetchers }) };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
  };

  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = {};
    clearReconnectRequired('gog');
    clearReconnectRequired('gog_galaxy');
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div><div id="fetcherRunLog"></div>';
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
    state.libraryMeta = {};
  });

  it('renders hero slash and per-group connected counts', async () => {
    const now = new Date().toISOString();
    state.libraryMeta = {
      steam: { fetched_at: now, game_count: 100 },
      nintendo: { fetched_at: now, game_count: 12 },
      epic: {},
      wishlistGog: { fetched_at: now },
      hltb: { fetched_at: now },
    };
    stubFetchers([
      { key: 'steam', label: 'Steam', metaKey: 'steam', group: 'library', color: '#1b2838', cmd: 'fetch_steam.py', available: true },
      { key: 'nintendo', label: 'Nintendo', metaKey: 'nintendo', group: 'library', color: '#e60012', cmd: 'fetch_nintendo.py', available: true },
      { key: 'epic', label: 'Epic', metaKey: 'epic', group: 'library', color: '#2f2d2e', cmd: 'fetch_epic.py', available: true },
      { key: 'wishlistGog', label: 'WL GOG', metaKey: 'wishlistGog', group: 'wishlist', color: '#6d28d9', cmd: 'fetch_gog_wishlist.py', available: true },
      { key: 'hltb', label: 'HLTB', metaKey: 'hltb', group: 'enrich', color: '#2d6a4f', cmd: 'fetch_hltb.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    expect(document.querySelector('.fh-stat--hero .fh-stat-value')?.textContent).toBe('4/5');

    const byLabel = Object.fromEntries(
      [...document.querySelectorAll('.fh-stats .fh-stat:not(.fh-stat--hero)')].map(tile => [
        tile.querySelector('.fh-stat-label')?.textContent,
        tile.querySelector('.fh-stat-value')?.textContent,
      ]),
    );
    expect(byLabel.Libraries).toBe('2');
    expect(byLabel.Wishlists).toBe('1');
    expect(byLabel.Enrichment).toBe('1');
    expect(byLabel['Last sync']).toMatch(/ago$/);
  });
});

describe('stat layout toggle', () => {
  const STAT_LAYOUT_KEY = 'baklog-fetcher-stat-layout';

  const stubFetchers = (fetchers) => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return { ok: true, json: async () => ({ fetchers }) };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
  };

  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = {};
    try { localStorage.removeItem(STAT_LAYOUT_KEY); } catch { /* ignore */ }
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div><div id="fetcherRunLog"></div>';
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    try { localStorage.removeItem(STAT_LAYOUT_KEY); } catch { /* ignore */ }
    document.body.innerHTML = '';
    state.libraryMeta = {};
  });

  it('defaults to compact and cycles to landscape with hero value intact', async () => {
    const now = new Date().toISOString();
    state.libraryMeta = {
      steam: { fetched_at: now, game_count: 100 },
      epic: {},
    };
    stubFetchers([
      { key: 'steam', label: 'Steam', metaKey: 'steam', group: 'library', color: '#1b2838', cmd: 'fetch_steam.py', available: true },
      { key: 'epic', label: 'Epic', metaKey: 'epic', group: 'library', color: '#2f2d2e', cmd: 'fetch_epic.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    const slot = document.getElementById('dashboardFetcherHealth');
    expect(slot?.dataset.statLayout).toBe('compact');
    expect(document.querySelector('.fh-stats.fh-stats--compact')).toBeTruthy();
    expect(document.querySelector('.fh-stat--hero .fh-stat-value')?.textContent).toBe('1/2');

    fetcherRunner.cycleStatLayout();
    expect(slot?.dataset.statLayout).toBe('landscape');
    expect(document.querySelector('.fh-stats.fh-stats--rail')).toBeTruthy();
    expect(document.querySelector('.fh-stat--hero .fh-stat-value')?.textContent).toBe('1/2');
  });
});

describe('enrichment chip compact count', () => {
  const stubFetchers = (fetchers) => {
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        return { ok: true, json: async () => ({ active: null, queue: [], history: [] }) };
      }
      if (u.includes('/api/fetchers')) {
        return { ok: true, json: async () => ({ fetchers }) };
      }
      if (u.includes('manifest.json')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      return { ok: false };
    }));
  };

  beforeEach(() => {
    connMock.loaded = true;
    connMock.statuses = {};
    document.body.innerHTML = '<div id="dashboardFetcherHealth"></div><div id="fetcherRunLog"></div>';
    state.allGames = [
      { store: 'gog', id: '1', name: 'Has HLTB', hltb_main_hours: 12 },
      { store: 'gog', id: '2', name: 'Needs HLTB' },
    ];
    state.itchGames = [];
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.innerHTML = '';
    state.libraryMeta = {};
    state.allGames = [];
    state.itchGames = [];
  });

  it('shows percent and optional pending new on the chip, not covered/total', async () => {
    const now = new Date().toISOString();
    state.libraryMeta = { hltb: { fetched_at: now } };
    stubFetchers([
      { key: 'hltb', label: 'HLTB', metaKey: 'hltb', group: 'enrich', color: '#2d6a4f', cmd: 'fetch_hltb.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    const countEl = document.querySelector('.fh-chip[data-fetcher-key="hltb"] .fh-chip-count');
    expect(countEl).not.toBeNull();
    const text = countEl.textContent;
    expect(text).toMatch(/^\d+%( · \d+ new)?$/);
    expect(text).not.toContain('/');
    expect(text).toContain('new');
  });

  it('shows only percent when nothing is pending', async () => {
    state.allGames = [
      { store: 'gog', id: '1', name: 'Done', hltb_main_hours: 5 },
      { store: 'gog', id: '2', name: 'Also done', hltb_main_hours: 8 },
    ];
    state.libraryMeta = {
      hltb: {
        fetched_at: new Date().toISOString(),
        'gog:2': false,
      },
    };
    stubFetchers([
      { key: 'hltb', label: 'HLTB', metaKey: 'hltb', group: 'enrich', color: '#2d6a4f', cmd: 'fetch_hltb.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    const text = document.querySelector('.fh-chip[data-fetcher-key="hltb"] .fh-chip-count')?.textContent;
    expect(text).toBe('100%');
    expect(text).not.toContain('new');
    expect(text).not.toContain('/');
  });

  it('drops " tags" from the Co-op chip label when new tags are pending', async () => {
    const now = new Date().toISOString();
    state.allGames = [
      { store: 'gog', id: '1', name: 'Tagged', coop_online: true },
      { store: 'gog', id: '2', name: 'Untagged' },
    ];
    state.libraryMeta = {
      steamTags: { fetched_at: now, rows_updated: 1 },
      steamReviews: { 'gog:1': 80, 'gog:2': 75 },
    };
    stubFetchers([
      { key: 'steamTags', label: 'Co-op tags', metaKey: 'steamTags', group: 'enrich', color: '#ea580c', cmd: 'enrich_steam_tags.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    const countText = document.querySelector('.fh-chip[data-fetcher-key="steamTags"] .fh-chip-count')?.textContent;
    expect(countText).toContain('new');
    const labelText = document.querySelector('.fh-chip[data-fetcher-key="steamTags"] .fh-chip-label')?.textContent;
    expect(labelText).toBe('Co-op');
  });

  it('keeps the full Co-op tags label when nothing is pending', async () => {
    const now = new Date().toISOString();
    state.allGames = [
      { store: 'gog', id: '1', name: 'Tagged', coop_online: true },
    ];
    state.libraryMeta = {
      steamTags: { fetched_at: now, rows_updated: 1 },
      steamReviews: { 'gog:1': 80 },
    };
    stubFetchers([
      { key: 'steamTags', label: 'Co-op tags', metaKey: 'steamTags', group: 'enrich', color: '#ea580c', cmd: 'enrich_steam_tags.py', available: true },
    ]);
    fetcherRunner.invalidateApiProbe();
    await fetcherRunner.probeApi(true);
    renderDashboardFetcherHealth();

    const countText = document.querySelector('.fh-chip[data-fetcher-key="steamTags"] .fh-chip-count')?.textContent;
    expect(countText).not.toContain('new');
    const labelText = document.querySelector('.fh-chip[data-fetcher-key="steamTags"] .fh-chip-label')?.textContent;
    expect(labelText).toBe('Co-op tags');
  });
});
