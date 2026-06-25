/**
 * Connections provider status cache (decoupled from rail/card rendering).
 */
import { FETCHER_AUTH_PROVIDER } from './fetcher-registry.js';
import { state } from './state.js';

let authStatus = [];
let _authStatusLoaded = false;

/** Read-only snapshot for connections.js rendering. */
export function getAuthStatusSnapshot() {
  return authStatus;
}

/** @param {Array<object>} providers */
export function setAuthStatusSnapshot(providers) {
  authStatus = providers || [];
  _authStatusLoaded = true;
}

/** Cache provider rows from GET /api/auth/status (dashboard poll + refresh). */
export function ingestAuthStatusProviders(providers) {
  setAuthStatusSnapshot(providers);
  try {
    document.dispatchEvent(
      new CustomEvent('baklog:auth-status', { detail: { providers: authStatus } }),
    );
  } catch (_) { /* no DOM (tests) */ }
}

/** Cached Connections status for a provider key, or null if unknown. */
export function providerStatus(provider) {
  const row = authStatus.find(p => p.key === provider);
  return row?.status ?? null;
}

/** True once /api/auth/status has resolved at least once this session. */
export function authStatusLoaded() {
  return _authStatusLoaded;
}

/** Map fetcher chip key -> auth provider for reconnect hints. */
export function providerForFetcher(key) {
  return FETCHER_AUTH_PROVIDER[key] || null;
}

/** True when the given auth provider is currently connected. */
export function isProviderConnected(provider) {
  return authStatus.some(p => p.key === provider && p.status === 'connected');
}

/** Number of auth providers with status === 'connected'. */
export function connectedProviderCount() {
  return authStatus.filter(p => p.status === 'connected').length;
}

/** True when this profile has itch.io API key or local app source enabled. */
export function isItchSetup() {
  const api = providerStatus('itch');
  if (api === 'connected' || api === 'unverified') return true;
  return providerStatus('itch_local') === 'connected';
}

/** True when a previously fetched itch catalog is still on disk in this profile. */
export function hasCachedItchLibrary() {
  const rows = state.itchGames;
  if (Array.isArray(rows) && rows.length > 0) return true;
  const cached = state.libraryMeta?.itch?.games;
  return Array.isArray(cached) && cached.length > 0;
}

/** itch.io tab: connected setup or a cached library worth browsing. */
export function isItchTabAvailable() {
  return isItchSetup() || hasCachedItchLibrary();
}

/** itch rows surfaced in tables, summary chips, and dashboard recap. */
export function visibleItchGames() {
  return Array.isArray(state.itchGames) ? state.itchGames : [];
}
