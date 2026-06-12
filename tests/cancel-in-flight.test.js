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
    document.body.innerHTML = '<div id="fetcherRunLog"></div>';
    installMockEventSource();
  });

  afterEach(() => {
    delete global.EventSource;
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
    expect(bulkCancels.every(u => u.includes('lane=fetcher'))).toBe(true);
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
    let runsGets = 0;
    const fetchMock = vi.fn(async (url) => {
      const u = String(url);
      if (u.includes('/api/runs')) {
        runsGets += 1;
        const busy = runsGets < 2;
        return {
          ok: true,
          json: async () => ({
            active: busy ? { id: 'r1', key: 'steam', status: 'running' } : null,
            queue: [],
            history: [],
          }),
        };
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
      active: { id: 'r1', key: 'steam', status: 'running' },
      queue: [],
      history: [],
    });
    expect(fetcherRunner.isQueueFull()).toBe(true);
    await fetcherRunner.waitForQueueSlot();
    expect(runsGets).toBeGreaterThanOrEqual(1);
    expect(fetcherRunner.isQueueFull()).toBe(false);
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
