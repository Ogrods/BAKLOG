/** Dev-only ?pro=1 override must stay on localhost. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('isDebugProEnabled host gate', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
  });

  async function loadAuthGate(url) {
    const win = new Window({ url });
    global.window = win;
    global.localStorage = win.localStorage;
    global.location = win.location;
    return import('../js/auth-gate.js');
  }

  it('allows localhost ?pro=1', async () => {
    const { isDebugProEnabled } = await loadAuthGate('http://127.0.0.1:8765/?pro=1');
    expect(isDebugProEnabled()).toBe(true);
  });

  it('blocks production host even with ?pro=1', async () => {
    const { isDebugProEnabled } = await loadAuthGate('https://baklog.app/?pro=1');
    expect(isDebugProEnabled()).toBe(false);
  });

  it('blocks localStorage override off localhost', async () => {
    const { isDebugProEnabled } = await loadAuthGate('https://baklog.app/');
    localStorage.setItem('baklog-debug-pro', '1');
    expect(isDebugProEnabled()).toBe(false);
  });
});
