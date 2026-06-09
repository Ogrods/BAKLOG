/** Phase 4: propagation scenario matrix + instrumentation hook guards. */
import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { PROPAGATION_SCENARIOS } from '../js/propagation-scenarios.js';
import {
  noteFetcherReload,
  noteLibraryMerge,
  noteDownstreamSync,
  noteDeferredDefer,
  noteDeferredFlush,
  noteTableRender,
  readPropagationStats,
  resetPropagationStatsForTests,
  tracingEnabled,
} from '../js/propagation-trace.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, '..');

function fileContains(path, needle) {
  return readFileSync(join(ROOT, path), 'utf8').includes(needle);
}

describe('propagation scenario matrix', () => {
  it('defines 10 manual verification scenarios', () => {
    expect(PROPAGATION_SCENARIOS).toHaveLength(10);
    const ids = PROPAGATION_SCENARIOS.map((s) => s.id);
    expect(new Set(ids).size).toBe(10);
  });

  for (const scenario of PROPAGATION_SCENARIOS) {
    it(`${scenario.id}: hooks wired in source`, () => {
      for (const hook of scenario.hooks) {
        const found = [
          'js/propagation-trace.js',
          'js/library-load.js',
          'js/filters-ui.js',
          'js/render-gate.js',
          'js/table-ui.js',
          'js/personal-storage.js',
          'js/app.js',
          'fetchers/registry.py',
          'js/fetcher-registry.js',
        ].some((f) => fileContains(f, hook));
        expect(found, `missing hook needle "${hook}" for ${scenario.id}`).toBe(true);
      }
    });
  }
});

describe('propagation trace counters', () => {
  const origDebug = globalThis.localStorage;

  beforeEach(() => {
    localStorage.setItem('baklog-debug', '1');
    resetPropagationStatsForTests();
  });

  afterEach(() => {
    if (origDebug) localStorage.setItem('baklog-debug', '1');
    delete window.__baklogProp;
  });

  it('tracingEnabled follows baklog-debug flag', () => {
    expect(tracingEnabled()).toBe(true);
    localStorage.removeItem('baklog-debug');
    expect(tracingEnabled()).toBe(false);
    localStorage.setItem('baklog-debug', '1');
  });

  it('accumulates merge, fetcher, defer, flush, and sync counters', () => {
    noteFetcherReload('psn');
    noteLibraryMerge('psn');
    noteDeferredDefer();
    noteDeferredFlush({ table: true, picks: false, summary: false });
    noteTableRender();
    noteDownstreamSync();
    const p = readPropagationStats();
    expect(p.fetcherReloads).toBe(1);
    expect(p.merges).toBe(1);
    expect(p.deferredDefers).toBe(1);
    expect(p.deferredFlushes).toBe(1);
    expect(p.tableRenders).toBe(1);
    expect(p.downstreamSyncs).toBe(1);
    expect(p.lastFetcherKey).toBe('psn');
    expect(p.lastMergeKey).toBe('psn');
  });

  it('skips deferred flush counter when no flags set', () => {
    noteDeferredFlush({ table: false, picks: false, summary: false });
    expect(readPropagationStats().deferredFlushes).toBe(0);
  });
});

describe('bug bundle includes propagation stats', () => {
  it('error-boundary embeds __baklogProp snapshot', () => {
    const src = readFileSync(join(ROOT, 'js', 'error-boundary.js'), 'utf8');
    expect(src).toContain('propagation:');
    expect(src).toContain('__baklogProp');
  });
});
