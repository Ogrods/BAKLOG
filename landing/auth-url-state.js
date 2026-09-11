/**
 * Parse Supabase auth redirect URL state (hash + query) for hosted landing pages.
 */

/** @param {string} search */
/** @param {string} hash */
export function parseConfirmRedirectState(search = '', hash = '') {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const error = params.get('error');
  if (error) {
    const desc = params.get('error_description') || error;
    return { status: 'error', message: desc };
  }
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw) return { status: 'unknown' };
  const hashParams = new URLSearchParams(raw);
  if (hashParams.get('error')) {
    return { status: 'error', message: hashParams.get('error_description') || hashParams.get('error') };
  }
  const type = hashParams.get('type') || '';
  if (hashParams.get('access_token') || type === 'signup' || type === 'email') {
    return { status: 'success' };
  }
  return { status: 'unknown' };
}

/** Strip sensitive tokens from the current URL (browser only). */
export function stripAuthHashFromUrl() {
  if (typeof history === 'undefined' || typeof location === 'undefined') return;
  if (!location.hash) return;
  try {
    history.replaceState(null, '', location.pathname + location.search);
  } catch {
    /* ignore */
  }
}

/** True when URL hash carries a password-recovery or invite setup token. */
export function hasRecoveryTokens(hash = '') {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw) return false;
  const params = new URLSearchParams(raw);
  const type = params.get('type') || '';
  return !!params.get('access_token') && (type === 'recovery' || type === 'invite');
}
