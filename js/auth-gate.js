/**
 * Optional Supabase account gate - blocks the app until the user signs in.
 * Config from GET /api/config; session stored by Supabase client in localStorage.
 */

import { stopBootTipRotation } from "./tips.js";

// Loaded lazily inside initAuthGate so merely importing this module (e.g. via
// api-client.js in unit tests) never triggers the remote esm.sh fetch, and the
// network request only happens when account auth is actually enabled.
/** Dev: js/vendor; built chunks live under dist/js/chunks/ so use /dist/vendor. */
function supabaseModuleUrl() {
  if (import.meta.url.includes("/dist/js/")) {
    return "/dist/vendor/supabase-js.mjs";
  }
  return "./vendor/supabase-js.mjs";
}

let _config = null;
let _supabase = null;
let _accessToken = null;
let _accountEmail = "";
let _authRequired = false;
let _resolveAuthed = null;
let _authedPromise = null;
let _authReadyPromise = null;
let _resolveAuthReady = null;
let _authReadySettled = false;
let _refreshInFlight = null;
let _authHandling = null;
let _accountProfileId = "";
let _localProfiles = false;
let _plan = "free";
let _licenseActivation = false;
let _proCheckoutEnabled = false;
let _proCheckout = { monthly: "", yearly: "" };
let _lastSessionProbeStatus = 0;
const SESSION_PROBE_ATTEMPTS = 6;
const SESSION_PROBE_DELAY_MS = 500;
const _planListeners = new Set();

function sessionProbeDelay(attempt) {
  return new Promise((resolve) => {
    setTimeout(resolve, SESSION_PROBE_DELAY_MS * (attempt + 1));
  });
}

/** Subscribe to plan changes (free ↔ pro). Returns unsubscribe. */
export function onPlanChange(fn) {
  _planListeners.add(fn);
  return () => {
    _planListeners.delete(fn);
  };
}

function setPlan(plan) {
  if (typeof plan !== "string" || !plan || plan === _plan) return;
  const prev = _plan;
  _plan = plan;
  for (const fn of _planListeners) {
    try {
      fn(_plan, prev);
    } catch (_) {
      /* listener */
    }
  }
}

const DEBUG_PRO_STORAGE_KEY = "baklog-debug-pro";

/** True when running on a local dev host (127.0.0.1 / localhost). */
function isLocalDevHost() {
  if (typeof window === "undefined") return false;
  try {
    const host = (location.hostname || "").toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  } catch (_) {
    return false;
  }
}

/** Dev-only Pro override: `?pro=1` or localStorage `baklog-debug-pro=1` on localhost only. */
export function isDebugProEnabled() {
  if (!isLocalDevHost()) return false;
  try {
    if (localStorage.getItem(DEBUG_PRO_STORAGE_KEY) === "1") return true;
  } catch (_) {
    /* private mode */
  }
  try {
    const q = new URLSearchParams(location.search);
    if (q.has("pro") && q.get("pro") !== "0") return true;
  } catch (_) {
    /* file:// */
  }
  return false;
}

export function isAccountAuthMode() {
  return !!_authRequired;
}

export function isLocalProfilesEnabled() {
  return _localProfiles;
}

/** Effective plan from GET /api/config ("free" | "pro"). */
export function getPlan() {
  if (isDebugProEnabled()) return "pro";
  return _plan;
}

/** True for the paid tier (server-side background refresh, etc.). */
export function isPro() {
  if (isDebugProEnabled()) return true;
  return _plan === "pro";
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
  const ov = document.getElementById("authGateOverlay");
  if (!ov) return;
  if (show) {
    ov.hidden = false;
    ov.setAttribute("aria-hidden", "false");
    document.documentElement.setAttribute("data-auth-required", "1");
    try {
      stopBootTipRotation();
    } catch (_) {
      /* ignore */
    }
  } else {
    ov.hidden = true;
    ov.setAttribute("aria-hidden", "true");
    document.documentElement.removeAttribute("data-auth-required");
  }
}

function setAuthError(msg) {
  const el = document.getElementById("authGateError");
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.classList.remove("hidden");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
  }
}

function setPanelMessage(id, msg, { success = false } = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  if (msg) {
    el.textContent = msg;
    el.classList.remove("hidden");
    if (success) el.classList.add("auth-gate-success");
    else el.classList.remove("auth-gate-success");
  } else {
    el.textContent = "";
    el.classList.add("hidden");
    el.classList.remove("auth-gate-success");
  }
}

