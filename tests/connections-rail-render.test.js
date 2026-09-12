import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mkProvider, steamProvider, mockProviders, mockBaklogFetchDefault } = vi.hoisted(() => {
  function mkProvider(key, overrides = {}) {
    return {
      key,
      label: key,
      kind: 'browser',
      status: 'disconnected',
      description: '',
      form_fields: [],
      tips: [],
      ...overrides,
    };
  }
  const steamProvider = mkProvider('steam', {
    label: 'Steam',
    status: 'connected',
    description: 'Steam library',
  });
  const mockProviders = { list: [steamProvider] };
  async function mockBaklogFetchDefault(url) {
    if (url === '/api/auth/status') {
      return new Response(
        JSON.stringify({ providers: mockProviders.list }),
        { status: 200 },
      );
    }
    if (url === '/api/config') {
      return new Response(JSON.stringify({ chromium_available: true }), { status: 200 });
    }
    return new Response('{}', { status: 404 });
  }
  return { mkProvider, steamProvider, mockProviders, mockBaklogFetchDefault };
});

vi.mock('../js/api-client.js', () => ({
  baklogFetch: vi.fn(mockBaklogFetchDefault),
  urlWithStreamTicket: vi.fn(async (u) => u),
}));

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: vi.fn(() => false),
  isPro: vi.fn(() => false),
  isAdminMode: vi.fn(() => false),
  isLocalProfilesEnabled: vi.fn(() => true),
  proFeaturesUnlocked: vi.fn(() => false),
  getAccessToken: vi.fn(() => null),
  getAccountProfileId: vi.fn(() => null),
  getProSettings: vi.fn(() => ({ cloudMirrorEnabled: false })),
  refreshAccountPlan: vi.fn(async () => 'free'),
}));

