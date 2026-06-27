/** Fetch helpers for fetcher health / runner. */
import { baklogFetch, withBaklogHeaders } from '../api-client.js';

export const FETCH_TIMEOUT_MS = 15_000;

function _isApiUrl(url) {
  const s = String(url);
  return s.startsWith('/api/') || s.includes('/api/');
}

/** Fetch with timeout; throws when the server does not respond in time. */
export async function fetchWithTimeout(url, options = {}, ms = FETCH_TIMEOUT_MS) {
  const method = (options.method || 'GET').toUpperCase();
  const merged = method === 'GET' || method === 'HEAD' ? options : withBaklogHeaders(options);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  const doFetch = _isApiUrl(url) ? baklogFetch : fetch;
  try {
    return await doFetch(url, { ...merged, signal: ctrl.signal });
  } catch (err) {
    if (err?.name === 'AbortError') {
      throw new Error('server not responding');
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
