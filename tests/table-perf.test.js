/**
 * Tests for js/table-perf.js — render instrumentation lifecycle.
 */

import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import {
  isTablePerfEnabled,
  perfBeginRun,
  perfMark,
  perfMeasure,
  perfChunk,
  perfEndRun,
  perfActiveRun,
} from '../js/table-perf.js';

const PERF_KEY = 'baklog-perf';

beforeEach(() => {
  localStorage.setItem(PERF_KEY, '1');
  window.__baklogPerfForce = false;
  delete window.__baklogPerf;
});

afterEach(() => {
  localStorage.removeItem(PERF_KEY);
  delete window.__baklogPerfForce;
  delete window.__baklogPerf;
});

describe('isTablePerfEnabled', () => {
  it('is true when localStorage flag is set', () => {
    expect(isTablePerfEnabled()).toBe(true);
  });

  it('is false when storage flag is cleared', () => {
    localStorage.removeItem(PERF_KEY);
    expect(isTablePerfEnabled()).toBe(false);
    localStorage.setItem(PERF_KEY, '1');
  });
});

describe('perf run lifecycle', () => {
  it('accumulates marks, measures, and chunks then clears active run', () => {
    const run = perfBeginRun({ view: 'library', rowCount: 100 });
    expect(run).not.toBeNull();
    expect(perfActiveRun()).toBe(run);

    perfMark(run, 'query:start');
    perfMark(run, 'query:end');
    perfMeasure(run, 'query', 'query:start', { rows: 50 });

    perfChunk(run, {
      start: 0,
      end: 25,
      count: 25,
      mode: 'progressive',
      htmlMs: 12,
      syncCoverMs: 3,
      totalMs: 15,
    });

    perfEndRun(run);
    expect(run.totalMs).toBeGreaterThanOrEqual(0);
    expect(run.measures).toHaveLength(1);
    expect(run.chunks).toHaveLength(1);
    expect(perfActiveRun()).toBeNull();
    expect(window.__baklogPerf?.last).toBe(run);
  });

  it('no-ops when perf disabled', () => {
    localStorage.removeItem(PERF_KEY);
    const run = perfBeginRun({ view: 'library' });
    expect(run).toBeNull();
    perfMark(null, 'x');
    perfMeasure(null, 'x', 'run:start');
    perfChunk(null, {});
    perfEndRun(null);
    expect(perfActiveRun()).toBeNull();
  });
});
