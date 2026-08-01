/** cancelInFlightRuns — server-truth cancel + fallback. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

function installMockEventSource() {
  class MockEventSource {
    constructor() {
      this.close = vi.fn();
    }
    addEventListener() {}
  }
  global.EventSource = MockEventSource;
}

describe('cancelInFlightRuns server truth', () => {
  beforeEach(() => {
    vi.resetModules();
    // fetcher-health.js hydrates suppressed run ids from sessionStorage at module
    // init; without clearing, cancelled ids (e.g. r1) leak across tests and make
    // runBlocksQueueSlot() drop a still-active run, flaking isQueueFull() asserts.
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = '<div id="fetcherRunLog"></div>';
    installMockEventSource();
  });

  afterEach(() => {
    delete global.EventSource;
    vi.useRealTimers();
  });

  it('applyServerSnapshotInFlight tracks server queue without client chips', async () => {
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    fetcherRunner.applyServerSnapshotInFlight({
      active: null,
      queue: [{ id: 'abc', key: 'demo', status: 'queued' }],
      history: [],
    });
    expect(fetcherRunner.getLastServerInFlight()).toBe(true);
    fetcherRunner.applyServerSnapshotInFlight({ active: null, queue: [], history: [] });
    expect(fetcherRunner.getLastServerInFlight()).toBe(false);
  });

  it('does not treat cancelling runs as queue-blocking', async () => {
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'die-1', key: 'steam', status: 'cancelling', line_count: 40 },
      queue: [],
      history: [],
    });
    expect(fetcherRunner.getLastServerInFlight()).toBe(false);
    expect(fetcherRunner.isQueueFull()).toBe(false);
  });

  it('does not re-latch queue-full from suppressed runs after cancel', async () => {
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'gog',
              label: 'GOG',
              metaKey: 'gog',
              group: 'library',
              color: '#fff',
              cmd: 'fetch_gog.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({
            active: { id: 'die-2', key: 'gog', status: 'cancelling', line_count: 10 },
            queue: [{ id: 'q1', key: 'hltb', status: 'queued' }],
            history: [],
          }),
        };
      }
      if (u.includes('/api/runs/cancel') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            cancelled: [{ id: 'die-2', key: 'gog', status: 'cancelling' }],
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'die-2', key: 'gog', status: 'running', line_count: 10 },
      queue: [{ id: 'q1', key: 'hltb', status: 'queued' }],
      history: [],
    });
    expect(fetcherRunner.getLastServerInFlight()).toBe(true);
    await fetcherRunner.cancelInFlightRuns();
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'die-2', key: 'gog', status: 'cancelling', line_count: 10 },
      queue: [{ id: 'q1', key: 'hltb', status: 'queued' }],
      history: [],
    });
    expect(fetcherRunner.getLastServerInFlight()).toBe(false);
    expect(fetcherRunner.isQueueFull()).toBe(false);
  });

  it('waitForQueueSlot unblocks when the server snapshot only has a cancelling run', async () => {
    vi.useFakeTimers();
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'c1', key: 'steamCovers', status: 'cancelling', line_count: 99 },
      queue: [],
      history: [],
    });
    await expect(fetcherRunner.waitForQueueSlot()).resolves.toBeUndefined();
    vi.useRealTimers();
  });

  it('clears stale queue-full after a run ends on the client', async () => {
    const fetchMock = vi.fn(async (url) => {
      if (String(url).includes('/api/runs')) {
        return {
          ok: true,
          json: async () => ({ active: null, queue: [], history: [] }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'n1', key: 'nintendo', status: 'running' },
      queue: [],
      history: [],
    });
    fetcherRunner.markChipStateForTest('nintendo', 'running', 'n1');
    expect(fetcherRunner.isQueueFull()).toBe(true);
    fetcherRunner.markChipStateForTest('nintendo', null);
    await vi.waitFor(() => {
      expect(fetcherRunner.isQueueFull()).toBe(false);
    });
    expect(fetcherRunner.getLastServerInFlight()).toBe(false);
  });

  it('calls bulk cancel then per-run fallback when bulk fails', async () => {
    let runsPoll = 0;
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'demo',
              label: 'Demo',
              metaKey: 'demo',
              group: 'library',
              color: '#fff',
              cmd: 'fetch_demo.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs') && method === 'GET') {
        runsPoll += 1;
        if (runsPoll > 2) {
          return {
            ok: true,
            json: async () => ({
              active: null,
              queue: [],
              history: [{ id: 'q1', key: 'demo', status: 'cancelled' }],
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            active: null,
            queue: [{ id: 'q1', key: 'demo', status: 'queued', label: 'Demo' }],
            history: [],
          }),
        };
      }
      if (u.includes('/api/runs/cancel') && method === 'POST' && !u.includes('force=1')) {
        throw new Error('timeout');
      }
      if (u.includes('/api/runs/cancel') && method === 'POST') {
        return { ok: true, json: async () => ({ cancelled: [], force: true }) };
      }
      if (u.includes('/api/run/q1/cancel') && method === 'POST') {
        return { ok: true, json: async () => ({ status: 'cancelled' }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);

    await fetcherRunner.cancelInFlightRuns();
    await vi.waitFor(() => {
      const urls = fetchMock.mock.calls.map(c => String(c[0]));
      expect(urls.some(u => u.includes('/api/runs/cancel'))).toBe(true);
      expect(urls.some(u => u.includes('/api/run/q1/cancel'))).toBe(true);
    });
    const bulkCancels = fetchMock.mock.calls
      .map(c => String(c[0]))
      .filter(u => u.includes('/api/runs/cancel'));
    expect(bulkCancels.some(u => u.includes('lane=fetcher'))).toBe(true);
    expect(bulkCancels.some(u => u.includes('lane=enrich'))).toBe(true);
  });

  it('bumps cancel epoch when user cancels', async () => {
    let runsPoll = 0;
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'demo',
              label: 'Demo',
              metaKey: 'demo',
              group: 'library',
              color: '#fff',
              cmd: 'fetch_demo.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs') && method === 'GET') {
        runsPoll += 1;
        if (runsPoll > 2) {
          return {
            ok: true,
            json: async () => ({
              active: null,
              queue: [],
              history: [{ id: 'r1', key: 'demo', status: 'cancelled' }],
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            active: { id: 'r1', key: 'demo', status: 'running' },
            queue: [],
            history: [],
          }),
        };
      }
      if (u.includes('/api/runs/cancel') && method === 'POST') {
        return {
          ok: true,
          json: async () => ({
            cancelled: [{ id: 'r1', key: 'demo', status: 'cancelled' }],
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    const before = fetcherRunner.getCancelEpoch();
    await fetcherRunner.cancelInFlightRuns();
    expect(fetcherRunner.getCancelEpoch()).toBe(before + 1);
  });

  it('run() does not POST while cancelInFlight', async () => {
    const fetchMock = vi.fn(async url => {
      const u = String(url);
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'steamCovers',
              label: 'Covers',
              metaKey: 'steamCovers',
              group: 'enrich',
              color: '#ea580c',
              cmd: 'enrich_cross_store_images.py',
              available: true,
              supportsRefresh: true,
            }],
          }),
        };
      }
      if (u.includes('/api/run/')) {
        return { ok: true, status: 202, json: async () => ({ id: 'new-run' }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner, loadFetcherSources } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    await loadFetcherSources(true);
    fetcherRunner.setCancelInFlightForTest(true);
    await fetcherRunner.run('steamCovers');
    const runPosts = fetchMock.mock.calls.filter(
      c => String(c[0]).includes('/api/run/') && (c[1]?.method || 'GET').toUpperCase() === 'POST',
    );
    expect(runPosts).toHaveLength(0);
  });

  it('clears chips and cancelInFlight immediately when server is unreachable', async () => {
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'steamTags',
              label: 'Co-op tags',
              metaKey: 'steamTags',
              group: 'enrich',
              color: '#ea580c',
              cmd: 'enrich_steam_tags.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs/cancel') && method === 'POST') {
        throw new Error('server not responding');
      }
      if (u.includes('/api/runs') && method === 'GET') {
        throw new Error('server not responding');
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    fetcherRunner.markChipStateForTest('steamTags', 'running');
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'r1', key: 'steamTags', status: 'running' },
      queue: [],
    });
    fetcherRunner.expandPanel();
    const t0 = Date.now();
    await fetcherRunner.cancelInFlightRuns();
    expect(Date.now() - t0).toBeLessThan(2000);
    expect(fetcherRunner.isCancelInFlightForTest()).toBe(false);
    expect(fetcherRunner.getInFlightCountForTest()).toBe(0);
    expect(fetcherRunner.getLastServerInFlight()).toBe(false);
    const panel = document.getElementById('fetcherRunLog');
    const body = panel?.querySelector('[data-role="body"]');
    expect(body?.textContent || '').toMatch(/\[cancelled\]/);
    const btn = panel?.querySelector('[data-role="cancel"]');
    expect(btn?.classList.contains('hidden')).toBe(true);
  });

  it('409 on submit re-syncs and retries once when queue is idle', async () => {
    vi.useFakeTimers();
    let runPosts = 0;
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'steamCovers',
              label: 'Covers',
              metaKey: 'steamCovers',
              group: 'enrich',
              color: '#ea580c',
              cmd: 'enrich_cross_store_images.py',
              available: true,
              supportsRefresh: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({ active: null, queue: [], history: [] }),
        };
      }
      if (u.includes('/api/run/steamCovers') && method === 'POST') {
        runPosts += 1;
        if (runPosts === 1) {
          return { ok: false, status: 409, text: async () => 'queue settling' };
        }
        return { ok: true, status: 202, json: async () => ({ run_id: 'retry-run' }) };
      }
      if (u.includes('/api/auth/status')) {
        return { ok: true, json: async () => ({ providers: {} }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner, loadFetcherSources } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    await loadFetcherSources(true);
    const runPromise = fetcherRunner.run('steamCovers');
    await vi.advanceTimersByTimeAsync(700);
    await runPromise;
    const posts = fetchMock.mock.calls.filter(
      c => String(c[0]).includes('/api/run/steamCovers') && (c[1]?.method || 'GET').toUpperCase() === 'POST',
    );
    expect(posts).toHaveLength(2);
    vi.useRealTimers();
  });

  it('waitForQueueSlot polls /api/runs and unblocks when the fetcher lane frees', async () => {
    vi.useFakeTimers();
    // Unique id: other suites reuse 'r1'; a suppressed id leaked via sessionStorage
    // makes runBlocksQueueSlot() drop this run and flake isQueueFull().
    const RUN_ID = 'poll-unblock-run';
    let runsGets = 0;
    const fetchMock = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        runsGets += 1;
        const busy = runsGets < 2;
        return {
          ok: true,
          json: async () => ({
            active: busy ? { id: RUN_ID, key: 'steam', status: 'running' } : null,
            queue: [],
            history: [],
          }),
        };
      }
      if (u.includes('/api/fetchers')) {
        return { ok: true, json: async () => ({ fetchers: [] }) };
      }
      if (u.includes('/api/config')) {
        return { ok: true, json: async () => ({}) };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: RUN_ID, key: 'steam', status: 'running' },
      queue: [],
      history: [],
    });
    expect(fetcherRunner.isQueueFull()).toBe(true);
    const waitP = fetcherRunner.waitForQueueSlot();
    // WAIT_QUEUE_SNAPSHOT_POLL_MS is 2000; two polls: busy then idle.
    await vi.advanceTimersByTimeAsync(2500);
    await vi.advanceTimersByTimeAsync(2500);
    await waitP;
    expect(runsGets).toBeGreaterThanOrEqual(1);
    expect(fetcherRunner.isQueueFull()).toBe(false);
    vi.useRealTimers();
  });

  it('claims auto-run proceeds while an internal job holds the internal lane', async () => {
    let runPosts = 0;
    const fetchMock = vi.fn(async (url, init) => {
      const u = String(url);
      const method = (init?.method || 'GET').toUpperCase();
      if (u.includes('/api/fetchers')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [{
              key: 'claims',
              label: 'Free',
              metaKey: 'claims',
              group: 'prices',
              color: '#f97316',
              cmd: 'fetch_free_claims.py',
              available: true,
            }],
          }),
        };
      }
      if (u.includes('/api/runs') && method === 'GET') {
        return {
          ok: true,
          json: async () => ({
            active: null,
            queue: [],
            internal_active: { id: 'build-1', key: 'buildClaims', status: 'running' },
            internal_queue: [],
            history: [],
          }),
        };
      }
      if (u.includes('/api/run/claims') && method === 'POST') {
        runPosts += 1;
        return { ok: true, status: 202, json: async () => ({ run_id: 'claims-run' }) };
      }
      if (u.includes('/api/auth/status')) {
        return { ok: true, json: async () => ({ providers: {} }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner, loadFetcherSources } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    await loadFetcherSources(true);
    fetcherRunner.applyServerSnapshotInFlight({
      active: null,
      queue: [],
      internal_active: { id: 'build-1', key: 'buildClaims', status: 'running' },
      internal_queue: [],
      history: [],
    });
    expect(fetcherRunner.isQueueFull()).toBe(false);
    await fetcherRunner.run('claims', { auto: true });
    expect(runPosts).toBe(1);
  });
});

describe('Cancel button after finished runs', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
    sessionStorage.clear();
    document.body.innerHTML = '<div id="fetcherRunLog"></div>';
    installMockEventSource();
  });

  afterEach(() => {
    delete global.EventSource;
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function setupRunner(runsHandler) {
    const fetchMock = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs') && !u.includes('/cancel')) {
        return { ok: true, json: async () => runsHandler() };
      }
      if (u.includes('/api/fetchers') || u.includes('manifest.json')) {
        return {
          ok: true,
          json: async () => ({
            fetchers: [
              {
                key: 'steamCovers',
                label: 'Covers',
                group: 'enrich',
                metaKey: 'steamCovers',
                available: true,
                cmd: 'enrich_steam_covers.py',
              },
              {
                key: 'hltb',
                label: 'HLTB',
                group: 'enrich',
                metaKey: 'hltb',
                available: true,
                cmd: 'enrich_hltb.py',
              },
              {
                key: 'steam',
                label: 'Steam',
                group: 'library',
                metaKey: 'steam',
                available: true,
                cmd: 'fetch_steam.py',
              },
            ],
          }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    global.fetch = fetchMock;
    const { fetcherRunner, loadFetcherSources } = await import('../js/fetcher-health.js');
    await fetcherRunner.probeApi(true);
    await loadFetcherSources(true);
    return { fetcherRunner, fetchMock };
  }

  function cancelHidden(fetcherRunner) {
    fetcherRunner.ensurePanelForTest({ label: 'Covers', key: 'steamCovers' }, 'done');
    const btn = document.querySelector('[data-role="cancel"]');
    return !!btn?.classList.contains('hidden');
  }

  it('hides Cancel after steamCovers chip clears when server is idle', async () => {
    const idle = {
      active: null,
      queue: [],
      enrich_active: null,
      enrich_queue: [],
      history: [],
    };
    const { fetcherRunner } = await setupRunner(() => idle);
    fetcherRunner.ensurePanelForTest({ label: 'Covers', key: 'steamCovers' }, 'running');
    fetcherRunner.applyServerSnapshotInFlight({
      enrich_active: { id: 'cover-1', key: 'steamCovers', status: 'running' },
      enrich_queue: [],
      active: null,
      queue: [],
      history: [],
    });
    fetcherRunner.markChipStateForTest('steamCovers', 'running', 'cover-1');
    expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(false);

    fetcherRunner.markChipStateForTest('steamCovers', null);
    await vi.waitFor(() => {
      expect(fetcherRunner.getLastServerInFlight()).toBe(false);
      expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(true);
    });
  });

  it('force-refreshes idle snap so coalesced in-flight snap cannot re-latch Cancel', async () => {
    let runsCalls = 0;
    const { fetcherRunner } = await setupRunner(() => {
      runsCalls += 1;
      // First non-force call during the coalesce window would return stale
      // enrich_active; force:true after chip clear must get idle.
      if (runsCalls === 1) {
        return {
          active: null,
          queue: [],
          enrich_active: { id: 'cover-2', key: 'steamCovers', status: 'running', line_count: 3 },
          enrich_queue: [],
          history: [],
        };
      }
      return {
        active: null,
        queue: [],
        enrich_active: null,
        enrich_queue: [],
        history: [
          {
            id: 'cover-2',
            key: 'steamCovers',
            status: 'done',
            exit_code: 0,
            ended_at: Date.now() / 1000,
          },
        ],
      };
    });

    fetcherRunner.ensurePanelForTest({ label: 'Covers', key: 'steamCovers' }, 'running');
    // Seed coalesce cache with the stale in-flight snap (call 1).
    await fetcherRunner.syncFromServer();
    expect(fetcherRunner.stateFor('steamCovers')).toBe('running');
    expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(false);

    // Chip clear forces a fresh idle snap (call 2+), not the coalesced one.
    fetcherRunner.markChipStateForTest('steamCovers', null);
    await vi.waitFor(() => {
      expect(runsCalls).toBeGreaterThanOrEqual(2);
      expect(fetcherRunner.getLastServerInFlight()).toBe(false);
      expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(true);
    });
  });

  it('does not keep Cancel visible for failed-only chip state', async () => {
    const { fetcherRunner } = await setupRunner(() => ({
      active: null,
      queue: [],
      enrich_active: null,
      enrich_queue: [],
      history: [],
    }));
    fetcherRunner.applyServerSnapshotInFlight({});
    fetcherRunner.markChipStateForTest('hltb', 'failed');
    expect(fetcherRunner.cancellableCount()).toBe(0);
    expect(fetcherRunner.isQueueFull()).toBe(false);
    expect(cancelHidden(fetcherRunner)).toBe(true);
  });

  it('reconcile failed schedules clear so Cancel is not held indefinitely', async () => {
    vi.useFakeTimers();
    const { fetcherRunner } = await setupRunner(() => ({
      active: null,
      queue: [],
      enrich_active: null,
      enrich_queue: [],
      history: [],
    }));
    fetcherRunner.ensurePanelForTest({ label: 'HLTB', key: 'hltb' }, 'running');
    fetcherRunner.markChipStateForTest('hltb', 'running', 'hltb-fail-1');
    fetcherRunner.reconcileRunStateFromSnapshot({
      active: null,
      queue: [],
      enrich_active: null,
      enrich_queue: [],
      history: [
        {
          id: 'hltb-fail-1',
          key: 'hltb',
          status: 'failed',
          exit_code: 1,
          ended_at: Date.now() / 1000,
        },
      ],
    });
    expect(fetcherRunner.stateFor('hltb')).toBe('failed');
    expect(fetcherRunner.cancellableCount()).toBe(0);
    expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(true);

    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcherRunner.stateFor('hltb')).toBeNull();
    expect(fetcherRunner.isRunFailedForTest('hltb')).toBe(true);
  });

  it('syncFromServer reattaches enrich_active and clears Cancel when history says done', async () => {
    let phase = 'running';
    const { fetcherRunner } = await setupRunner(() => {
      if (phase === 'running') {
        return {
          active: null,
          queue: [],
          enrich_active: { id: 'cover-3', key: 'steamCovers', status: 'running', line_count: 2 },
          enrich_queue: [],
          history: [],
        };
      }
      return {
        active: null,
        queue: [],
        enrich_active: null,
        enrich_queue: [],
        history: [
          {
            id: 'cover-3',
            key: 'steamCovers',
            status: 'done',
            exit_code: 0,
            ended_at: Date.now() / 1000,
          },
        ],
      };
    });

    await fetcherRunner.syncFromServer();
    expect(fetcherRunner.stateFor('steamCovers')).toBe('running');
    expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(false);

    phase = 'done';
    // Let the /api/runs coalesce window expire so the next sync sees idle truth.
    await new Promise((r) => setTimeout(r, 1600));
    await fetcherRunner.syncFromServer();
    await vi.waitFor(() => {
      expect(fetcherRunner.stateFor('steamCovers')).toBeNull();
      expect(fetcherRunner.getLastServerInFlight()).toBe(false);
      expect(document.querySelector('[data-role="cancel"]')?.classList.contains('hidden')).toBe(true);
    });
  });
});