const AUTH_PANEL_COPY = {
  signin: {
    title: "Sign in to BAKLOG",
    hint: "Sign in with your BAKLOG account. New here? Create a free account below.",
  },
  signup: {
    title: "Create your BAKLOG account",
    hint: "Free account for beta. Your library stays on this PC; we only store your email for sign-in.",
  },
  forgot: {
    title: "Reset your password",
    hint: "Enter your account email. We will send a link to choose a new password.",
  },
  reset: {
    title: "Choose a new password",
    hint: "Pick a new password for your BAKLOG account, then sign in.",
  },
};

function authConfirmRedirectUrl() {
  const fromConfig = _config?.authConfirmRedirectUrl;
  if (typeof fromConfig === "string" && fromConfig.trim())
    return fromConfig.trim();
  return "https://baklog.app/auth/confirmed";
}

function authResetRedirectUrl() {
  const fromConfig = _config?.authResetRedirectUrl;
  if (typeof fromConfig === "string" && fromConfig.trim())
    return fromConfig.trim();
  return "https://baklog.app/auth/reset";
}

function isEmailNotConfirmedError(error) {
  const msg = String(error?.message || error || "").toLowerCase();
  return (
    msg.includes("email not confirmed") ||
    msg.includes("not confirmed") ||
    msg.includes("confirm your email")
  );
}

function setResendConfirmVisible(show) {
  const btn = document.getElementById("authGateResendConfirm");
  if (!btn) return;
  btn.hidden = !show;
  btn.classList.toggle("hidden", !show);
}

/** Show sign-in, forgot-password, or reset-password panel on the auth gate. */
export function showAuthGatePanel(panel = "signin") {
  const key = AUTH_PANEL_COPY[panel] ? panel : "signin";
  const title = document.getElementById("authGateTitle");
  const hint = document.getElementById("authGateHint");
  if (title) title.textContent = AUTH_PANEL_COPY[key].title;
  if (hint) hint.textContent = AUTH_PANEL_COPY[key].hint;
  for (const form of document.querySelectorAll("[data-auth-panel]")) {
    const active = form.getAttribute("data-auth-panel") === key;
    form.hidden = !active;
    form.classList.toggle("hidden", !active);
  }
  if (key === "signin") {
    setAuthError("");
    setPanelMessage("authGateSignInSuccess", "");
    setResendConfirmVisible(false);
  }
  if (key === "signup") {
    setPanelMessage("authGateSignupError", "");
    setPanelMessage("authGateSignupSuccess", "");
  }
  if (key === "forgot") {
    setPanelMessage("authGateForgotError", "");
    setPanelMessage("authGateForgotSuccess", "");
  }
  if (key === "reset") setPanelMessage("authGateResetError", "");
}

function applyConfigEntitlement(config) {
  if (!config || typeof config !== "object") return;
  if (typeof config.plan === "string" && config.plan) setPlan(config.plan);
  _licenseActivation = !!config.licenseActivation;
  _proCheckoutEnabled = !!config.proCheckoutEnabled;
  const checkout = config.proCheckout;
  _proCheckout = {
    monthly: checkout?.monthly || "",
    yearly: checkout?.yearly || "",
  };
}

export function licenseActivationEnabled() {
  return _licenseActivation;
}

export function proCheckoutEnabled() {
  return _proCheckoutEnabled;
}

export function proCheckoutUrls() {
  return { ..._proCheckout };
}

/** Re-read plan from the server (JWT session probe or /api/config). */
export async function refreshAccountPlan() {
  try {
    if (_authRequired && _accessToken) {
      await refreshAccessToken();
      const res = await fetch("/api/auth/session", {
        headers: { Authorization: `Bearer ${_accessToken}` },
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.plan === "string" && data.plan) {
          setPlan(data.plan);
          return _plan;
        }
      }
    }
    const headers = _accessToken
      ? { Authorization: `Bearer ${_accessToken}` }
      : undefined;
    const res = await fetch("/api/config", headers ? { headers } : undefined);
    if (res.ok) applyConfigEntitlement(await res.json());
  } catch {
    /* keep last known plan */
  }
  return _plan;
}

