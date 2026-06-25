/**
 * Boot curtain min-visible timing contract.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

describe('loading curtain perf', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.documentElement.setAttribute('data-boot-loading', 'library');
    document.body.innerHTML = `
      <div id="bootLoadingOverlay" aria-busy="true"></div>
      <div id="tableShell"><table><tbody id="tbody"></tbody></table></div>`;
    vi.stubGlobal('requestAnimationFrame', (cb) => {
      cb();
      return 0;
    });
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  });

  afterEach(() => {
    document.documentElement.removeAttribute('data-boot-loading');
    document.body.innerHTML = '';
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('holds boot curtain at least 150ms when bootstrap was fast', async () => {
    const { liftBootCurtain } = await import('../js/loading-curtain.js');
    const startedAt = performance.now();
    liftBootCurtain(startedAt);
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(true);
    vi.advanceTimersByTime(149);
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(true);
    vi.advanceTimersByTime(2);
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(false);
  });

  it('lifts immediately when force option is set', async () => {
    const { liftBootCurtain } = await import('../js/loading-curtain.js');
    liftBootCurtain(0, { force: true });
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(false);
  });
});

describe('boot-perf instrumentation', () => {
  beforeEach(() => {
    localStorage.setItem('baklog-perf', '1');
    delete window.__baklogBootPerf;
  });

  afterEach(() => {
    localStorage.removeItem('baklog-perf');
    delete window.__baklogBootPerf;
  });

  it('records marks and totalMs', async () => {
    const { bootPerfBegin, bootPerfMark, bootPerfEnd } = await import('../js/boot-perf.js');
    const run = bootPerfBegin();
    expect(run).not.toBeNull();
    bootPerfMark(run, 'auth:done');
    bootPerfMark(run, 'curtain:lift');
    bootPerfEnd(run);
    expect(window.__baklogBootPerf.last.totalMs).toBeGreaterThanOrEqual(0);
    expect(window.__baklogBootPerf.last.marks['auth:done']).toBeDefined();
  });
});
