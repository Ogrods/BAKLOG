import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createRunConsole } from '../admin/run-console.js';

function mountConsoleDom() {
  document.body.innerHTML = `
    <div id="runConsole" class="run-console hidden">
      <strong id="runConsoleTitle"></strong>
      <span id="runConsoleStatus"></span>
      <div id="runHistory" hidden></div>
      <div id="runConsoleBody"></div>
      <button type="button" id="runConsoleJump" hidden></button>
      <button type="button" id="runCancelBtn" hidden>Cancel</button>
      <button type="button" id="runConsoleClear"></button>
      <button type="button" id="runConsoleCollapse"></button>
      <button type="button" id="runHistoryToggle"></button>
    </div>
  `;
}

function installMockEventSource({ fireOnClose = true } = {}) {
  class MockEventSource {
    constructor(url) {
      this.url = url;
      this.onerror = null;
      this.readyState = 2;
      this._handlers = {};
      MockEventSource.last = this;
      this.close = vi.fn(() => {
        if (fireOnClose && this.onerror) this.onerror(new Event('error'));
      });
    }
    addEventListener(type, fn) {
      this._handlers[type] = fn;
    }
  }
  MockEventSource.last = null;
  global.EventSource = MockEventSource;
  return MockEventSource;
}

describe('createRunConsole local lifecycle', () => {
  beforeEach(() => {
    mountConsoleDom();
    vi.useFakeTimers();
  });

  afterEach(() => {
    delete global.EventSource;
    vi.useRealTimers();
  });

  it('beginLocal exposes cancel, aborts fetch signal, and endLocal clears running state', async () => {
    const adminFetch = vi.fn().mockResolvedValue({ items: [] });
    const consoleApi = createRunConsole({
      adminFetch,
      streamUrl: async () => '/api/stream/test',
    });

    const signal = consoleApi.beginLocal('Enrich in place');
    expect(signal.aborted).toBe(false);
    expect(document.getElementById('runCancelBtn').hidden).toBe(false);

    vi.advanceTimersByTime(5000);
    expect(document.getElementById('runConsoleBody').textContent).toMatch(/still working/);

    await consoleApi.cancel();
    expect(signal.aborted).toBe(true);

    consoleApi.endLocal('cancelled');
    expect(document.getElementById('runConsoleStatus').textContent).toMatch(/cancelled/);
    expect(document.getElementById('runCancelBtn').hidden).toBe(true);
  });
});

describe('createRunConsole SSE reconnect', () => {
  beforeEach(() => {
    mountConsoleDom();
    vi.useFakeTimers();
  });

  afterEach(() => {
    delete global.EventSource;
    vi.useRealTimers();
  });

  it('does not schedule duplicate reconnects when close() re-fires onerror', async () => {
    vi.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => {
      cb(0);
      return 0;
    });
    const MockES = installMockEventSource({ fireOnClose: true });
    const adminFetch = vi.fn().mockResolvedValue({ history: [] });
    const consoleApi = createRunConsole({
      adminFetch,
      streamUrl: async () => '/api/stream/test-run',
    });

    void consoleApi.subscribe('test-run', 'Fetch claim sources');
    await Promise.resolve();

    const es = MockES.last;
    expect(es).toBeTruthy();

    es.onerror(new Event('error'));
    const body = document.getElementById('runConsoleBody');
    const droppedLines = (body.textContent.match(/stream dropped/g) || []).length;
    expect(droppedLines).toBe(1);
  });
});
