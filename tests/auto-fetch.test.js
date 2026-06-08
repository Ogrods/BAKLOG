/** Auto-fetch on connect + staggered 24h background refresh (runs while hidden). */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('processAuthStatusTransitions', () => {
  let processAuthStatusTransitions;

  beforeEach(async () => {
    vi.resetModules();
    ({ processAuthStatusTransitions } = await import('../js/fetcher-health.js'));
  });

  it('does not auto-fetch on first ingest (prev undefined)', () => {
    const prev = new Map();
    const runConnect = vi.fn();
    processAuthStatusTransitions(
      [{ key: 'steam', status: 'connected', fetcher_keys: ['steam'] }],
      prev,
      { maybeAutoFetchOnConnect: runConnect, autoFetchOnConnect: true },
    );
    expect(runConnect).not.toHaveBeenCalled();
    expect(prev.get('steam')).toBe('connected');
  });

  it('auto-fetches on disconnected → connected', () => {
    const prev = new Map([['epic_wishlist', 'disconnected']]);
    const runConnect = vi.fn();
    processAuthStatusTransitions(
      [{ key: 'epic_wishlist', status: 'connected', fetcher_keys: ['wishlistEpic'] }],
      prev,
      { maybeAutoFetchOnConnect: runConnect, autoFetchOnConnect: true },
    );
    expect(runConnect).toHaveBeenCalledWith(['wishlistEpic'], expect.any(Object));
  });

  it('auto-fetches on expired → connected (reconnect)', () => {
    const prev = new Map([['gog', 'expired']]);
    const runConnect = vi.fn();
    processAuthStatusTransitions(
      [{ key: 'gog', status: 'connected', fetcher_keys: ['gog', 'wishlistGog'] }],
      prev,
      { maybeAutoFetchOnConnect: runConnect, autoFetchOnConnect: true },
    );
    expect(runConnect).toHaveBeenCalledWith(['gog', 'wishlistGog'], expect.any(Object));
  });

  it('does not auto-fetch when already connected', () => {
    const prev = new Map([['steam', 'connected']]);
    const runConnect = vi.fn();
    processAuthStatusTransitions(
      [{ key: 'steam', status: 'connected', fetcher_keys: ['steam'] }],
      prev,
      { maybeAutoFetchOnConnect: runConnect, autoFetchOnConnect: true },
    );
    expect(runConnect).not.toHaveBeenCalled();
  });

  it('respects pref off', () => {
    const prev = new Map([['steam', 'disconnected']]);
    const runConnect = vi.fn();
    processAuthStatusTransitions(
      [{ key: 'steam', status: 'connected', fetcher_keys: ['steam'] }],
      prev,
      { maybeAutoFetchOnConnect: runConnect, autoFetchOnConnect: false },
    );
    expect(runConnect).not.toHaveBeenCalled();
  });
});

