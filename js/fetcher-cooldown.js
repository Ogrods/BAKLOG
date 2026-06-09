/**
 * Chip-level auth-failure backoff (escalating 5m -> 15m -> 60m).
 */
import { FETCHER_AUTH_PROVIDER } from './fetcher-registry.js';
import { LS_FETCHER_AUTH_COOLDOWN, profileScopedStorageKey } from './profiles.js';

const AUTH_COOLDOWN_STEPS_MS = [5 * 60_000, 15 * 60_000, 60 * 60_000];

/** @type {{ onCooldownExpire?: () => void, onMaxStrikes?: (key: string) => void, credentialsSatisfied?: (key: string) => boolean, connectProvider?: (key: string) => string | null }} */
let hooks = {};

export function configureFetcherCooldown(next) {
  hooks = { ...hooks, ...next };
}

function authCooldownLsKey() {
  return profileScopedStorageKey(LS_FETCHER_AUTH_COOLDOWN);
}

/** Escalating cooldown duration for the Nth consecutive auth failure (1-based). */
export function authCooldownDurationMs(strikes) {
  const i = Math.min(Math.max(strikes, 1), AUTH_COOLDOWN_STEPS_MS.length) - 1;
  return AUTH_COOLDOWN_STEPS_MS[i];
}

function loadAuthCooldowns() {
  const m = new Map();
  try {
    const raw = JSON.parse(localStorage.getItem(authCooldownLsKey()) || '{}');
    const now = Date.now();
    for (const [k, v] of Object.entries(raw)) {
      if (v && typeof v.until === 'number' && v.until > now) {
        m.set(k, { until: v.until, strikes: Number(v.strikes) || 1 });
      }
    }
  } catch (_) { /* corrupt or unavailable storage — start clean */ }
  return m;
}

/** @type {Map<string, { until: number, strikes: number }>} */
let authCooldowns = new Map();
let _profileScopedCooldownReady = false;
let authCooldownTimer = null;

/** Load profile-scoped cooldown map after auth/profile id is known. */
export function initAuthCooldowns() {
  if (_profileScopedCooldownReady) return;
  _profileScopedCooldownReady = true;
  authCooldowns = loadAuthCooldowns();
  if (authCooldowns.size) setTimeout(() => scheduleAuthCooldownTick(), 0);
}

export function resetAuthCooldownsForTest() {
  _profileScopedCooldownReady = false;
  authCooldowns = new Map();
  if (authCooldownTimer) {
    clearTimeout(authCooldownTimer);
    authCooldownTimer = null;
  }
}

function persistAuthCooldowns() {
  try {
    const obj = {};
    for (const [k, v] of authCooldowns) obj[k] = v;
    localStorage.setItem(authCooldownLsKey(), JSON.stringify(obj));
  } catch (_) { /* storage unavailable — in-memory map still enforces */ }
}

/** Record one auth failure for a fetcher key and (re)arm the escalating cooldown. */
export function noteAuthCooldownStrike(key) {
  initAuthCooldowns();
  const strikes = Math.min((authCooldowns.get(key)?.strikes || 0) + 1, AUTH_COOLDOWN_STEPS_MS.length);
  authCooldowns.set(key, { until: Date.now() + authCooldownDurationMs(strikes), strikes });
  persistAuthCooldowns();
  scheduleAuthCooldownTick();
  if (strikes >= AUTH_COOLDOWN_STEPS_MS.length && !hooks.credentialsSatisfied?.(key)) {
    const provider = hooks.connectProvider?.(key) || FETCHER_AUTH_PROVIDER[key];
    if (provider) hooks.onMaxStrikes?.(key, provider);
  }
}

function scheduleAuthCooldownTick() {
  if (authCooldownTimer) { clearTimeout(authCooldownTimer); authCooldownTimer = null; }
  let soonest = Infinity;
  for (const c of authCooldowns.values()) soonest = Math.min(soonest, c.until);
  if (!Number.isFinite(soonest)) return;
  const delay = Math.max(0, soonest - Date.now()) + 250;
  authCooldownTimer = setTimeout(() => {
    authCooldownTimer = null;
    for (const [k, c] of authCooldowns) { if (c.until <= Date.now()) authCooldowns.delete(k); }
    persistAuthCooldowns();
    try { hooks.onCooldownExpire?.(); } catch (_) { /* not mounted */ }
    scheduleAuthCooldownTick();
  }, delay);
}

export function clearAuthCooldown(key) {
  if (authCooldowns.delete(key)) persistAuthCooldowns();
}

/** Remaining cooldown for a fetcher key in ms, or 0. Self-heals on expiry or
 *  when the mapped provider is reconnected. */
export function authCooldownRemainingMs(key, isProviderConnected) {
  initAuthCooldowns();
  const c = authCooldowns.get(key);
  if (!c) return 0;
  if (isProviderConnected?.(key)) {
    clearAuthCooldown(key);
    return 0;
  }
  const rem = c.until - Date.now();
  if (rem <= 0) { clearAuthCooldown(key); return 0; }
  return rem;
}

/** Short label for a cooldown badge, e.g. "auth 5m" / "auth 1h". */
export function authCooldownLabel(ms) {
  const mins = Math.max(1, Math.ceil(ms / 60_000));
  return mins >= 60 ? `auth ${Math.round(mins / 60)}h` : `auth ${mins}m`;
}