function applySession(session) {
  _accessToken = session?.access_token || null;
  _accountEmail = session?.user?.email || _accountEmail;
  if (_accessToken) {
    setOverlayVisible(false);
    setAuthError("");
  } else {
    setOverlayVisible(true);
  }
}

/** Supabase refresh failures that mean local storage is stale — clear and re-prompt. */
function isStaleRefreshTokenError(error) {
  const msg = String(error?.message || error || "").toLowerCase();
  return msg.includes("refresh token") || msg.includes("invalid refresh");
}

/** Drop a dead Supabase session from localStorage so auto-refresh stops retrying. */
async function clearStaleAuthSession() {
  if (!_supabase) return;
  try {
    await _supabase.auth.signOut();
  } catch {
    /* best-effort */
  }
  _accessToken = null;
  _accountProfileId = "";
}

/** Verify the current bearer is accepted by server.py before boot continues. */
async function probeServerToken() {
  if (!_accessToken) return false;
  try {
    const res = await fetch("/api/auth/session", {
      headers: { Authorization: `Bearer ${_accessToken}` },
    });
    if (!res.ok) {
      _lastSessionProbeStatus = res.status;
      return false;
    }
    const data = await res.json();
    if (data.profile) _accountProfileId = String(data.profile);
    if (data.email) _accountEmail = data.email;
    if (typeof data.plan === "string" && data.plan) setPlan(data.plan);
    const ok = !!data.ok;
    if (ok && data.refreshSession && _supabase) {
      const { data: refData, error } = await _supabase.auth.refreshSession();
      if (!error && refData.session) applySession(refData.session);
      // Re-probe for updated plan claim; do not fail sign-in on a transient miss.
      await probeServerTokenWithRetry(2);
    }
    return ok;
  } catch {
    return false;
  }
}

async function probeServerTokenWithRetry(attempts = SESSION_PROBE_ATTEMPTS) {
  for (let i = 0; i < attempts; i++) {
    if (await probeServerToken()) return true;
    if (i < attempts - 1) await sessionProbeDelay(i);
  }
  return false;
}

/**
 * Confirm the JWT works on the local server before bootstrap continues.
 * Uses the session token as-is first (fresh sign-in); refresh only if probe fails.
 */
async function ensureServerReadySession(session) {
  if (!session || !_supabase) return false;
  applySession(session);
  if (await probeServerTokenWithRetry()) return true;
  await refreshAccessToken();
  return probeServerTokenWithRetry(SESSION_PROBE_ATTEMPTS);
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
        const hint =
          _lastSessionProbeStatus === 401
            ? " Quit BAKLOG from the tray and restart once. If it persists, reinstall from the latest BAKLOG-Setup.exe."
            : "";
        setAuthError(
          `Could not verify your session on the server. Try again or refresh the page.${hint}`,
        );
        setOverlayVisible(true);
      }
    } finally {
      _authHandling = null;
    }
  })();
  return _authHandling;
}

async function loadConfig() {
  const res = await fetch("/api/config");
  if (!res.ok) throw new Error("Could not load app config");
  return res.json();
}

