/** Headers required for mutating BAKLOG API calls (localhost CSRF guard). */
import {
  getAccessToken,
  handleApiUnauthorized,
  isAccountAuthMode,
  refreshAccessToken,
  whenAuthReady,
} from "./auth-gate.js";
import { reportError } from "./error-boundary.js";

export const BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local";
export const BAKLOG_LOCAL_HEADER_VALUE = "1";

const _DATA_JSON_RE = /^\/games_[a-z0-9_]+\.json$/i;
const _CACHE_META_RE =
  /^\/cache\/(hltb_map|steam_review_map|cross_store_images_meta|steam_tags_meta|protondb_map|fx_rates)\.json$/i;

/** Normalize catalog paths (library-load uses ``games_steam.json`` without a leading /). */
function pathOnly(url) {
  const s = String(url).split("?")[0];
  return s.startsWith("/") ? s : `/${s}`;
}

function isApiUrl(url) {
  const s = String(url);
  if (s.startsWith("/api/")) return true;
  if (/^https?:\/\//i.test(s)) {
    try {
      return new URL(s).pathname.startsWith("/api/");
    } catch {
      return false;
    }
  }
  return false;
}

function isDataUrl(url) {
  const s = pathOnly(url);
  if (_DATA_JSON_RE.test(s)) return true;
  if (
    s === "/itad_prices.json" ||
    s === "/free_claims.json" ||
    s === "/sponsors.json"
  )
    return true;
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
  if (pathOnly(url) === "/api/config") return false;
  return isApiUrl(url) || isDataUrl(url);
}

function mergeAuthHeaders(url, init = {}, { includeLocal = false } = {}) {
  const token = getAccessToken();
  if (init.headers instanceof Headers) {
    const h = new Headers(init.headers);
    if (includeLocal) h.set(BAKLOG_LOCAL_HEADER, BAKLOG_LOCAL_HEADER_VALUE);
    if (token && shouldAttachBearer(url))
      h.set("Authorization", `Bearer ${token}`);
    return { ...init, headers: h };
  }
  const headers = {
    ...(init.headers && typeof init.headers === "object" ? init.headers : {}),
  };
  if (includeLocal) headers[BAKLOG_LOCAL_HEADER] = BAKLOG_LOCAL_HEADER_VALUE;
  if (token && shouldAttachBearer(url)) {
    headers.Authorization = `Bearer ${token}`;
  }
  return { ...init, headers };
}

/** Merge the local-only header into fetch init (plain object headers). */
export function withBaklogHeaders(init = {}) {
  const url = init.url || "";
  return mergeAuthHeaders(url, init, { includeLocal: true });
}

function attachAuthHeaders(url, init = {}) {
  return mergeAuthHeaders(url, init, { includeLocal: false });
}

function mergeFetchInit(url, init, method) {
  if (method !== "GET" && method !== "HEAD") {
    return withBaklogHeaders({ ...init, url });
  }
  return attachAuthHeaders(url, init);
}

const _NETWORK_ERROR_RE = /Failed to fetch|network error|NetworkError/i;

/**
 * Low-level fetch with single retry + descriptive error for network failures.
 * Narrow catch: only intercepts TypeError with "Failed to fetch" (server unreachable).
 * All other errors propagate immediately so AbortError, timeout, etc. keep their
 * original semantics for callers that handle them.
 */
async function _fetchWithRetry(
  url,
  merged,
  { retries = 1, delayMs = 500 } = {},
) {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      return await fetch(url, merged);
    } catch (err) {
      const isNetworkError =
        err?.constructor?.name === "TypeError" &&
        typeof err?.message === "string" &&
        _NETWORK_ERROR_RE.test(err.message);
      // Re-throw non-network errors immediately (e.g. AbortError from fetchWithTimeout)
      if (!isNetworkError) throw err;
      if (attempt < retries) {
        await new Promise((r) => setTimeout(r, delayMs));
        continue;
      }
      // Last attempt exhausted — produce a descriptive error + surface via toast
      const descriptive = new Error(
        `Server unreachable: BAKLOG is not responding at ${url}. Check that the server is running.`,
      );
      descriptive.name = "NetworkError";
      // Suppress error persistence when the server is expected to be down
      // (e.g. during update apply/restart). The poll caller handles retries;
      // we don't want transient downtime logged as a permanent error.
      if (
        typeof window === "undefined" ||
        !window.__baklogSuppressNetworkErrors
      ) {
        reportError(descriptive, {
          source: "fetchWithAuthRetry",
          kind: "network",
        });
      }
      throw descriptive;
    }
  }
}

async function fetchWithAuthRetry(url, init, method) {
  if (needsAuthReady(url)) await whenAuthReady();
  let merged = mergeFetchInit(url, init, method);
  let res = await _fetchWithRetry(url, merged);
  if (res.status === 401 && isAccountAuthMode() && shouldAttachBearer(url)) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      merged = mergeFetchInit(url, init, method);
      res = await _fetchWithRetry(url, merged);
    }
    if (res.status === 401) {
      const duringBoot =
        typeof document !== "undefined" &&
        document.documentElement?.hasAttribute("data-boot-loading");
      if (!duringBoot) handleApiUnauthorized();
    }
  }
  return res;
}

/** GET/HEAD for catalog + cache JSON — attaches Bearer in account auth mode. */
export async function dataFetch(url, init = {}) {
  const method = (init.method || "GET").toUpperCase();
  return fetchWithAuthRetry(url, init, method);
}

/** fetch() wrapper that adds X-BAKLOG-Local for POST/PUT/DELETE and Bearer for /api/*. */
export async function baklogFetch(url, init = {}) {
  const method = (init.method || "GET").toUpperCase();
  return fetchWithAuthRetry(url, init, method);
}

/** Mint a limited-reuse SSE ticket (EventSource cannot send Authorization). */
export async function mintStreamTicket(runId = null) {
  if (!isAccountAuthMode()) return null;
  const body = runId ? JSON.stringify({ run_id: runId }) : undefined;
  const res = await baklogFetch("/api/auth/stream-ticket", {
    method: "POST",
    body,
  });
  if (!res.ok) return null;
  const data = await res.json().catch(() => ({}));
  return data.ticket || null;
}

/** Append ?ticket= for authenticated SSE streams. */
export async function urlWithStreamTicket(url, { runId = null } = {}) {
  if (!isAccountAuthMode()) return url;
  const ticket = await mintStreamTicket(runId);
  if (!ticket) {
    throw new Error("Could not mint SSE stream ticket");
  }
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
}
