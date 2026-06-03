/** cancelInFlightRuns — server-truth cancel + fallback. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('cancelInFlightRuns server truth', () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = '<div id="fetcherRunLog"></div>';
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
    const urls = fetchMock.mock.calls.map(c => String(c[0]));
    expect(urls.some(u => u.includes('/api/runs/cancel'))).toBe(true);
    expect(urls.some(u => u.includes('/api/run/q1/cancel'))).toBe(true);
  });
});