function bindSignInForm() {
  const form = document.getElementById("authGateForm");
  const btn = document.getElementById("authGateSubmit");
  if (!form || !btn || !_supabase) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setAuthError("");
    const email = document.getElementById("authGateEmail")?.value?.trim();
    const password = document.getElementById("authGatePassword")?.value;
    if (!email || !password) {
      setAuthError("Enter email and password.");
      return;
    }
    btn.disabled = true;
    try {
      const { data, error } = await _supabase.auth.signInWithPassword({
        email,
        password,
      });
      if (error) {
        if (isEmailNotConfirmedError(error)) {
          setAuthError(
            "Confirm your email first. Check your inbox, or resend the confirmation email below.",
          );
          setResendConfirmVisible(true);
        } else {
          setAuthError(error.message || "Sign in failed.");
          setResendConfirmVisible(false);
        }
        return;
      }
      setResendConfirmVisible(false);
      if (!data.session) {
        setAuthError(
          "No session returned. Confirm your email if you just signed up, then try again.",
        );
        return;
      }
      await onAuthenticated(data.session);
    } finally {
      btn.disabled = false;
    }
  });

  document
    .getElementById("authGateForgotLink")
    ?.addEventListener("click", () => {
      const email = document.getElementById("authGateEmail")?.value?.trim();
      const forgotEmail = document.getElementById("authGateForgotEmail");
      if (forgotEmail && email) forgotEmail.value = email;
      showAuthGatePanel("forgot");
    });

  document
    .getElementById("authGateCreateLink")
    ?.addEventListener("click", () => {
      const email = document.getElementById("authGateEmail")?.value?.trim();
      const signupEmail = document.getElementById("authGateSignupEmail");
      if (signupEmail && email) signupEmail.value = email;
      showAuthGatePanel("signup");
    });

  document
    .getElementById("authGateResendConfirm")
    ?.addEventListener("click", async () => {
      const email = document.getElementById("authGateEmail")?.value?.trim();
      if (!email) {
        setAuthError(
          "Enter your email above, then resend the confirmation email.",
        );
        return;
      }
      const btn = document.getElementById("authGateResendConfirm");
      if (btn) btn.disabled = true;
      try {
        const { error } = await _supabase.auth.resend({
          type: "signup",
          email,
          options: { emailRedirectTo: authConfirmRedirectUrl() },
        });
        if (error) {
          setAuthError(error.message || "Could not resend confirmation email.");
          return;
        }
        setAuthError("");
        setPanelMessage(
          "authGateSignInSuccess",
          "Confirmation email sent. Check your inbox, then sign in here.",
          { success: true },
        );
      } finally {
        if (btn) btn.disabled = false;
      }
    });
}

function bindSignUpForm() {
  const form = document.getElementById("authGateSignupForm");
  const btn = document.getElementById("authGateSignupSubmit");
  if (!form || !btn || !_supabase) return;

  document
    .getElementById("authGateSignupBack")
    ?.addEventListener("click", () => {
      showAuthGatePanel("signin");
    });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setPanelMessage("authGateSignupError", "");
    setPanelMessage("authGateSignupSuccess", "");
    const email = document.getElementById("authGateSignupEmail")?.value?.trim();
    const password =
      document.getElementById("authGateSignupPassword")?.value || "";
    const confirm =
      document.getElementById("authGateSignupConfirm")?.value || "";
    if (!email) {
      setPanelMessage("authGateSignupError", "Enter your email.");
      return;
    }
    if (password.length < 8) {
      setPanelMessage(
        "authGateSignupError",
        "Password must be at least 8 characters.",
      );
      return;
    }
    if (password !== confirm) {
      setPanelMessage("authGateSignupError", "Passwords do not match.");
      return;
    }
    btn.disabled = true;
    try {
      const { data, error } = await _supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: authConfirmRedirectUrl() },
      });
      if (error) {
        setPanelMessage(
          "authGateSignupError",
          error.message || "Could not create account.",
        );
        return;
      }
      if (data.session) {
        await onAuthenticated(data.session);
        return;
      }
      setPanelMessage(
        "authGateSignupSuccess",
        "Account created. We sent a confirmation email. You can confirm from any device. When it is confirmed, return to BAKLOG on this PC and sign in.",
        { success: true },
      );
      showAuthGatePanel("signin");
      setAuthError(
        "Waiting for confirmation? Check your inbox, then sign in here.",
      );
      const signInEmail = document.getElementById("authGateEmail");
      if (signInEmail) signInEmail.value = email;
    } finally {
      btn.disabled = false;
    }
  });
}

function bindForgotPasswordForm() {
  const form = document.getElementById("authGateForgotForm");
  const btn = document.getElementById("authGateForgotSubmit");
  if (!form || !btn || !_supabase) return;

  document
    .getElementById("authGateBackToSignIn")
    ?.addEventListener("click", () => {
      showAuthGatePanel("signin");
    });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setPanelMessage("authGateForgotError", "");
    setPanelMessage("authGateForgotSuccess", "");
    const email = document.getElementById("authGateForgotEmail")?.value?.trim();
    if (!email) {
      setPanelMessage("authGateForgotError", "Enter your account email.");
      return;
    }
    btn.disabled = true;
    try {
      const { error } = await _supabase.auth.resetPasswordForEmail(email, {
        redirectTo: authResetRedirectUrl(),
      });
      if (error) {
        setPanelMessage(
          "authGateForgotError",
          error.message || "Could not send reset email.",
        );
        return;
      }
      setPanelMessage(
        "authGateForgotSuccess",
        "If that email is registered, a reset link is on its way. Check your inbox.",
        { success: true },
      );
    } finally {
      btn.disabled = false;
    }
  });
}

