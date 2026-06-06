/**
 * Supabase invite-only gate — blocks the app until the user signs in.
 * Config from GET /api/config; session stored by Supabase client in localStorage.
 */

import { stopBootTipRotation } from './tips.js';

// Loaded lazily inside initAuthGate so merely importing this module (e.g. via
// api-client.js in unit tests) never triggers the remote esm.sh fetch, and the
// network request only happens when account auth is actually enabled.
const SUPABASE_MODULE = './vendor/supabase-js.mjs';

let _config = null;
let _supabase = null;
let _accessToken = null;
let _accountEmail = '';
let _authRequired = false;
let _resolveAuthed = null;
let _authedPromise = null;
let _authReadyPromise = null;
let _resolveAuthReady = null;
let _authReadySettled = false;
let _refreshInFlight = null;
let _authHandling = null;
let _accountProfileId = '';
let _localProfiles = false;

export function isAccountAuthMode() {
  return !!_authRequired;
}

export function isLocalProfilesEnabled() {
  return _localProfiles;
}

export function getAccessToken() {
  return _accessToken;
}

/** Signed-in account email (empty when unknown / auth off). */
export function getAccountEmail() {
  return _accountEmail;
}

/** Server-bound profile id (Supabase sub) when account auth is on. */
export function getAccountProfileId() {
  return _accountProfileId;
}

function ensureAuthReadyPromise() {
  if (!_authReadyPromise) {
    _authReadyPromise = new Promise((resolve) => {
      _resolveAuthReady = resolve;
    });
  }
}

/** Resolves when initAuthGate finishes (auth off, or server-valid session). */
export function whenAuthReady() {
  ensureAuthReadyPromise();
  if (_authReadySettled) return Promise.resolve();
  return _authReadyPromise;
}

function markAuthReady() {
  _authReadySettled = true;
  if (_resolveAuthReady) {
    _resolveAuthReady();
    _resolveAuthReady = null;
  }
}

function setOverlayVisible(show) {
  const ov = document.getElementById('authGateOverlay');
  if (!ov) return;
  if (show) {
    ov.hidden = false;
    ov.setAttribute('aria-hidden', 'false');
    document.documentElement.setAttribute('data-auth-required', '1');
    try { stopBootTipRotation(); } catch (_) { /* ignore */ }
  } else {
    ov.hidden = true;
    ov.setAttribute('aria-hidden', 'true');
    document.documentElement.removeAttribute('data-auth-required');
  }
}

function setAuthError(msg) {
  const el = document.getElementById('authGateError');
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.classList.remove('hidden');
  } else {
    el.textContent = '';
    el.classList.add('hidden');
  }
}

function applySession(session) {
  _accessToken = session?.access_token || null;
  _accountEmail = session?.user?.email || _accountEmail;
  if (_accessToken) {
    setOverlayVisible(false);
    setAuthError('');
  } else {
    setOverlayVisible(true);
  }
}

/** Verify the current bearer is accepted by server.py before boot continues. */
async function probeServerToken() {
  if (!_accessToken) return false;
  try {
    const res = await fetch('/api/auth/session', {
      headers: { Authorization: `Bearer ${_accessToken}` },
    });
    if (!res.ok) return false;
    const data = await res.json();
    if (data.profile) _accountProfileId = String(data.profile);
    if (data.email) _accountEmail = data.email;
    return !!data.ok;
  } catch {
    return false;
  }
}

/**
 * Confirm the JWT works on the local server before bootstrap continues.
 * Uses the session token as-is first (fresh sign-in); refresh only if probe fails.
 */
async function ensureServerReadySession(session) {
  if (!session || !_supabase) return false;
  applySession(session);
  if (await probeServerToken()) return true;
  const tok = await refreshAccessToken();
  return !!tok;
}

function resolveAuthedWaiter() {
  if (_resolveAuthed) {
    _resolveAuthed();
    _resolveAuthed = null;
  }
}

function onAuthenticated(session) {
  if (_authHandling) return _authHandling;
  _authHandling = (async () => {
    try {
      if (await ensureServerReadySession(session)) {
        if (!_authReadySettled) {
          resolveAuthedWaiter();
        } else {
          location.reload();
        }
      } else {
        setAuthError('Could not verify your session on the server. Try again.');
        applySession(null);
      }
    } finally {
      _authHandling = null;
    }
  })();
  return _authHandling;
}

