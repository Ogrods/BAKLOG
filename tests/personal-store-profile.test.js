/**
 * Profile switch must flush personal data before the active profile changes on the server.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('personalStore.prepareForProfileSwitch', () => {
  beforeEach(() => {
    vi.resetModules();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  async function loadStore() {
    const { personalStore } = await import('../js/personal-store.js');
    const { state } = await import('../js/state.js');
    state.personal = { game1: { status: 'backlog' } };
    state.prefs = { activeView: 'library' };
    return { personalStore, state };
  }

  it('PUTs current snapshot before profile switch proceeds', async () => {
    const puts = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, opts) => {
        if (url === '/api/personal' && opts?.method === 'GET') {
          return {
            ok: true,
            json: async () => ({
              personal: { game1: { status: 'backlog' } },
              prefs: {},
              manual: [],
            }),
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

    const { personalStore, state } = await loadStore();
    await personalStore.init();
    state.personal = { game1: { status: 'playing' } };
    personalStore.notify();
    await personalStore.flush();
    await personalStore.prepareForProfileSwitch();
    expect(puts.length).toBeGreaterThanOrEqual(1);
    const playingPut = puts.find((p) => p.personal?.game1?.status === 'playing');
    expect(playingPut).toBeTruthy();
    expect(playingPut.profile).toBe('default');
  });

  it('PUT body omits profile claim in account auth mode', async () => {
    vi.resetModules();
    vi.doMock('../js/auth-gate.js', () => ({
      isAccountAuthMode: () => true,
      isLocalProfilesEnabled: () => false,
      getAccessToken: () => 'tok',
      whenAuthReady: () => Promise.resolve(),
      refreshAccessToken: async () => null,
      handleApiUnauthorized: () => {},
    }));
    localStorage.setItem('baklog-active-profile', 'work');
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

    const { personalStore, state } = await loadStore();
    state.personal = { game1: { status: 'backlog' } };
    await personalStore.init();
    personalStore.notify();
    await personalStore.flush();
    expect(puts.length).toBeGreaterThanOrEqual(1);
    expect(puts[puts.length - 1].profile).toBeUndefined();
  });

  it('PUT body keeps profile claim in account auth + local profiles hybrid mode', async () => {
    vi.resetModules();
    vi.doMock('../js/auth-gate.js', () => ({
      isAccountAuthMode: () => true,
      isLocalProfilesEnabled: () => true,
      getAccessToken: () => 'tok',
      whenAuthReady: () => Promise.resolve(),
      refreshAccessToken: async () => null,
      handleApiUnauthorized: () => {},
    }));
    localStorage.setItem('baklog-active-profile', 'work');
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

    const { personalStore, state } = await loadStore();
    state.personal = { game1: { status: 'backlog' } };
    await personalStore.init();
    personalStore.notify();
    await personalStore.flush();
    expect(puts.length).toBeGreaterThanOrEqual(1);
    expect(puts[puts.length - 1].profile).toBe('work');
  });

  it('409 profile mismatch keeps local edits for a later flush', async () => {
    let putCount = 0;
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
          putCount += 1;
          if (putCount === 1) {
            return { ok: false, status: 409, text: async () => 'profile mismatch' };
          }
          return {
            ok: true,
            json: async () => JSON.parse(opts.body),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    await personalStore.init();
    state.personal = { game1: { status: 'backlog' } };
    personalStore.notify();
    await personalStore.flush();

    state.personal = { game1: { status: 'playing' } };
    personalStore.notify();
    await personalStore.flush();

    expect(putCount).toBe(2);
  });
});
