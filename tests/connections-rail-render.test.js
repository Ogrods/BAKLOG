import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const { mkProvider, steamProvider, mockProviders } = vi.hoisted(() => {
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
  return { mkProvider, steamProvider, mockProviders: { list: [steamProvider] } };
});

vi.mock('../js/api-client.js', () => ({
  baklogFetch: vi.fn(async (url) => {
    if (url === '/api/auth/status') {
      return new Response(
        JSON.stringify({ providers: mockProviders.list }),
        { status: 200 },
      );
    }
    return new Response('{}', { status: 404 });
  }),
  urlWithStreamTicket: vi.fn(async (u) => u),
}));

vi.mock('../js/auth-gate.js', () => ({
  isAccountAuthMode: vi.fn(() => false),
}));

vi.mock('../js/filters-ui.js', () => ({
  applyItchTabVisibility: vi.fn(),
}));

vi.mock('../js/state.js', () => ({
  state: { activeView: 'connections' },
  STORAGE_KEY: 'steam-backlog-personal',
  PREFS_KEY: 'steam-backlog-ui-prefs',
  MANUAL_KEY: 'steam-backlog-manual-games',
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

    // The next refresh fails at the network layer.
    vi.mocked(baklogFetch).mockImplementationOnce(() => {
      throw new Error('server down');
    });
    await refreshConnections();

    // Cached steam row is still rendered — the snapshot is kept, pane not wiped.
    expect(document.querySelector('.conn-rail-item[data-provider="steam"]')).toBeTruthy();

    const banner = document.getElementById('connRefreshBanner');
    expect(banner).toBeTruthy();
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.className).toContain('text-amber-400');
    expect(banner.textContent).toMatch(/local server/i);
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
