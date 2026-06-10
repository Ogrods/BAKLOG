/**
 * Tests for js/anon-metrics.js — opt-in aggregate metrics batching.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  __resetMetricsForTest,
  flushMetrics,
  isMetricsEnabled,
  noteSponsoredImpression,
  recordMetric,
  recordSponsoredClick,
  startMetrics,
  stopMetrics,
  METRICS_ENDPOINT,
} from '../js/anon-metrics.js';
import { state } from '../js/state.js';

beforeEach(() => {
  state.prefs = { shareAnonStats: false };
  state.sponsoredDeals = [];
  __resetMetricsForTest();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
});

afterEach(() => {
  __resetMetricsForTest();
  vi.unstubAllGlobals();
});

describe('isMetricsEnabled', () => {
  it('is false unless shareAnonStats is explicitly true', () => {
    expect(isMetricsEnabled()).toBe(false);
    state.prefs.shareAnonStats = true;
    expect(isMetricsEnabled()).toBe(true);
  });
});

describe('recordMetric', () => {
  it('no-ops when disabled', async () => {
    recordMetric('session_start');
    await flushMetrics();
    expect(fetch).not.toHaveBeenCalled();
  });

  it('batches events and POSTs on flush when enabled', async () => {
    state.prefs.shareAnonStats = true;
    recordMetric('session_start');
    recordMetric('impression', { placement: 'picks', sponsorId: 'ad1' });
    await flushMetrics();
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, opts] = fetch.mock.calls[0];
    expect(url).toBe(METRICS_ENDPOINT);
    const body = JSON.parse(opts.body);
    expect(body.bundle).toBe('baklog-metrics');
    expect(body.session_id).toBeTruthy();
    expect(body.events).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: 'session_start', n: 1 }),
      expect.objectContaining({ type: 'impression', placement: 'picks', sponsor_id: 'ad1', n: 1 }),
    ]));
  });
});

describe('noteSponsoredImpression', () => {
  it('dedupes impressions per placement+sponsor per session', async () => {
    state.prefs.shareAnonStats = true;
    noteSponsoredImpression('table', 'ad1');
    noteSponsoredImpression('table', 'ad1');
    await flushMetrics();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    const imp = body.events.find(e => e.type === 'impression');
    expect(imp?.n).toBe(1);
  });
});

describe('recordSponsoredClick', () => {
  it('records click with placement from feed item', async () => {
    state.prefs.shareAnonStats = true;
    state.sponsoredAds = { ad1: { title: 'Game', kind: 'sponsor' } };
    state.adLocations = { 'claim-cards': ['ad1'] };
    state.sponsoredDeals = [{ id: 'ad1', title: 'Game' }];
    recordSponsoredClick('ad1');
    await flushMetrics();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.events).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: 'click', placement: 'claim-cards', sponsor_id: 'ad1', n: 1 }),
    ]));
  });
});

describe('startMetrics / stopMetrics', () => {
  it('emits session_start on start and clears on stop', async () => {
    state.prefs.shareAnonStats = true;
    startMetrics();
    await flushMetrics();
    expect(fetch).toHaveBeenCalled();
    const firstBody = JSON.parse(fetch.mock.calls[0][1].body);
    expect(firstBody.events).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: 'session_start', n: 1 }),
    ]));
    fetch.mockClear();
    stopMetrics();
    await flushMetrics();
    expect(fetch).not.toHaveBeenCalled();
  });
});