vi.mock('../js/pro-capabilities.js', () => ({
  capabilityStatus: vi.fn(() => 'soon'),
  getProSettings: vi.fn(() => ({ cloudMirrorEnabled: false })),
  setProSettings: vi.fn(() => ({ cloudMirrorEnabled: false })),
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

function mountConnectionsDom() {
  document.body.innerHTML = `
    <strong id="connHeroCount"></strong>
    <span id="connProgressFill"></span>
    <div id="connOnboard" hidden></div>
    <nav id="connRail" role="listbox"></nav>
    <div id="connPane"></div>`;
}

describe('connections rail render', () => {
  beforeEach(() => {
    mockProviders.list = [steamProvider];
    mountConnectionsDom();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('refreshConnections renders rail dot from pillSt without throwing', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await expect(refreshConnections()).resolves.toBeUndefined();

    const dot = document.querySelector('.conn-rail-item[data-provider="steam"] .conn-row-dot');
    expect(dot?.classList.contains('conn-row-dot--connected')).toBe(true);

    const railPill = document.querySelector('.conn-rail-item[data-provider="steam"] .conn-row-pill');
    expect(railPill?.textContent).toBe('Connected');
  });
});

describe('refreshConnections error keep-cache', () => {
  beforeEach(() => {
    mockProviders.list = [steamProvider];
    document.body.innerHTML = `
      <strong id="connHeroCount"></strong>
      <span id="connProgressFill"></span>
      <div id="connOnboard" hidden></div>
      <div id="connLayout">
        <nav id="connRail" role="listbox"></nav>
        <div id="connPane"></div>
      </div>`;
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('keeps the cached rail and shows an amber error when a later refresh fails', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    const { baklogFetch } = await import('../js/api-client.js');

    // First refresh succeeds and populates the in-memory snapshot.
    await refreshConnections();
    expect(document.querySelector('.conn-rail-item[data-provider="steam"]')).toBeTruthy();

    // The next refresh fails at the auth-status fetch (config preflight runs first).
    vi.mocked(baklogFetch).mockImplementation(async (url) => {
      if (url === '/api/auth/status') {
        throw new Error('server down');
      }
      return mockBaklogFetchDefault(url);
    });
    await refreshConnections();

    // Cached steam row is still rendered — the snapshot is kept, pane not wiped.
    expect(document.querySelector('.conn-rail-item[data-provider="steam"]')).toBeTruthy();

    const banner = document.getElementById('connRefreshBanner');
    expect(banner).toBeTruthy();
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.className).toContain('text-amber-400');
    expect(banner.textContent).toMatch(/local server/i);

    vi.mocked(baklogFetch).mockImplementation(mockBaklogFetchDefault);
  });
});

describe('connections content groups (Epic)', () => {
  beforeEach(() => {
    mockProviders.list = [
      mkProvider('epic', { label: 'Epic Games', description: 'Epic library' }),
      mkProvider('epic_wishlist', { label: 'Epic Wishlist', description: 'Epic wishlist' }),
    ];
    mountConnectionsDom();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('collapses epic + epic_wishlist to one rail row with library-on-top stack', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    expect(document.querySelector('.conn-rail-item[data-provider="epic"]')).toBeTruthy();
    expect(document.querySelector('.conn-rail-item[data-provider="epic_wishlist"]')).toBeNull();

    const stack = document.querySelector('.conn-card-stack');
    expect(stack).toBeTruthy();
    const cards = stack.querySelectorAll('.conn-card[data-provider]');
    expect(cards.length).toBe(2);
    expect(cards[0].getAttribute('data-provider')).toBe('epic');
    expect(cards[1].getAttribute('data-provider')).toBe('epic_wishlist');
  });

  it('shows separate sign-ins note for Epic content group', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    const note = document.querySelector('.conn-group-note')?.textContent || '';
    expect(note).toMatch(/separate sign-ins/i);
    expect(note).toMatch(/library card is on top/i);
  });

  it('hero count reflects collapsed rail rows, not raw providers', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    // epic + epic_wishlist collapse into one rail row, so the hero denominator
    // is 1 (stores) rather than 2 (raw auth providers).
    expect(document.getElementById('connHeroCount')?.textContent).toBe('0 of 1 stores connected');
  });

  it('renders Content and Source facet badges on Epic library card', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    const epicCard = document.querySelector('.conn-card[data-provider="epic"]');
    expect(epicCard?.querySelector('.conn-facet--content')?.textContent).toBe('Library');
    expect(epicCard?.querySelector('.conn-facet--source')?.textContent).toBe('Web sign-in');
    const wlCard = document.querySelector('.conn-card[data-provider="epic_wishlist"]');
    expect(wlCard?.querySelector('.conn-facet--content')?.textContent).toBe('Wishlist');
  });
});

describe('connections source groups (GOG)', () => {
  beforeEach(() => {
    mockProviders.list = [
      mkProvider('gog', { label: 'GOG', description: 'GOG web', status: 'connected' }),
      mkProvider('gog_galaxy', {
        label: 'GOG Galaxy',
        kind: 'local',
        description: 'Galaxy DB',
      }),
    ];
    mountConnectionsDom();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('collapses gog + gog_galaxy to one rail row', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    expect(document.querySelector('.conn-rail-item[data-provider="gog"]')).toBeTruthy();
    expect(document.querySelector('.conn-rail-item[data-provider="gog_galaxy"]')).toBeNull();
  });

  it('shows only-need-one source note with wishlist reinforcement for GOG', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    const note = document.querySelector('.conn-group-note')?.textContent || '';
    expect(note).toMatch(/only need one GOG source/i);
    expect(note).toMatch(/library and wishlist/i);
    expect(note).not.toMatch(/separate sign-ins/i);
  });

  it('renders facet badges: web Library + Wishlist, Galaxy Library + File scan', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    const web = document.querySelector('.conn-card[data-provider="gog"]');
    expect(web?.querySelector('.conn-facet--content')?.textContent).toBe('Library + Wishlist');
    expect(web?.querySelector('.conn-facet--source')?.textContent).toBe('Web sign-in');

    const galaxy = document.querySelector('.conn-card[data-provider="gog_galaxy"]');
    expect(galaxy?.querySelector('.conn-facet--content')?.textContent).toBe('Library');
    expect(galaxy?.querySelector('.conn-facet--source')?.textContent).toBe('File scan');
  });
});

describe('connections content groups (Nintendo)', () => {
  beforeEach(() => {
    mockProviders.list = [
      mkProvider('nintendo', { label: 'Nintendo', description: 'Nintendo library' }),
      mkProvider('nintendo_wishlist', { label: 'Nintendo Wishlist', description: 'Nintendo wishlist' }),
    ];
    mountConnectionsDom();
  });

  afterEach(() => {
    vi.resetModules();
  });

  it('shows legacy retention note for Nintendo content group', async () => {
    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    const note = document.querySelector('.conn-group-note')?.textContent || '';
    expect(note).toMatch(/Virtual Game Cards/i);
    expect(note).toMatch(/about two years/i);
    expect(note).toMatch(/not marked stale/i);
    expect(note).toMatch(/bulk Remove/i);
  });
});

describe('cloud mirror prefs visibility', () => {
  afterEach(() => {
    vi.resetModules();
  });

  function mountCloudPrefsDom() {
    document.body.innerHTML = `
      <div id="connectionsContainer">
      <strong id="connHeroCount"></strong>
      <span id="connProgressFill"></span>
      <div id="connOnboard" hidden></div>
      <nav id="connRail" role="listbox"></nav>
      <div id="connPane"></div>
      <div id="connPrefs" class="conn-prefs">
        <input id="autoFetchOnConnectToggle" type="checkbox" />
        <input id="autoFetchStale24hToggle" type="checkbox" />
        <input id="shareAnonStatsToggle" type="checkbox" />
        <p id="bgRefreshPlanNote" hidden></p>
      </div>
      <div id="connCloudPrefs" class="conn-prefs conn-cloud-prefs" hidden>
        <div class="conn-cloud-prefs-row">
          <label id="cloudMirrorToggleWrap" hidden>
            <input id="cloudMirrorEnabledToggle" type="checkbox" />
          </label>
          <button id="cloudMirrorSyncBtn" type="button" class="hidden" hidden>Sync now</button>
          <button id="cloudMirrorImportBtn" type="button" class="hidden" hidden>Import</button>
          <button id="cloudMirrorClearBtn" type="button" class="hidden" hidden>Clear cloud library</button>
        </div>
        <p id="cloudMirrorUploadStatus" hidden></p>
      </div>
      <div id="connLayout"></div>
      </div>
    `;
  }

  it('hides cloud sync controls when capability is soon', async () => {
    mountCloudPrefsDom();
    const auth = await import('../js/auth-gate.js');
    const caps = await import('../js/pro-capabilities.js');
    vi.mocked(auth.proFeaturesUnlocked).mockReturnValue(true);
    vi.mocked(auth.isAccountAuthMode).mockReturnValue(true);
    vi.mocked(auth.getAccessToken).mockReturnValue('tok');
    vi.mocked(caps.capabilityStatus).mockReturnValue('soon');

    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    expect(document.getElementById('connCloudPrefs')?.hidden).toBe(true);
    expect(document.getElementById('cloudMirrorToggleWrap')?.hidden).toBe(true);
    expect(document.getElementById('cloudMirrorImportBtn')?.hidden).toBe(true);
    expect(document.getElementById('cloudMirrorSyncBtn')?.hidden).toBe(true);
    expect(document.getElementById('cloudMirrorClearBtn')?.hidden).toBe(true);
  });

  it('shows cloud sync controls when capability is live for Pro account', async () => {
    mountCloudPrefsDom();
    const auth = await import('../js/auth-gate.js');
    const caps = await import('../js/pro-capabilities.js');
    vi.mocked(auth.proFeaturesUnlocked).mockReturnValue(true);
    vi.mocked(auth.isAccountAuthMode).mockReturnValue(true);
    vi.mocked(auth.getAccessToken).mockReturnValue('tok');
    vi.mocked(caps.capabilityStatus).mockReturnValue('live');
    vi.mocked(caps.getProSettings).mockReturnValue({ cloudMirrorEnabled: false });

    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    expect(document.getElementById('connCloudPrefs')?.hidden).toBe(false);
    expect(document.getElementById('cloudMirrorToggleWrap')?.hidden).toBe(false);
    expect(document.getElementById('cloudMirrorImportBtn')?.hidden).toBe(false);
    expect(document.getElementById('cloudMirrorSyncBtn')?.hidden).toBe(false);
    expect(document.getElementById('cloudMirrorSyncBtn')?.disabled).toBe(true);
    expect(document.getElementById('cloudMirrorClearBtn')?.hidden).toBe(false);
  });

  it('shows cloud sync for admin Pro-sim without real Pro plan', async () => {
    mountCloudPrefsDom();
    const auth = await import('../js/auth-gate.js');
    const caps = await import('../js/pro-capabilities.js');
    vi.mocked(auth.isPro).mockReturnValue(false);
    vi.mocked(auth.proFeaturesUnlocked).mockReturnValue(true);
    vi.mocked(auth.isAccountAuthMode).mockReturnValue(true);
    vi.mocked(auth.getAccessToken).mockReturnValue('tok');
    vi.mocked(caps.capabilityStatus).mockReturnValue('live');
    vi.mocked(caps.getProSettings).mockReturnValue({ cloudMirrorEnabled: false });

    const { refreshConnections } = await import('../js/connections.js');
    await refreshConnections();

    expect(document.getElementById('connCloudPrefs')?.hidden).toBe(false);
    expect(document.getElementById('cloudMirrorToggleWrap')?.hidden).toBe(false);
  });

  it('Clear cloud library confirms before POSTing /api/mirror/clear', async () => {
    mountCloudPrefsDom();
    const auth = await import('../js/auth-gate.js');
    const caps = await import('../js/pro-capabilities.js');
    const api = await import('../js/api-client.js');
    vi.mocked(auth.proFeaturesUnlocked).mockReturnValue(true);
    vi.mocked(auth.isAccountAuthMode).mockReturnValue(true);
    vi.mocked(auth.getAccessToken).mockReturnValue('tok');
    vi.mocked(caps.capabilityStatus).mockReturnValue('live');
    vi.mocked(caps.getProSettings).mockReturnValue({ cloudMirrorEnabled: true });

    window.confirm = vi.fn(() => false);
    const fetchSpy = vi.mocked(api.baklogFetch);
    fetchSpy.mockClear();

    const mod = await import('../js/connections.js');
    mod.wireConnectionsUi();
    await mod.refreshConnections();
    document.getElementById('cloudMirrorClearBtn')?.click();
    await Promise.resolve();

    expect(window.confirm).toHaveBeenCalled();
    expect(
      fetchSpy.mock.calls.some((c) => c[0] === '/api/mirror/clear'),
    ).toBe(false);

    window.confirm = vi.fn(() => true);
    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({ ok: true, count: 2, deleted: ['games_steam.json', 'data/personal.json'] }),
    });
    document.getElementById('cloudMirrorClearBtn')?.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(
      fetchSpy.mock.calls.some(
        (c) => c[0] === '/api/mirror/clear' && c[1]?.method === 'POST',
      ),
    ).toBe(true);
  });

  it('resets Import mode to overwrite when dialog reopens after Merge cancel', async () => {
    document.body.innerHTML = `
      <dialog id="cloudMirrorImportDialog">
        <form method="dialog">
          <p id="cloudMirrorImportIntro"></p>
          <fieldset>
            <input type="radio" name="cloudMirrorImportMode" id="cloudMirrorImportModeOverwrite" value="overwrite" checked />
            <input type="radio" name="cloudMirrorImportMode" id="cloudMirrorImportModeMerge" value="merge" />
          </fieldset>
          <ul id="cloudMirrorImportArtifactList"></ul>
          <input id="cloudMirrorImportPersonal" type="checkbox" />
          <button type="submit" value="cancel" id="importCancel">Cancel</button>
          <button type="submit" value="confirm" id="importConfirm">Import</button>
        </form>
      </dialog>
    `;
    // happy-dom may lack HTMLDialogElement.showModal
    const dialog = document.getElementById('cloudMirrorImportDialog');
    if (dialog && typeof dialog.showModal !== 'function') {
      dialog.showModal = function showModal() {
        this.open = true;
      };
      dialog.close = function close(returnValue) {
        if (returnValue !== undefined) this.returnValue = returnValue;
        this.open = false;
        this.dispatchEvent(new Event('close'));
      };
    }

    const auth = await import('../js/auth-gate.js');
    vi.mocked(auth.getAccountProfileId).mockReturnValue(null);

    const api = await import('../js/api-client.js');
    vi.mocked(api.baklogFetch).mockImplementation(async (url) => {
      if (String(url).startsWith('/api/mirror')) {
        return new Response(
          JSON.stringify({
            artifacts: [{ path: 'games_steam.json' }],
            profiles: ['default'],
            profile: 'default',
            localUploadState: { artifacts: {}, last_upload_at: null },
          }),
          { status: 200 },
        );
      }
      return mockBaklogFetchDefault(url);
    });

    const { openCloudMirrorImportDialog } = await import('../js/connections.js');
    const snap = {
      artifacts: [{ path: 'games_steam.json' }],
      profiles: ['default'],
      profile: 'default',
    };

    const first = openCloudMirrorImportDialog(snap);
    await Promise.resolve();
    document.getElementById('cloudMirrorImportModeMerge').checked = true;
    document.getElementById('cloudMirrorImportModeOverwrite').checked = false;
    dialog.close('cancel');
    const choice1 = await first;
    expect(choice1.confirmed).toBe(false);

    const second = openCloudMirrorImportDialog(snap);
    await Promise.resolve();
    expect(document.getElementById('cloudMirrorImportModeOverwrite')?.checked).toBe(true);
    expect(document.getElementById('cloudMirrorImportModeMerge')?.checked).toBe(false);
    dialog.close('cancel');
    await second;
  });
});
