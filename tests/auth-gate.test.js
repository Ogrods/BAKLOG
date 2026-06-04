import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const supabaseMock = vi.hoisted(() => {
  let session = null;
  let authListener = null;
  return {
    createClient: vi.fn(() => ({
      auth: {
        getSession: vi.fn(async () => ({ data: { session } })),
        signInWithPassword: vi.fn(async () => ({ data: { session }, error: null })),
        signOut: vi.fn(async () => { session = null; }),
        refreshSession: vi.fn(async () => ({ data: { session }, error: null })),
        onAuthStateChange: vi.fn((cb) => {
          authListener = cb;
          return { data: { subscription: { unsubscribe: vi.fn() } } };
        }),
      },
    })),
    setSession(s) { session = s; },
    getSession() { return session; },
    fireAuthChange(next) { authListener?.('SIGNED_IN', next); },
    reset() {
      session = null;
      authListener = null;
    },
  };
});

vi.mock('../js/vendor/supabase-js.mjs', () => ({
  createClient: supabaseMock.createClient,
}));

describe('auth-gate', () => {
  beforeEach(() => {
    supabaseMock.reset();
    document.body.innerHTML = `
      <div id="authGateOverlay" hidden></div>
      <form id="authGateForm">
        <input id="authGateEmail" />
        <input id="authGatePassword" />
        <p id="authGateError" class="hidden"></p>
        <button type="submit" id="authGateSubmit"></button>
      </form>`;
    document.documentElement.removeAttribute('data-auth-required');
    document.documentElement.removeAttribute('data-boot-loading');
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (url === '/api/config') {
        return new Response(JSON.stringify({
          authRequired: true,
          supabaseUrl: 'https://test.supabase.co',
          supabaseAnonKey: 'anon',
        }), { status: 200 });
      }
      if (url === '/api/auth/session') {
        return new Response(JSON.stringify({
          ok: true,
          email: 'user@example.com',
          profile: '550e8400-e29b-41d4-a716-446655440000',
        }), { status: 200 });
      }
      return new Response('{}', { status: 404 });
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it('initAuthGate hides overlay when session is valid', async () => {
    supabaseMock.setSession({
      access_token: 'tok',
      user: { email: 'user@example.com' },
    });
    const { initAuthGate, getAccountEmail, getAccountProfileId } = await import('../js/auth-gate.js');
    await initAuthGate();
    const ov = document.getElementById('authGateOverlay');
    expect(ov.hidden).toBe(true);
    expect(getAccountEmail()).toBe('user@example.com');
    expect(getAccountProfileId()).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('handleApiUnauthorized re-shows overlay after boot', async () => {
    supabaseMock.setSession({ access_token: 'tok', user: { email: 'a@b.com' } });
    const { initAuthGate, handleApiUnauthorized } = await import('../js/auth-gate.js');
    await initAuthGate();
    handleApiUnauthorized();
    const ov = document.getElementById('authGateOverlay');
    expect(ov.hidden).toBe(false);
    expect(document.getElementById('authGateError').textContent).toContain('Session expired');
  });

  it('keeps gate when config fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new Error('network down');
    }));
    const { initAuthGate } = await import('../js/auth-gate.js');
    const boot = initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    const ov = document.getElementById('authGateOverlay');
    expect(ov.hidden).toBe(false);
    expect(document.getElementById('authGateError').textContent).toContain('Could not load server config');
    expect(document.documentElement.hasAttribute('data-auth-required')).toBe(true);
    await expect(Promise.race([boot, Promise.resolve('pending')])).resolves.toBe('pending');
  });

  it('signOutAccount with intentional does not show session expired message', async () => {
    supabaseMock.setSession({ access_token: 'tok', user: { email: 'a@b.com' } });
    const { initAuthGate, signOutAccount } = await import('../js/auth-gate.js');
    await initAuthGate();
    await signOutAccount({ intentional: true });
    expect(document.getElementById('authGateError').textContent).toBe('');
  });
});
