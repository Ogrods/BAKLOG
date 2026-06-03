/**
 * Profile switch must flush personal data before the active profile changes on the server.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { state } from '../js/state.js';

describe('personalStore.prepareForProfileSwitch', () => {
  beforeEach(() => {
    localStorage.clear();
    state.personal = { game1: { status: 'backlog' } };
    state.prefs = { activeView: 'library' };
    vi.restoreAllMocks();
  });

  it('PUTs current snapshot before profile switch proceeds', async () => {
    const puts = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, opts) => {
        if (url === '/api/personal' && opts?.method === 'GET') {
          return {
            ok: true,
            json: async () => ({ personal: {}, prefs: {}, manual: [] }),
          };
        }
        if (url === '/api/personal' && opts?.method === 'PUT') {
          puts.push(JSON.parse(opts.body));
          return {
            ok: true,
            json: async () => JSON.parse(opts.body),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore } = await import('../js/personal-store.js');
    await personalStore.init();
    state.personal = { game1: { status: 'playing' } };
    personalStore.notify();
    await personalStore.prepareForProfileSwitch();
    expect(puts.length).toBeGreaterThanOrEqual(1);
    expect(puts[puts.length - 1].personal.game1.status).toBe('playing');
  });
});