describe('maybeAutoFetchOnConnect', () => {
  let state;
  let maybeAutoFetchOnConnect;

  const sources = [
    { key: 'steam', label: 'Steam', group: 'library', missingRequirements: [] },
    { key: 'wishlistSteam', label: 'Steam WL', group: 'wishlist', missingRequirements: [] },
    { key: 'steamReviews', label: 'Reviews', group: 'enrich', missingRequirements: [] },
  ];

  beforeEach(async () => {
    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ maybeAutoFetchOnConnect } = await import('../js/fetcher-health.js'));
    state.prefs = { autoFetchOnConnect: true };
  });

  it('does nothing when pref is off', async () => {
    state.prefs.autoFetchOnConnect = false;
    const runFn = vi.fn();
    const ok = await maybeAutoFetchOnConnect(['steam'], {
      isApiAvailable: () => true,
      loadFetcherSources: async () => {},
      sources,
      runFn,
      openFetcherLog: () => {},
      waitForQueueSlot: async () => {},
      getCancelEpoch: () => 1,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('runs provider fetcher_keys serialized', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    const waitForQueueSlot = vi.fn().mockResolvedValue(undefined);
    const ok = await maybeAutoFetchOnConnect(['steam', 'wishlistSteam', 'steamReviews'], {
      isApiAvailable: () => true,
      loadFetcherSources: async () => {},
      sources,
      runFn,
      openFetcherLog: () => {},
      waitForQueueSlot,
      getCancelEpoch: () => 1,
    });
    expect(ok).toBe(true);
    expect(runFn.mock.calls.map((c) => c[0])).toEqual(['steam', 'wishlistSteam', 'steamReviews']);
    expect(runFn.mock.calls.every((c) => c[1]?.auto === true)).toBe(true);
    expect(waitForQueueSlot).toHaveBeenCalledTimes(3);
  });

  it('returns false when API is unavailable', async () => {
    const runFn = vi.fn();
    const ok = await maybeAutoFetchOnConnect(['steam'], {
      isApiAvailable: () => false,
      loadFetcherSources: async () => {},
      sources,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('filters unknown fetcher keys and opens the fetcher log', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    const openFetcherLog = vi.fn();
    const ok = await maybeAutoFetchOnConnect(['steam', 'unknownKey'], {
      isApiAvailable: () => true,
      loadFetcherSources: async () => {},
      sources,
      runFn,
      openFetcherLog,
      waitForQueueSlot: async () => {},
      getCancelEpoch: () => 1,
    });
    expect(ok).toBe(true);
    expect(openFetcherLog).toHaveBeenCalled();
    expect(runFn).toHaveBeenCalledTimes(1);
    expect(runFn.mock.calls[0][0]).toBe('steam');
  });

  it('returns false when no keys match sources', async () => {
    const runFn = vi.fn();
    const ok = await maybeAutoFetchOnConnect(['bogus'], {
      isApiAvailable: () => true,
      loadFetcherSources: async () => {},
      sources,
      runFn,
      openFetcherLog: () => {},
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });
});

describe('maybeAutoFetchStale24h', () => {
  let state;
  let maybeAutoFetchStale24h;
  let AUTO_STALE_AGE_MS;
  let AUTO_STALE_STAGGER_MS;

  const sources = [
    { key: 'steam', label: 'Steam', group: 'library', metaKey: 'steam', missingRequirements: [] },
    { key: 'gog', label: 'GOG', group: 'library', metaKey: 'gog', missingRequirements: [] },
    { key: 'hltb', label: 'HLTB', group: 'enrich', metaKey: 'hltb', missingRequirements: [] },
    { key: 'itad', label: 'ITAD', group: 'deals', metaKey: 'itad', missingRequirements: [] },
  ];

  beforeEach(async () => {
    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({
      maybeAutoFetchStale24h,
      AUTO_STALE_AGE_MS,
      AUTO_STALE_STAGGER_MS,
    } = await import('../js/fetcher-health.js'));
    state.prefs = { autoFetchStale24h: true };
  });

  it('does nothing when pref is off', () => {
    state.prefs.autoFetchStale24h = false;
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('respects 30-minute stagger', () => {
    const runFn = vi.fn();
    const now = 1_000_000;
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now,
      getLastRun: () => now - (AUTO_STALE_STAGGER_MS - 60_000),
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips when a fetcher is in flight', () => {
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 1,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('picks the stalest eligible store fetcher', () => {
    const runFn = vi.fn();
    const setLastRun = vi.fn();
    const freshness = (src) => ({
      ageMs: src.key === 'gog' ? AUTO_STALE_AGE_MS + 50_000 : AUTO_STALE_AGE_MS + 10_000,
    });
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      setLastRun,
      sources,
      fetcherFreshness: freshness,
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(true);
    expect(runFn).toHaveBeenCalledWith('gog', { auto: true });
    expect(setLastRun).toHaveBeenCalled();
  });

  it('still runs while the page is hidden (minimized/unfocused window)', () => {
    // Phase 1: auto-refresh must keep working when document.visibilityState is
    // 'hidden'. Guards against a regression that re-adds an isPageHidden() bail.
    const original = Object.getOwnPropertyDescriptor(document, 'visibilityState');
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => 'hidden',
    });
    try {
      const runFn = vi.fn();
      const ok = maybeAutoFetchStale24h({
        isApiAvailable: () => true,
        inFlightCount: () => 0,
        now: Date.now(),
        getLastRun: () => 0,
        setLastRun: vi.fn(),
        sources,
        fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
        fetcherCredentialsSatisfied: () => true,
        stateFor: () => null,
        authCooldownRemainingMs: () => 0,
        isFetcherDisconnected: () => false,
        isFetcherReconnectRequired: () => false,
        runFn,
      });
      expect(ok).toBe(true);
      expect(runFn).toHaveBeenCalledTimes(1);
      expect(runFn.mock.calls[0][1]).toEqual({ auto: true });
    } finally {
      if (original) Object.defineProperty(document, 'visibilityState', original);
    }
  });

  it('excludes itad and pure enrichers', () => {
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources: [
        { key: 'hltb', label: 'HLTB', group: 'enrich', metaKey: 'hltb', missingRequirements: [] },
        { key: 'itad', label: 'ITAD', group: 'deals', metaKey: 'itad', missingRequirements: [] },
      ],
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips when API is unavailable', () => {
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => false,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips fresh fetchers', () => {
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS - 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips disconnected and reconnect-required stores', () => {
    const runFn = vi.fn();
    const disconnected = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => true,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(disconnected).toBe(false);

    const reconnect = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => true,
      runFn,
    });
    expect(reconnect).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips fetchers on auth cooldown or already in flight', () => {
    const runFn = vi.fn();
    const cooldown = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => null,
      authCooldownRemainingMs: () => 60_000,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(cooldown).toBe(false);

    const inFlight = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources,
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => true,
      stateFor: () => ({ status: 'running' }),
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(inFlight).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('skips stores with missing credentials', () => {
    const runFn = vi.fn();
    const ok = maybeAutoFetchStale24h({
      isApiAvailable: () => true,
      inFlightCount: () => 0,
      now: Date.now(),
      getLastRun: () => 0,
      sources: [
        {
          key: 'steam',
          label: 'Steam',
          group: 'library',
          metaKey: 'steam',
          missingRequirements: ['api_key'],
        },
      ],
      fetcherFreshness: () => ({ ageMs: AUTO_STALE_AGE_MS + 1 }),
      fetcherCredentialsSatisfied: () => false,
      stateFor: () => null,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      isFetcherReconnectRequired: () => false,
      runFn,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });
});