async function loadConfig() {
  const res = await fetch('/api/config');
  if (!res.ok) throw new Error('Could not load app config');
  return res.json();
}

function bindSignInForm() {
  const form = document.getElementById('authGateForm');
  const btn = document.getElementById('authGateSubmit');
  if (!form || !btn || !_supabase) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    setAuthError('');
    const email = document.getElementById('authGateEmail')?.value?.trim();
    const password = document.getElementById('authGatePassword')?.value;
    if (!email || !password) {
      setAuthError('Enter email and password.');
      return;
    }
    btn.disabled = true;
    try {
      const { data, error } = await _supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setAuthError(error.message || 'Sign in failed.');
        return;
      }
      if (!data.session) {
        setAuthError('No session returned. Use the link from your invite email if this is your first sign-in.');
        return;
      }
      await onAuthenticated(data.session);
    } finally {
      btn.disabled = false;
    }
  });
}

/**
 * Resolve only once a valid session exists. The app awaits this before booting,
 * so when auth is required the gate stays up (no boot-curtain flicker behind it).
 */
export async function initAuthGate() {
  ensureAuthReadyPromise();
  setOverlayVisible(true);
  document.documentElement.setAttribute('data-auth-required', '1');
  try {
    _config = await loadConfig();
  } catch {
    setAuthError('Could not load server config. Start python server.py and reload.');
    return new Promise(() => {});
  }
  _authRequired = !!_config.authRequired;
  _localProfiles = !!_config.localProfiles;
  if (!_authRequired) {
    setOverlayVisible(false);
    document.documentElement.removeAttribute('data-auth-required');
    markAuthReady();
    return;
  }

  const url = _config.supabaseUrl;
  const key = _config.supabaseAnonKey;
  if (!url || !key) {
    setAuthError('Server auth is enabled but Supabase URL/key are missing.');
    setOverlayVisible(true);
    return new Promise(() => {}); // unrecoverable without config; stay gated
  }

  const { createClient } = await import(SUPABASE_MODULE);
  _supabase = createClient(url, key, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });

  bindSignInForm();

  const { data: { session } } = await _supabase.auth.getSession();
  if (session && (await ensureServerReadySession(session))) {
    markAuthReady();
    return;
  }
  if (session) {
    await _supabase.auth.signOut();
    applySession(null);
  }

  _authedPromise = new Promise((resolve) => { _resolveAuthed = resolve; });
  setOverlayVisible(true);
  _supabase.auth.onAuthStateChange((_event, nextSession) => {
    if (nextSession?.access_token) {
      onAuthenticated(nextSession);
    } else if (!_authReadySettled) {
      applySession(null);
    } else {
      handleApiUnauthorized();
    }
  });
  await _authedPromise;
  markAuthReady();
}

/** Re-show gate after API 401 (session expired). Skipped during boot curtain. */
export function handleApiUnauthorized(message = 'Session expired. Sign in again.') {
  if (!_authRequired) return;
  if (typeof document !== 'undefined'
    && document.documentElement?.hasAttribute('data-boot-loading')) {
    return;
  }
  _accessToken = null;
  _accountProfileId = '';
  setOverlayVisible(true);
  setAuthError(message);
}

/** Try refresh once; parallel callers share one in-flight refresh. */
export async function refreshAccessToken() {
  if (!_supabase) return null;
  if (_refreshInFlight) return _refreshInFlight;
  _refreshInFlight = (async () => {
    try {
      const { data, error } = await _supabase.auth.refreshSession();
      if (error || !data.session) return null;
      applySession(data.session);
      if (!(await probeServerToken())) {
        applySession(null);
        return null;
      }
      return _accessToken;
    } finally {
      _refreshInFlight = null;
    }
  })();
  return _refreshInFlight;
}

export async function signOutAccount(opts = {}) {
  if (_supabase) await _supabase.auth.signOut();
  _accessToken = null;
  _accountProfileId = '';
  if (opts.intentional) {
    setOverlayVisible(true);
    setAuthError('');
  } else {
    handleApiUnauthorized();
  }
}
