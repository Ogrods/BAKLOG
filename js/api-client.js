/** Headers required for mutating BAKLOG API calls (localhost CSRF guard). */
import {
  getAccessToken,
  handleApiUnauthorized,
  isAccountAuthMode,
  refreshAccessToken,
  whenAuthReady,
} from './auth-gate.js';

export const BAKLOG_LOCAL_HEADER = 'X-BAKLOG-Local';
export const BAKLOG_LOCAL_HEADER_VALUE = '1';

const _DATA_JSON_RE = /^\/games_[a-z0-9_]+\.json$/i;
const _CACHE_META_RE = /^\/cache\/(hltb_map|steam_review_map|cross_store_images_meta|steam_tags_meta|fx_rates)\.json$/i;

/** Normalize catalog paths (library-load uses ``games_steam.json`` without a leading /). */
function pathOnly(url) {
  const s = String(url).split('?')[0];
  return s.startsWith('/') ? s : `/${s}`;
}

function isApiUrl(url) {
  const s = String(url);
  if (s.startsWith('/api/')) return true;
  if (/^https?:\/\//i.test(s)) {
    try {
      return new URL(s).pathname.startsWith('/api/');
    } catch {
      return false;
    }
  }
  return false;
}

function isDataUrl(url) {
  const s = pathOnly(url);
  if (_DATA_JSON_RE.test(s)) return true;
  if (s === '/itad_prices.json' || s === '/free_claims.json') return true;
  if (_CACHE_META_RE.test(s)) return true;
  return false;
}

function shouldAttachBearer(url) {
  if (!isAccountAuthMode()) return false;
  return isApiUrl(url) || isDataUrl(url);
}

/** Block protected fetches until initAuthGate has a server-valid JWT (or auth is off). */
function needsAuthReady(url) {
  if (!isAccountAuthMode()) return false;
  if (pathOnly(url) === '/api/config') return false;
  return isApiUrl(url) || isDataUrl(url);
}

function mergeAuthHeaders(url, init = {}, { includeLocal = false } = {}) {
  const token = getAccessToken();
  if (init.headers instanceof Headers) {
    const h = new Headers(init.headers);
    if (includeLocal) h.set(BAKLOG_LOCAL_HEADER, BAKLOG_LOCAL_HEADER_VALUE);
    if (token && shouldAttachBearer(url)) h.set('Authorization', `Bearer ${token}`);
    return { ...init, headers: h };
  }
  const headers = {
    ...(init.headers && typeof init.headers === 'object' ? init.headers : {}),
  };
  if (includeLocal) headers[BAKLOG_LOCAL_HEADER] = BAKLOG_LOCAL_HEADER_VALUE;
  if (token && shouldAttachBearer(url)) {
    headers.Authorization = `Bearer ${token}`;
  }
  return { ...init, headers };
}

/** Merge the local-only header into fetch init (plain object headers). */
export function withBaklogHeaders(init = {}) {
  const url = init.url || '';
  return mergeAuthHeaders(url, init, { includeLocal: true });
}

function attachAuthHeaders(url, init = {}) {
  return mergeAuthHeaders(url, init, { includeLocal: false });
}

function mergeFetchInit(url, init, method) {
  if (method !== 'GET' && method !== 'HEAD') {
    return withBaklogHeaders({ ...init, url });
  }
  return attachAuthHeaders(url, init);
}

async function fetchWithAuthRetry(url, init, method) {
  if (needsAuthReady(url)) await whenAuthReady();
  let merged = mergeFetchInit(url, init, method);
  let res = await fetch(url, merged);
  if (res.status === 401 && isAccountAuthMode() && shouldAttachBearer(url)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      merged = mergeFetchInit(url, init, method);
      res = await fetch(url, merged);
    }
    if (res.status === 401) {
      const duringBoot = typeof document !== 'undefined'
        && document.documentElement?.hasAttribute('data-boot-loading');
      if (!duringBoot) handleApiUnauthorized();
    }
  }
  return res;
}

/** GET/HEAD for catalog + cache JSON — attaches Bearer in account auth mode. */
export async function dataFetch(url, init = {}) {
  const method = (init.method || 'GET').toUpperCase();
  return fetchWithAuthRetry(url, init, method);
}

/** fetch() wrapper that adds X-BAKLOG-Local for POST/PUT/DELETE and Bearer for /api/*. */
export async function baklogFetch(url, init = {}) {
  const method = (init.method || 'GET').toUpperCase();
  return fetchWithAuthRetry(url, init, method);
}

/** Mint a single-use SSE ticket (EventSource cannot send Authorization). */
export async function mintStreamTicket() {
  if (!isAccountAuthMode()) return null;
  const res = await baklogFetch('/api/auth/stream-ticket', { method: 'POST' });
  if (!res.ok) return null;
  const data = await res.json().catch(() => ({}));
  return data.ticket || null;
}

/** Append ?ticket= for authenticated SSE streams. */
export async function urlWithStreamTicket(url) {
  const ticket = await mintStreamTicket();
  if (!ticket) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
}
