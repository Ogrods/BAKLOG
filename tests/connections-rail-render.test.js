import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const steamProvider = {
  key: 'steam',
  label: 'Steam',
  kind: 'browser',
  status: 'connected',
  description: 'Steam library',
  form_fields: [],
  tips: [],
};

vi.mock('../js/api-client.js', () => ({
  baklogFetch: vi.fn(async (url) => {
    if (url === '/api/auth/status') {
      return new Response(
        JSON.stringify({ providers: [steamProvider] }),
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
