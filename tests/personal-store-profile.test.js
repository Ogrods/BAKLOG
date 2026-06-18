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
      getAccountProfileId: () => '',
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
    state.personal = { game1: { status: 'backlog' } };
    await personalStore.init();
    state.personal = { game1: { status: 'playing' } };
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
      getAccountProfileId: () => '',
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
    state.personal = { game1: { status: 'backlog' } };
    await personalStore.init();
    state.personal = { game1: { status: 'playing' } };
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
            json: async () => ({
              personal: { game1: { status: 'backlog' } },
              prefs: {},
              manual: [],
            }),
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
    state.personal = { game1: { status: 'backlog' } };
    await personalStore.init();
    state.personal = { game1: { status: 'next' } };
    personalStore.notify();
    await personalStore.flush();

    state.personal = { game1: { status: 'playing' } };
    personalStore.notify();
    await personalStore.flush();

    expect(putCount).toBe(2);
  });

  it('merges cached libraryFirstSeen with server doc and writes cache to localStorage', async () => {
    const { libraryFirstSeenStorageKey } = await import('../js/profiles.js');
    localStorage.setItem(
      libraryFirstSeenStorageKey(),
      JSON.stringify({ 'steam:1': 1000, 'steam:2': 2000 }),
    );

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
              libraryFirstSeen: { 'steam:2': 5000, 'steam:3': 3000 },
            }),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    await personalStore.init();

    expect(state.libraryFirstSeenByKey).toEqual({
      'steam:1': 1000,
      'steam:2': 5000,
      'steam:3': 3000,
    });
    expect(JSON.parse(localStorage.getItem(libraryFirstSeenStorageKey()))).toEqual({
      'steam:1': 1000,
      'steam:2': 5000,
      'steam:3': 3000,
    });
  });

  it('keeps local rowHeroBackdrop over stale server false on init', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (url === '/api/personal') {
          return {
            ok: true,
            json: async () => ({
              personal: { game1: { status: 'backlog' } },
              prefs: { rowHeroBackdrop: false },
              manual: [],
            }),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    state.prefs = {
      activeView: 'library',
      rowHeroBackdrop: true,
      rowHeroBackdropDefaulted: true,
    };
    await personalStore.init();
    expect(state.prefs.rowHeroBackdrop).toBe(true);
    expect(state.prefs.rowHeroBackdropDefaulted).toBe(true);
  });

  it('treats libraryFirstSeen-only server doc as meaningful (applies without migration)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (url === '/api/personal') {
          return {
            ok: true,
            json: async () => ({
              personal: {},
              prefs: {},
              manual: [],
              libraryFirstSeen: { 'steam:9': 9000 },
            }),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    state.personal = {};
    const result = await personalStore.init();
    expect(result.pendingMigration).toBeNull();
    expect(result.migrated).toBe(true);
    expect(state.libraryFirstSeenByKey).toEqual({ 'steam:9': 9000 });
  });

  it('unions local + server claim dismissals on init instead of letting server win', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url, opts) => {
        if (url === '/api/personal' && opts?.method === 'GET') {
          return {
            ok: true,
            json: async () => ({
              personal: {
                __dismissedClaims: { 'epic-foo': 1000, 'shared': 1000 },
                __dismissedClaimKeys: { 'title:foo': 1000 },
              },
              prefs: {},
              manual: [],
            }),
          };
        }
        if (url === '/api/personal' && opts?.method === 'PUT') {
          return { ok: true, json: async () => JSON.parse(opts.body) };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    // Local dismissals saved after the last server PUT (e.g. cleared this session).
    state.personal = {
      __dismissedClaims: { 'gog-bar': 2000, 'shared': 3000 },
      __dismissedClaimKeys: { 'title:bar': 2000 },
    };
    await personalStore.init();

    expect(state.personal.__dismissedClaims).toEqual({
      'epic-foo': 1000,
      'gog-bar': 2000,
      // Shared key keeps the newer timestamp from local.
      'shared': 3000,
    });
    expect(state.personal.__dismissedClaimKeys).toEqual({
      'title:foo': 1000,
      'title:bar': 2000,
    });
  });

  it('PUTs merged dismissals to server when boot union grows dismissal maps', async () => {
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
          return { ok: true, json: async () => JSON.parse(opts.body) };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    state.personal = {
      game1: { status: 'backlog' },
      __dismissedClaims: { 'gog-bar': 2000 },
      __dismissedClaimKeys: { 'title:bar': 2000 },
    };
    await personalStore.init();
    await personalStore.flush();

    expect(puts.length).toBeGreaterThan(0);
    expect(puts[0].personal.__dismissedClaims).toEqual({ 'gog-bar': 2000 });
    expect(puts[0].personal.__dismissedClaimKeys).toEqual({ 'title:bar': 2000 });
  });

  it('keeps exclude_from_count-only records through server merge', async () => {
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
        return { ok: false, status: 500, text: async () => '' };
      }),
    );
    const { personalStore, state } = await loadStore();
    state.personal = { game1: { status: 'backlog', exclude_from_count: true } };
    await personalStore.init();
    expect(state.personal.game1.exclude_from_count).toBe(true);
  });

  it('hybrid mode: populated server doc on account profile scope skips migration banner', async () => {
    vi.resetModules();
    const accountId = '0344d93b-a54d-4b75-8dc2-05b158b8de42';
    vi.doMock('../js/auth-gate.js', () => ({
      isAccountAuthMode: () => true,
      isLocalProfilesEnabled: () => true,
      getAccountProfileId: () => accountId,
      getAccessToken: () => 'tok',
      whenAuthReady: () => Promise.resolve(),
      refreshAccessToken: async () => null,
      handleApiUnauthorized: () => {},
    }));
    const { STORAGE_KEY } = await import('../js/state.js');
    localStorage.setItem(
      `${STORAGE_KEY}:${accountId}`,
      JSON.stringify({ game1: { status: 'backlog' } }),
    );
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (url === '/api/personal') {
          return {
            ok: true,
            json: async () => ({
              personal: { game1: { status: 'backlog' }, game2: { status: 'playing' } },
              prefs: { activeView: 'library' },
              manual: [],
              libraryFirstSeen: {},
            }),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    const result = await personalStore.init();
    expect(result.pendingMigration).toBeNull();
    expect(result.migrated).toBe(true);
    expect(state.personal.game2?.status).toBe('playing');
  });

  it('does not PUT an empty snapshot before init completes', async () => {
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
          return { ok: true, json: async () => JSON.parse(opts.body) };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore } = await loadStore();
    personalStore.notify();
    await personalStore.flush();
    expect(puts).toHaveLength(0);
  });

  it('first-seen merge keeps the newer local timestamp', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (url === '/api/personal') {
          return {
            ok: true,
            json: async () => ({
              personal: {},
              prefs: {},
              manual: [],
              libraryFirstSeen: { 'steam:1': 1000 },
            }),
          };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );
    localStorage.setItem('baklog-library-first-seen-default', JSON.stringify({ 'steam:1': 5000 }));
    const { personalStore, state } = await loadStore();
    const { libraryFirstSeenStorageKey } = await import('../js/profiles.js');
    localStorage.setItem(libraryFirstSeenStorageKey(), JSON.stringify({ 'steam:1': 5000 }));
    await personalStore.init();
    expect(state.libraryFirstSeenByKey['steam:1']).toBe(5000);
  });

  it('does not merge unscoped default localStorage dismissals into non-default profile', async () => {
    vi.resetModules();
    localStorage.clear();
    localStorage.setItem('baklog-active-profile', 'promo');
    // Unscoped key is default's pre-multi-profile cache — must not bleed into promo.
    localStorage.setItem(
      'steam-backlog-personal',
      JSON.stringify({
        __dismissedClaims: { 'epic-citizen-sleeper-944858': 1781799498808 },
        __dismissedClaimKeys: { 'title:citizen sleeper': 1781799498808 },
      }),
    );
    localStorage.setItem(
      'steam-backlog-personal:promo',
      JSON.stringify({ game1: { status: 'backlog' } }),
    );

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
          return { ok: true, json: async () => JSON.parse(opts.body) };
        }
        return { ok: false, status: 500, text: async () => '' };
      }),
    );

    const { personalStore, state } = await loadStore();
    await personalStore.init();
    expect(state.personal.__dismissedClaims).toBeUndefined();
    expect(state.personal.__dismissedClaimKeys).toBeUndefined();
  });
});
