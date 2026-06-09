import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const authGate = vi.hoisted(() => {
  let settled = false;
  const waiters = [];
  return {
    isAccountAuthMode: vi.fn(() => true),
    getAccessToken: vi.fn(() => 'test-token'),
    whenAuthReady: vi.fn(() => {
      if (settled) return Promise.resolve();
      return new Promise((resolve) => { waiters.push(resolve); });
    }),
    settleAuthReady() {
      settled = true;
      while (waiters.length) waiters.shift()();
    },
    resetAuthReady() {
      settled = false;
      waiters.length = 0;
    },
    refreshAccessToken: vi.fn(async () => null),
    handleApiUnauthorized: vi.fn(),
  };
});

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: authGate.isAccountAuthMode,
  getAccessToken: authGate.getAccessToken,
  whenAuthReady: authGate.whenAuthReady,
  refreshAccessToken: authGate.refreshAccessToken,
  handleApiUnauthorized: authGate.handleApiUnauthorized,
}));

describe('api-client auth boot guard', () => {
  beforeEach(() => {
    authGate.resetAuthReady();
    authGate.isAccountAuthMode.mockReturnValue(true);
    authGate.getAccessToken.mockReturnValue('test-token');
    authGate.refreshAccessToken.mockReset();
    authGate.handleApiUnauthorized.mockReset();
    authGate.whenAuthReady.mockClear();
    document.documentElement.removeAttribute('data-boot-loading');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('waits for whenAuthReady before protected /api/* fetch', async () => {
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { baklogFetch } = await import('../js/api-client.js');
    const pending = baklogFetch('/api/personal');
    await Promise.resolve();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(authGate.whenAuthReady).toHaveBeenCalled();

    authGate.settleAuthReady();
    await pending;
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/api/personal');
  });

  it('does not call handleApiUnauthorized on 401 while data-boot-loading is set', async () => {
    document.documentElement.setAttribute('data-boot-loading', 'dashboard');
    authGate.settleAuthReady();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })));

    const { baklogFetch } = await import('../js/api-client.js');
    await baklogFetch('/api/personal');

    expect(authGate.handleApiUnauthorized).not.toHaveBeenCalled();
  });

  it('calls handleApiUnauthorized on 401 after boot curtain is lifted', async () => {
    authGate.settleAuthReady();
    vi.stubGlobal('fetch', vi.fn(async () => new Response('{}', { status: 401 })));

    const { baklogFetch } = await import('../js/api-client.js');
    await baklogFetch('/api/personal');

    expect(authGate.handleApiUnauthorized).toHaveBeenCalled();
  });

  it('attaches Bearer to /cache/protondb_map.json', async () => {
    authGate.settleAuthReady();
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { dataFetch } = await import('../js/api-client.js');
    await dataFetch('cache/protondb_map.json?t=1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe('Bearer test-token');
  });

  it('attaches Bearer to games_*.json paths without a leading slash', async () => {
    authGate.settleAuthReady();
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { dataFetch } = await import('../js/api-client.js');
    await dataFetch('games_steam.json?t=1');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers.Authorization).toBe('Bearer test-token');
  });

  it('does not gate GET /api/config', async () => {
    authGate.isAccountAuthMode.mockReturnValue(true);
    const fetchMock = vi.fn(async () => new Response('{}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    const { baklogFetch } = await import('../js/api-client.js');
    await baklogFetch('/api/config');

    expect(authGate.whenAuthReady).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalled();
  });
});
