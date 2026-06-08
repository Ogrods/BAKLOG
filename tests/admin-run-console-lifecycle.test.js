import { beforeEach, describe, expect, it, vi } from 'vitest';
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

describe('createRunConsole local lifecycle', () => {
  beforeEach(() => {
    mountConsoleDom();
    vi.useFakeTimers();
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
