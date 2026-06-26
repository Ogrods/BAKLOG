import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const supabaseMock = vi.hoisted(() => {
  let session = null;
  let authListener = null;
  let getSessionResult = null;
  const signOut = vi.fn(async () => { session = null; });
  const client = {
    auth: {
      getSession: vi.fn(async () => getSessionResult ?? { data: { session }, error: null }),
      signInWithPassword: vi.fn(async () => ({ data: { session }, error: null })),
      signUp: vi.fn(async () => ({ data: { user: { id: 'new' }, session: null }, error: null })),
      signOut,
      refreshSession: vi.fn(async () => ({ data: { session }, error: null })),
      resetPasswordForEmail: vi.fn(async () => ({ data: {}, error: null })),
      resend: vi.fn(async () => ({ data: {}, error: null })),
      updateUser: vi.fn(async () => ({ data: { session }, error: null })),
      onAuthStateChange: vi.fn((cb) => {
        authListener = cb;
        return { data: { subscription: { unsubscribe: vi.fn() } } };
      }),
    },
  };
  return {
    createClient: vi.fn(() => client),
    client,
    setSession(s) { session = s; getSessionResult = null; },
    setGetSessionResult(r) { getSessionResult = r; },
    getSession() { return session; },
    fireAuthChange(event, next) { authListener?.(event, next); },
    reset() {
      session = null;
      authListener = null;
      getSessionResult = null;
      signOut.mockClear();
      client.auth.resetPasswordForEmail.mockClear();
      client.auth.resend.mockClear();
      client.auth.signUp.mockClear();
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
      <h2 id="authGateTitle"></h2>
      <p id="authGateHint"></p>
      <form id="authGateForm" data-auth-panel="signin">
        <input id="authGateEmail" />
        <input id="authGatePassword" />
        <p id="authGateError" class="auth-gate-error hidden"></p>
        <p id="authGateSignInSuccess" class="auth-gate-success hidden"></p>
        <button type="submit" id="authGateSubmit"></button>
        <button type="button" id="authGateForgotLink"></button>
        <button type="button" id="authGateCreateLink"></button>
        <button type="button" id="authGateResendConfirm" class="hidden" hidden></button>
      </form>
      <form id="authGateSignupForm" class="hidden" data-auth-panel="signup" hidden>
        <input id="authGateSignupEmail" />
        <input id="authGateSignupPassword" />
        <input id="authGateSignupConfirm" />
        <p id="authGateSignupError" class="hidden"></p>
        <p id="authGateSignupSuccess" class="hidden auth-gate-success"></p>
        <button type="submit" id="authGateSignupSubmit"></button>
        <button type="button" id="authGateSignupBack"></button>
      </form>
      <form id="authGateForgotForm" class="hidden" data-auth-panel="forgot" hidden>
        <input id="authGateForgotEmail" />
        <p id="authGateForgotError" class="hidden"></p>
        <p id="authGateForgotSuccess" class="hidden auth-gate-success"></p>
        <button type="submit" id="authGateForgotSubmit"></button>
        <button type="button" id="authGateBackToSignIn"></button>
      </form>
      <form id="authGateResetForm" class="hidden" data-auth-panel="reset" hidden>
        <input id="authGateNewPassword" />
        <input id="authGateConfirmPassword" />
        <p id="authGateResetError" class="hidden"></p>
        <button type="submit" id="authGateResetSubmit"></button>
      </form>`;
    document.documentElement.removeAttribute('data-auth-required');
    document.documentElement.removeAttribute('data-boot-loading');
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (url === '/api/config') {
        return new Response(JSON.stringify({
          authRequired: true,
          supabaseUrl: 'https://test.supabase.co',
          supabaseAnonKey: 'anon',
          authConfirmRedirectUrl: 'https://baklog.app/auth/confirmed',
          authResetRedirectUrl: 'https://baklog.app/auth/reset',
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

  it('initAuthGate clears stale refresh token and shows sign-in', async () => {
    supabaseMock.setGetSessionResult({
      data: { session: null },
      error: { message: 'Invalid Refresh Token: Refresh Token Not Found' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    const boot = initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    expect(supabaseMock.client.auth.signOut).toHaveBeenCalled();
    const ov = document.getElementById('authGateOverlay');
    expect(ov.hidden).toBe(false);
    expect(document.documentElement.hasAttribute('data-auth-required')).toBe(true);
    await expect(Promise.race([boot, Promise.resolve('pending')])).resolves.toBe('pending');
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
    expect(document.documentElement.hasAttribute('data-auth-required')).toBe(false);
    expect(getAccountEmail()).toBe('user@example.com');
    expect(getAccountProfileId()).toBe('550e8400-e29b-41d4-a716-446655440000');
  });

  it('initAuthGate retries session probe after transient failure', async () => {
    let sessionHits = 0;
    vi.stubGlobal('fetch', vi.fn(async (url) => {
      if (url === '/api/config') {
        return new Response(JSON.stringify({
          authRequired: true,
          supabaseUrl: 'https://test.supabase.co',
          supabaseAnonKey: 'anon',
        }), { status: 200 });
      }
      if (url === '/api/auth/session') {
        sessionHits += 1;
        if (sessionHits < 2) return new Response('{}', { status: 401 });
        return new Response(JSON.stringify({
          ok: true,
          email: 'user@example.com',
          profile: '550e8400-e29b-41d4-a716-446655440000',
        }), { status: 200 });
      }
      return new Response('{}', { status: 404 });
    }));
    supabaseMock.setSession({
      access_token: 'tok',
      user: { email: 'user@example.com' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    await initAuthGate();
    expect(sessionHits).toBeGreaterThanOrEqual(2);
    expect(document.getElementById('authGateOverlay').hidden).toBe(true);
  }, 10_000);

  it('initAuthGate with valid session leaves boot curtain up', async () => {
    document.documentElement.setAttribute('data-boot-loading', 'dashboard');
    supabaseMock.setSession({
      access_token: 'tok',
      user: { email: 'user@example.com' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    await initAuthGate();
    expect(document.documentElement.hasAttribute('data-auth-required')).toBe(false);
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(true);
    expect(document.getElementById('authGateOverlay').hidden).toBe(true);
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

  it('isPro returns true when ?pro=1 is in the URL on localhost', async () => {
    vi.stubGlobal('location', { ...window.location, hostname: '127.0.0.1', search: '?pro=1' });
    const { isPro, getPlan } = await import('../js/auth-gate.js');
    expect(isPro()).toBe(true);
    expect(getPlan()).toBe('pro');
  });

  it('isPro ignores ?pro=1 off localhost', async () => {
    vi.stubGlobal('location', { ...window.location, hostname: 'baklog.app', search: '?pro=1' });
    const { isPro, getPlan } = await import('../js/auth-gate.js');
    expect(isPro()).toBe(false);
    expect(getPlan()).not.toBe('pro');
  });

  it('isPro returns true when baklog-debug-pro is set in localStorage', async () => {
    localStorage.setItem('baklog-debug-pro', '1');
    const { isPro, getPlan } = await import('../js/auth-gate.js');
    expect(isPro()).toBe(true);
    expect(getPlan()).toBe('pro');
    localStorage.removeItem('baklog-debug-pro');
  });

  it('showAuthGatePanel toggles signup form', async () => {
    const { showAuthGatePanel } = await import('../js/auth-gate.js');
    showAuthGatePanel('signup');
    expect(document.getElementById('authGateSignupForm').hidden).toBe(false);
    expect(document.getElementById('authGateTitle').textContent).toContain('Create');
  });

  it('signup submit calls signUp with hosted confirm redirect', async () => {
    supabaseMock.setGetSessionResult({
      data: { session: null },
      error: { message: 'Invalid Refresh Token: Refresh Token Not Found' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    document.getElementById('authGateCreateLink').click();
    document.getElementById('authGateSignupEmail').value = 'new@example.com';
    document.getElementById('authGateSignupPassword').value = 'password123';
    document.getElementById('authGateSignupConfirm').value = 'password123';
    document.getElementById('authGateSignupForm').requestSubmit();
    await new Promise((r) => setTimeout(r, 0));
    expect(supabaseMock.client.auth.signUp).toHaveBeenCalledWith({
      email: 'new@example.com',
      password: 'password123',
      options: { emailRedirectTo: 'https://baklog.app/auth/confirmed' },
    });
  });

  it('showAuthGatePanel toggles forgot-password form', async () => {
    const { showAuthGatePanel } = await import('../js/auth-gate.js');
    showAuthGatePanel('forgot');
    expect(document.getElementById('authGateForm').hidden).toBe(true);
    expect(document.getElementById('authGateForgotForm').hidden).toBe(false);
    expect(document.getElementById('authGateTitle').textContent).toContain('Reset');
  });

  it('forgot-password submit calls resetPasswordForEmail', async () => {
    supabaseMock.setGetSessionResult({
      data: { session: null },
      error: { message: 'Invalid Refresh Token: Refresh Token Not Found' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    document.getElementById('authGateForgotLink').click();
    document.getElementById('authGateForgotEmail').value = 'user@example.com';
    document.getElementById('authGateForgotForm').requestSubmit();
    await new Promise((r) => setTimeout(r, 0));
    expect(supabaseMock.client.auth.resetPasswordForEmail).toHaveBeenCalledWith(
      'user@example.com',
      { redirectTo: 'https://baklog.app/auth/reset' },
    );
  });

  it('PASSWORD_RECOVERY shows reset panel', async () => {
    supabaseMock.setGetSessionResult({
      data: { session: null },
      error: { message: 'Invalid Refresh Token: Refresh Token Not Found' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    supabaseMock.fireAuthChange('PASSWORD_RECOVERY', { access_token: 'recovery-tok' });
    expect(document.getElementById('authGateResetForm').hidden).toBe(false);
    expect(document.getElementById('authGateTitle').textContent).toContain('new password');
  });

  it('unconfirmed sign-in shows resend and calls resend on click', async () => {
    supabaseMock.client.auth.signInWithPassword.mockResolvedValueOnce({
      data: { session: null },
      error: { message: 'Email not confirmed' },
    });
    supabaseMock.setGetSessionResult({
      data: { session: null },
      error: { message: 'Invalid Refresh Token: Refresh Token Not Found' },
    });
    const { initAuthGate } = await import('../js/auth-gate.js');
    initAuthGate();
    await new Promise((r) => setTimeout(r, 50));
    document.getElementById('authGateEmail').value = 'new@example.com';
    document.getElementById('authGatePassword').value = 'password123';
    document.getElementById('authGateForm').requestSubmit();
    await new Promise((r) => setTimeout(r, 0));
    expect(document.getElementById('authGateResendConfirm').hidden).toBe(false);
    document.getElementById('authGateResendConfirm').click();
    await new Promise((r) => setTimeout(r, 0));
    expect(supabaseMock.client.auth.resend).toHaveBeenCalledWith({
      type: 'signup',
      email: 'new@example.com',
      options: { emailRedirectTo: 'https://baklog.app/auth/confirmed' },
    });
  });
});
