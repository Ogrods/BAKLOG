import { describe, it, expect, vi, afterEach } from 'vitest';

const { mockFetch } = vi.hoisted(() => {
  async function mockFetch(url) {
    if (url === '/api/auth/status') {
      return new Response(JSON.stringify({ providers: [] }), { status: 200 });
    }
    if (url === '/api/config') {
      return new Response(JSON.stringify({ chromium_available: true }), { status: 200 });
    }
    if (url === '/api/mirror/clear') {
      return new Response(JSON.stringify({ ok: true, count: 2 }), { status: 200 });
    }
    if (String(url).startsWith('/api/mirror')) {
      return new Response(
        JSON.stringify({
          artifacts: [],
          profiles: ['default'],
          profile: 'default',
          localUploadState: { artifacts: {}, last_upload_at: null },
        }),
        { status: 200 },
      );
    }
    return new Response('{}', { status: 404 });
  }
  return { mockFetch };
});

vi.mock('../js/api-client.js', () => ({
  baklogFetch: vi.fn(mockFetch),
  urlWithStreamTicket: vi.fn(async (u) => u),
}));

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: vi.fn(() => true),
  isPro: vi.fn(() => true),
  isAdminMode: vi.fn(() => false),
  isLocalProfilesEnabled: vi.fn(() => true),
  proFeaturesUnlocked: vi.fn(() => true),
  getAccessToken: vi.fn(() => 'tok'),
  getAccountProfileId: vi.fn(() => null),
  getProSettings: vi.fn(() => ({ cloudMirrorEnabled: true })),
  refreshAccountPlan: vi.fn(async () => 'pro'),
}));

vi.mock('../js/pro-capabilities.js', () => ({
  capabilityStatus: vi.fn(() => 'live'),
  getProSettings: vi.fn(() => ({ cloudMirrorEnabled: true })),
  setProSettings: vi.fn((s) => s),
}));

vi.mock('../js/filters-ui.js', () => ({
  applyItchTabVisibility: vi.fn(),
}));

vi.mock('../js/state.js', () => ({
  state: { activeView: 'connections', prefs: {} },
  STORAGE_KEY: 'steam-backlog-personal',
  PREFS_KEY: 'steam-backlog-ui-prefs',
  MANUAL_KEY: 'steam-backlog-manual-games',
  LIBRARY_FIRST_SEEN_KEY: 'steam-backlog-library-first-seen',
  KNOWN_LIBRARY_KEYS_KEY: 'baklog-known-library-keys',
  COLOR_THEME_KEY: 'baklog-color-theme',
}));

vi.mock('../js/visibility.js', () => ({
  isPageHidden: vi.fn(() => false),
  registerPausable: vi.fn(),
}));

function mountDom() {
  document.body.innerHTML = `
    <div id="connectionsContainer">
    <strong id="connHeroCount"></strong>
    <span id="connProgressFill"></span>
    <div id="connOnboard" hidden></div>
    <nav id="connRail" role="listbox"></nav>
    <div id="connPane"></div>
    <div id="connCloudPrefs" hidden>
      <label id="cloudMirrorToggleWrap" hidden><input id="cloudMirrorEnabledToggle" type="checkbox" /></label>
      <button id="cloudMirrorSyncBtn" type="button" hidden>Sync now</button>
      <button id="cloudMirrorClearBtn" type="button" hidden>Clear cloud library</button>
      <p id="cloudMirrorUploadStatus" hidden></p>
    </div>
    <div id="connLayout"></div>
    </div>`;
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await new Promise((r) => setTimeout(r, 0));
}

describe('Clear cloud library result message', () => {
  afterEach(() => {
    vi.resetModules();
  });

  it('keeps the cleared count visible after the status refresh runs', async () => {
    mountDom();
    window.confirm = vi.fn(() => true);
    const mod = await import('../js/connections.js');
    mod.wireConnectionsUi();
    await mod.refreshConnections();
    await flush();

    document.getElementById('cloudMirrorClearBtn').click();
    await flush();

    const status = document.getElementById('cloudMirrorUploadStatus');
    expect(status.hidden).toBe(false);
    expect(status.textContent).toBe(
      'Cloud library cleared (2 files deleted). Credentials stayed local.',
    );

    await mod.refreshConnections();
    await flush();
    expect(status.textContent).toMatch(/Cloud library cleared/);
  });

  it('shows the clear error instead of the upload summary', async () => {
    mountDom();
    window.confirm = vi.fn(() => true);
    const api = await import('../js/api-client.js');
    vi.mocked(api.baklogFetch).mockImplementation(async (url) => {
      if (url === '/api/mirror/clear') {
        return new Response(JSON.stringify({ error: 'Storage unavailable' }), { status: 503 });
      }
      return mockFetch(url);
    });
    const mod = await import('../js/connections.js');
    mod.wireConnectionsUi();
    await mod.refreshConnections();
    await flush();

    document.getElementById('cloudMirrorClearBtn').click();
    await flush();

    const status = document.getElementById('cloudMirrorUploadStatus');
    expect(status.textContent).toBe('Storage unavailable');
    expect(status.classList.contains('conn-prefs-note--error')).toBe(true);
    vi.mocked(api.baklogFetch).mockImplementation(mockFetch);
  });
});