function bindResetPasswordForm() {
  const form = document.getElementById("authGateResetForm");
  const btn = document.getElementById("authGateResetSubmit");
  if (!form || !btn || !_supabase) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    setPanelMessage("authGateResetError", "");
    const password =
      document.getElementById("authGateNewPassword")?.value || "";
    const confirm =
      document.getElementById("authGateConfirmPassword")?.value || "";
    if (password.length < 8) {
      setPanelMessage(
        "authGateResetError",
        "Password must be at least 8 characters.",
      );
      return;
    }
    if (password !== confirm) {
      setPanelMessage("authGateResetError", "Passwords do not match.");
      return;
    }
    btn.disabled = true;
    try {
      const { data, error } = await _supabase.auth.updateUser({ password });
      if (error) {
        setPanelMessage(
          "authGateResetError",
          error.message || "Could not update password.",
        );
        return;
      }
      if (data.session) {
        await onAuthenticated(data.session);
        return;
      }
      showAuthGatePanel("signin");
      setAuthError("Password updated. Sign in with your new password.");
    } finally {
      btn.disabled = false;
    }
  });
}

/**
 * Resolve only once a valid session exists. The app awaits this before booting.
 * Returning users keep the boot curtain until session probe succeeds; the sign-in
 * overlay is shown only when login is actually required (avoids curtain flicker).
 */
export async function initAuthGate() {
  ensureAuthReadyPromise();
  try {
    _config = await loadConfig();
  } catch {
    setAuthError(
      "Could not load server config. Start python server.py and reload.",
    );
    setOverlayVisible(true);
    return new Promise(() => {});
  }
  _authRequired = !!_config.authRequired;
  _localProfiles = !!_config.localProfiles;
  applyConfigEntitlement(_config);
  if (!_authRequired) {
    setOverlayVisible(false);
    markAuthReady();
    return;
  }

  const url = _config.supabaseUrl;
  const key = _config.supabaseAnonKey;
  if (!url || !key) {
    setAuthError("Server auth is enabled but Supabase URL/key are missing.");
    setOverlayVisible(true);
    return new Promise(() => {}); // unrecoverable without config; stay gated
  }

  const { createClient } = await import(supabaseModuleUrl());
  _supabase = createClient(url, key, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });

  bindSignInForm();
  bindSignUpForm();
  bindForgotPasswordForm();
  bindResetPasswordForm();
  showAuthGatePanel("signin");

  const {
    data: { session },
    error: sessionError,
  } = await _supabase.auth.getSession();
  if (sessionError && isStaleRefreshTokenError(sessionError)) {
    await clearStaleAuthSession();
  } else if (session && (await ensureServerReadySession(session))) {
    markAuthReady();
    return;
  } else if (session) {
    await clearStaleAuthSession();
  }

  _authedPromise = new Promise((resolve) => {
    _resolveAuthed = resolve;
  });
  setOverlayVisible(true);
  _supabase.auth.onAuthStateChange((event, nextSession) => {
    if (event === "PASSWORD_RECOVERY") {
      showAuthGatePanel("reset");
      setOverlayVisible(true);
      setAuthError("");
      return;
    }
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
export function handleApiUnauthorized(
  message = "Session expired. Sign in again.",
) {
  if (!_authRequired) return;
  if (
    typeof document !== "undefined" &&
    document.documentElement?.hasAttribute("data-boot-loading")
  ) {
    return;
  }
  _accessToken = null;
  _accountProfileId = "";
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
      if (error) {
        if (isStaleRefreshTokenError(error)) await clearStaleAuthSession();
        applySession(null);
        return null;
      }
      if (!data.session) return null;
      applySession(data.session);
      if (await probeServerTokenWithRetry(2)) return _accessToken;
      return null;
    } finally {
      _refreshInFlight = null;
    }
  })();
  return _refreshInFlight;
}

export async function signOutAccount(opts = {}) {
  if (_supabase) await _supabase.auth.signOut();
  _accessToken = null;
  _accountProfileId = "";
  if (opts.intentional) {
    showAuthGatePanel("signin");
    setOverlayVisible(true);
    setAuthError("");
  } else {
    handleApiUnauthorized();
  }
}
