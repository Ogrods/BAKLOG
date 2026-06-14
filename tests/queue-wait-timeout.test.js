/**
 * Regression repro for "queue wait timeout" aborting the enrich chain so
 * steamReviews (3rd in ENRICH_ORDER) silently never runs.
 *
 * Beta report: wishlist view, lib:259, persisted unhandledrejection
 * "queue wait timeout" + "steam review enrichment didn't work".
 *
 * Root cause under test: waitForQueueSlot used a TOTAL wait cap
 * (WAIT_QUEUE_SLOT_MS). A legitimately long active run (a big library fetch or a
 * slow preceding enricher like Covers over hundreds of rows) keeps the single
 * server slot busy past the cap, so the next waitForQueueSlot rejects
 * "queue wait timeout" even though the run is alive and making progress. In the
 * enrich chain that rejection breaks the loop before steamReviews runs.
 *
 * Fix: the cap is a NO-PROGRESS timeout. While the active run keeps advancing
 * (new run id or growing line_count, surfaced via applyServerSnapshotInFlight),
 * the deadline resets; it only fires when the slot is genuinely wedged.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { fetcherRunner, maybeAutoEnrichNewAdditions } from '../js/fetcher-health.js';
import { state } from '../js/state.js';

vi.mock('../js/connections.js', () => ({
  FETCHER_AUTH_PROVIDER: { steam: 'steam' },
  isProviderConnected: vi.fn(() => true),
  noteFetcherAuthFailure: vi.fn(() => false),
  showReconnectBanner: vi.fn(),
  clearReconnectBanner: vi.fn(),
  authStatusLoaded: () => true,
  providerStatus: () => 'connected',
  ingestAuthStatusProviders: vi.fn(),
  groupRepFor: (key) => key,
}));

describe('waitForQueueSlot no-progress timeout (real timer behaviour)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    fetcherRunner.applyServerSnapshotInFlight({}); // clean slate
  });

  afterEach(() => {
    fetcherRunner.applyServerSnapshotInFlight({});
    vi.useRealTimers();
  });

  it('keeps waiting while the active run makes progress, then resolves when it frees', async () => {
    // A single Covers run holds the only slot for ~240s but emits heartbeat
    // lines (line_count grows) every 60s — well within the 120s window.
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'r1', key: 'steamCovers', status: 'running', line_count: 1 },
    });
    const waitP = fetcherRunner.waitForQueueSlot();
    const settled = waitP.then(() => 'resolved', (e) => `rejected:${e.message}`);

    for (let lc = 2; lc <= 5; lc += 1) {
      await vi.advanceTimersByTimeAsync(60_000);
      fetcherRunner.applyServerSnapshotInFlight({
        active: { id: 'r1', key: 'steamCovers', status: 'running', line_count: lc },
      });
    }
    // 240s elapsed, far past the 120s cap, but progress never stalled > window.
    fetcherRunner.applyServerSnapshotInFlight({}); // Covers finished, slot free
    await vi.advanceTimersByTimeAsync(300);

    expect(await settled).toBe('resolved');
  });

  it('still times out when the slot is wedged with no progress (safety net)', async () => {
    // Same active run, never advances (line_count frozen) — a genuinely wedged
    // queue should still surface the timeout so we never wait forever.
    fetcherRunner.applyServerSnapshotInFlight({
      active: { id: 'r1', key: 'steamCovers', status: 'running', line_count: 1 },
    });
    const waitP = fetcherRunner.waitForQueueSlot();
    const settled = waitP.then(() => 'resolved', (e) => `rejected:${e.message}`);

    await vi.advanceTimersByTimeAsync(125_000);

    expect(await settled).toBe('rejected:queue wait timeout');
  });

  it('resolves when the slot frees before the cap (control)', async () => {
    fetcherRunner.applyServerSnapshotInFlight({ active: { id: 'r2', key: 'steam', status: 'running', line_count: 1 } });
    const waitP = fetcherRunner.waitForQueueSlot();
    const settled = waitP.then(() => 'resolved', (e) => `rejected:${e.message}`);

    await vi.advanceTimersByTimeAsync(3_000);
    fetcherRunner.applyServerSnapshotInFlight({}); // run finished
    await vi.advanceTimersByTimeAsync(300);

    expect(await settled).toBe('resolved');
  });
});

describe('enrich chain reaction to a queue wait timeout', () => {
  const enrichSources = [
    { key: 'steamTags', label: 'Co-op tags', group: 'enrich', missingRequirements: [] },
    { key: 'steamCovers', label: 'Covers', group: 'enrich', missingRequirements: [] },
    { key: 'steamReviews', label: 'Reviews', group: 'enrich', missingRequirements: [] },
    { key: 'protondb', label: 'ProtonDB', group: 'enrich', missingRequirements: [] },
    { key: 'hltb', label: 'HLTB', group: 'enrich', missingRequirements: [] },
  ];

  beforeEach(() => {
    state.prefs = { autoEnrichOnAdd: true };
  });

  it('runs the full chain (incl. steamReviews) when slot waits resolve', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    await maybeAutoEnrichNewAdditions(3, {
      isApiAvailable: () => true,
      now: Date.now(),
      runFn,
      waitForQueueSlot: async () => {},
      getCancelEpoch: () => 0,
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
    });
    expect(runFn.mock.calls.map((c) => c[0])).toContain('steamReviews');
  });

  it('aborts steamReviews/protondb/hltb when the slot wait times out after Covers', async () => {
    const runFn = vi.fn().mockResolvedValue(undefined);
    let slotCalls = 0;
    const waitForQueueSlot = vi.fn().mockImplementation(() => {
      slotCalls += 1;
      if (slotCalls >= 3) return Promise.reject(new Error('queue wait timeout'));
      return Promise.resolve();
    });
    const appendLine = vi.fn();

    await maybeAutoEnrichNewAdditions(3, {
      isApiAvailable: () => true,
      now: Date.now() + 3_600_000,
      runFn,
      waitForQueueSlot,
      getCancelEpoch: () => 0,
      loadFetcherSources: async () => {},
      sources: enrichSources,
      stateFor: () => null,
      fetcherCredentialsSatisfied: () => true,
      authCooldownRemainingMs: () => 0,
      isFetcherDisconnected: () => false,
      appendLine,
    });

    const ran = runFn.mock.calls.map((c) => c[0]);
    expect(ran).toEqual(['steamTags', 'steamCovers']);
    expect(ran).not.toContain('steamReviews');
  });
});
