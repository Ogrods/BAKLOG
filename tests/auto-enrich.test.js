/** maybeAutoEnrichNewAdditions — queue enrichers after library adds. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('maybeAutoEnrichNewAdditions', () => {
  let state;
  let maybeAutoEnrichNewAdditions;

  const enrichSources = [
    { key: 'steamTags', label: 'Co-op tags', group: 'enrich', missingRequirements: [] },
    { key: 'steamCovers', label: 'Covers', group: 'enrich', missingRequirements: [] },
    { key: 'steamReviews', label: 'Reviews', group: 'enrich', missingRequirements: ['STEAM_API_KEY'] },
    { key: 'hltb', label: 'HLTB', group: 'enrich', missingRequirements: [] },
  ];

  beforeEach(async () => {
    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ maybeAutoEnrichNewAdditions } = await import('../js/fetcher-health.js'));
    state.prefs = { autoEnrichOnAdd: true };
  });

  it('does nothing when pref is off', async () => {
    state.prefs.autoEnrichOnAdd = false;
    const runFn = vi.fn();
    const ok = await maybeAutoEnrichNewAdditions(5, {
      isApiAvailable: () => true,
      runFn,
      loadFetcherSources: async () => {},
      sources: enrichSources,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('does nothing when newCount is zero', async () => {
    const runFn = vi.fn();
    const ok = await maybeAutoEnrichNewAdditions(0, {
      isApiAvailable: () => true,
      runFn,
      loadFetcherSources: async () => {},
      sources: enrichSources,
    });
    expect(ok).toBe(false);
    expect(runFn).not.toHaveBeenCalled();
  });

  it('queues runnable enrichers in ENRICH_ORDER', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    const waitForQueueSlot = vi.fn().mockResolvedValue(undefined);
    const ok = await maybeAutoEnrichNewAdditions(3, {
      isApiAvailable: () => true,
      now: Date.now() + 10_000,
      runFn,
      waitForQueueSlot,
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
    });
    expect(ok).toBe(true);
    expect(runFn.mock.calls.map(c => c[0])).toEqual([
      'steamTags',
      'steamCovers',
      'steamReviews',
      'hltb',
    ]);
    expect(runFn.mock.calls.every(c => c[1]?.auto === true)).toBe(true);
    expect(waitForQueueSlot).toHaveBeenCalledTimes(4);
  });

  it('skips enrichers missing credentials', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    await maybeAutoEnrichNewAdditions(2, {
      isApiAvailable: () => true,
      now: Date.now() + 20_000,
      runFn,
      waitForQueueSlot: async () => {},
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: key => key !== 'steamReviews',
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
    });
    expect(runFn.mock.calls.map(c => c[0])).toEqual(['steamTags', 'steamCovers', 'hltb']);
  });

  it('skips enrichers already running', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    await maybeAutoEnrichNewAdditions(1, {
      isApiAvailable: () => true,
      now: Date.now() + 30_000,
      runFn,
      waitForQueueSlot: async () => {},
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: key => (key === 'hltb' ? 'running' : null),
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
    });
    expect(runFn.mock.calls.map(c => c[0])).toEqual(['steamTags', 'steamCovers', 'steamReviews']);
  });

  it('stops queuing remaining enrichers after cancel epoch bumps mid-batch', async () => {
    let epoch = 0;
    const getCancelEpoch = () => epoch;
    const runFn = vi.fn().mockImplementation(async key => {
      if (key === 'steamCovers') epoch = 1;
    });
    const appendLine = vi.fn();
    await maybeAutoEnrichNewAdditions(3, {
      isApiAvailable: () => true,
      now: Date.now() + 40_000,
      runFn,
      getCancelEpoch,
      waitForQueueSlot: async () => {},
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      appendLine,
    });
    expect(runFn.mock.calls.map(c => c[0])).toEqual(['steamTags', 'steamCovers']);
    expect(appendLine).toHaveBeenCalledWith('[auto-enrich aborted: cancelled]', 'meta');
  });

  it('stops when waitForQueueSlot rejects cancelled', async () => {
    const runFn = vi.fn();
    await maybeAutoEnrichNewAdditions(1, {
      isApiAvailable: () => true,
      now: Date.now() + 50_000,
      runFn,
      waitForQueueSlot: () => Promise.reject(new Error('cancelled')),
      getCancelEpoch: () => 0,
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
    });
    expect(runFn).not.toHaveBeenCalled();
  });
});

describe('recordLibraryFirstSeen', () => {
  let state;
  let recordLibraryFirstSeen;
  let gameKey;
  let notifySpy;

  beforeEach(async () => {
    vi.resetModules();
    const ps = await import('../js/personal-store.js');
    notifySpy = vi.spyOn(ps.personalStore, 'notify').mockImplementation(() => {});
    ({ state } = await import('../js/state.js'));
    ({ recordLibraryFirstSeen } = await import('../js/library-load.js'));
    ({ gameKey } = await import('../js/game-core.js'));
    state.prefs = { librarySeenSeeded: false };
    state.libraryFirstSeenByKey = {};
    state.allGames = [
      { store: 'steam', id: '1', name: 'A' },
      { store: 'steam', id: '2', name: 'B' },
    ];
  });

  it('returns 0 on first seed (existing library)', () => {
    const n = recordLibraryFirstSeen();
    expect(n).toBe(0);
    expect(state.prefs.librarySeenSeeded).toBe(true);
    expect(state.libraryFirstSeenByKey[gameKey(state.allGames[0])]).toBe(0);
  });

  it('returns count of newly stamped keys after seed', () => {
    recordLibraryFirstSeen();
    state.allGames.push({ store: 'gog', id: '9', name: 'New' });
    const n = recordLibraryFirstSeen();
    expect(n).toBe(1);
    expect(state.libraryFirstSeenByKey[gameKey({ store: 'gog', id: '9', name: 'New' })]).toBeGreaterThan(0);
  });

  it('re-seeds as baseline when the map is empty but seeded flag is true (desync)', () => {
    // Simulates the server-doc-reset / migration path where applyServerDoc never
    // populated the in-memory map but prefs.librarySeenSeeded persisted as true.
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    const n = recordLibraryFirstSeen();
    expect(n).toBe(0);
    expect(state.libraryFirstSeenByKey[gameKey(state.allGames[0])]).toBe(0);
    expect(state.libraryFirstSeenByKey[gameKey(state.allGames[1])]).toBe(0);
  });
});
