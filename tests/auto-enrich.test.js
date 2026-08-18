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

  it('does nothing when pref is undefined (opt-in)', async () => {
    delete state.prefs.autoEnrichOnAdd;
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
      'steamReviews',
      'steamTags',
      'steamCovers',
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
    expect(runFn.mock.calls.map(c => c[0])).toEqual(['steamReviews', 'steamTags', 'steamCovers']);
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
    expect(runFn.mock.calls.map(c => c[0])).toEqual(['steamReviews', 'steamTags', 'steamCovers']);
    expect(appendLine).toHaveBeenCalledWith('[auto-enrich aborted: cancelled]', 'meta');
  });

  it('uses wired auth helpers when deps omit credential/cooldown/disconnect fns', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    const ok = await maybeAutoEnrichNewAdditions(2, {
      isApiAvailable: () => true,
      now: Date.now() + 60_000,
      runFn,
      waitForQueueSlot: async () => {},
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
    });
    expect(ok).toBe(true);
    expect(runFn).toHaveBeenCalled();
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
    state.itchGames = [];
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

  it('stamps itch games (state.itchGames) so itch adds are not invisible in recents', () => {
    recordLibraryFirstSeen();
    const itch = { store: 'itch', id: 'manual-zed', name: 'Zed', manual: true };
    state.itchGames = [itch];
    const n = recordLibraryFirstSeen();
    expect(n).toBe(1);
    expect(state.libraryFirstSeenByKey[gameKey(itch)]).toBeGreaterThan(0);
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

  it('stamps merge-diff keys during a re-seed when a pre-merge snapshot exists', async () => {
    const { captureLibraryKeysBeforeMerge } = await import('../js/library-load.js');
    recordLibraryFirstSeen();
    captureLibraryKeysBeforeMerge();
    state.libraryFirstSeenByKey = {};
    state.allGames.push({ store: 'nintendo', id: 'new-1', name: 'Fresh Switch Game' });
    const n = recordLibraryFirstSeen();
    expect(n).toBe(1);
    expect(state.libraryFirstSeenByKey['nintendo:new-1']).toBeGreaterThan(0);
    expect(state.libraryFirstSeenByKey[gameKey(state.allGames[0])]).toBe(0);
  });

  it('baselines a first Steam import instead of flooding recents', () => {
    recordLibraryFirstSeen();
    state._libraryKeysBeforeMerge = new Set();
    const bulk = [];
    for (let i = 0; i < 20; i++) {
      bulk.push({ store: 'steam', id: String(400 + i), name: `Game ${i}` });
    }
    state.allGames = bulk;
    const n = recordLibraryFirstSeen();
    expect(n).toBe(0);
    expect(state.libraryFirstSeenByKey['steam:400']).toBe(0);
    expect(state.libraryFirstSeenByKey['steam:419']).toBe(0);
  });

  it('still stamps a single game added after seed', () => {
    recordLibraryFirstSeen();
    state._libraryKeysBeforeMerge = new Set(state.allGames.map(g => gameKey(g)));
    state.allGames.push({ store: 'steam', id: '999', name: 'One New Game' });
    const n = recordLibraryFirstSeen();
    expect(n).toBe(1);
    expect(state.libraryFirstSeenByKey['steam:999']).toBeGreaterThan(0);
  });

  it('does not let a later capture hide a 10-game haul from enrich replay', async () => {
    const { captureLibraryKeysBeforeMerge } = await import('../js/library-load.js');
    state.allGames = [];
    for (let i = 0; i < 20; i++) {
      state.allGames.push({ store: 'steam', id: `old-${i}`, name: `Old ${i}` });
    }
    recordLibraryFirstSeen();
    captureLibraryKeysBeforeMerge();
    for (let i = 0; i < 10; i++) {
      state.allGames.push({ store: 'steam', id: `haul-${i}`, name: `Haul ${i}` });
    }
    captureLibraryKeysBeforeMerge();
    const n = recordLibraryFirstSeen();
    expect(n).toBe(10);
    expect(state.libraryFirstSeenByKey['steam:haul-0']).toBeGreaterThan(0);
    expect(state.libraryFirstSeenByKey['steam:haul-9']).toBeGreaterThan(0);
  });
});

describe('repairBulkFirstSeenStamps', () => {
  it('collapses persisted bulk-import batches to baseline', async () => {
    const { repairBulkFirstSeenStamps } = await import('../js/library-load.js');
    // Align to a second boundary so ts+i never spans two buckets (flaky when
    // Date.now() % 1000 is near 999).
    const ts = Date.now() - 3 * 60 * 60 * 1000;
    const base = ts - (ts % 1000);
    const map = {};
    for (let i = 0; i < 12; i++) map[`steam:${i}`] = base + i;
    expect(repairBulkFirstSeenStamps(map)).toBe(true);
    expect(map['steam:0']).toBe(0);
    expect(map['steam:11']).toBe(0);
  });

  it('leaves small batches alone', async () => {
    const { repairBulkFirstSeenStamps } = await import('../js/library-load.js');
    const ts = Date.now();
    const map = { 'steam:400': ts, 'steam:620': ts + 1 };
    expect(repairBulkFirstSeenStamps(map)).toBe(false);
    expect(map['steam:400']).toBe(ts);
  });

  it('leaves a same-second haul on an already-seeded library', async () => {
    const { repairBulkFirstSeenStamps } = await import('../js/library-load.js');
    const ts = Date.now() - 3 * 60 * 60 * 1000;
    const base = ts - (ts % 1000);
    const map = {};
    for (let i = 0; i < 2000; i++) map[`steam:old-${i}`] = 0;
    for (let i = 0; i < 10; i++) map[`steam:haul-${i}`] = base + i;
    expect(repairBulkFirstSeenStamps(map)).toBe(false);
    expect(map['steam:haul-0']).toBe(base);
    expect(map['steam:haul-9']).toBe(base + 9);
  });
});
