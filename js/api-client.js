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

/** Session key shared with update-check.js (avoid import cycle). */
const UPDATE_SUPPRESS_NETWORK_KEY = "baklog.suppressNetworkErrors";

/** Paths that poll during Connect and briefly  fail when the HTTP thread is busy. */
const CONNECT_SUPPRESS_PATH_RE = /\/api\/(runs\b|auth\/status\b|fetchers\b)/i;

/** @type {number} epoch ms; 0 = off */
let _connectNetworkSuppressUntil = 0;
/** @type {ReturnType<typeof setTimeout> | null} */
let _connectNetworkSuppressTimer = null;
/** Nested Connect flows (refcount); suppress stays until depth hits 0 or the timer. */
let _connectNetworkSuppressDepth = 0;

function _clearConnectNetworkSuppressState() {
  _connectNetworkSuppressUntil = 0;
  _connectNetworkSuppressDepth = 0;
  if (_connectNetworkSuppressTimer) {
    clearTimeout(_connectNetworkSuppressTimer);
    _connectNetworkSuppressTimer = null;
  }
  if (typeof window !== "undefined") {
    window.__baklogConnectNetworkSuppressUntil = 0;
  }
}

/**
 * Time-boxed suppress of NetworkError toasts for Connect-adjacent polls.
 * Does not weaken auth - only skips reportError for Failed-to-fetch on
 * /api/runs, /api/auth/status, and /api/fetchers while a headed Connect is active.
 * Refcounted: each begin must be matched by end; sibling Connects do not cancel each other.
 * @param {number} [ms=120000]
 */
export function beginConnectNetworkSuppress(ms = 120_000) {
  _connectNetworkSuppressDepth += 1;
  const until = Date.now() + Math.max(1_000, Number(ms) || 120_000);
  _connectNetworkSuppressUntil = Math.max(_connectNetworkSuppressUntil, until);
  if (typeof window !== "undefined") {
    window.__baklogConnectNetworkSuppressUntil = _connectNetworkSuppressUntil;
  }
  if (_connectNetworkSuppressTimer) {
    clearTimeout(_connectNetworkSuppressTimer);
  }
  _connectNetworkSuppressTimer = setTimeout(() => {
    _clearConnectNetworkSuppressState();
  }, Math.max(1_000, _connectNetworkSuppressUntil - Date.now()));
}

export function endConnectNetworkSuppress() {
  if (_connectNetworkSuppressDepth > 0) _connectNetworkSuppressDepth -= 1;
  if (_connectNetworkSuppressDepth > 0) return;
  _clearConnectNetworkSuppressState();
}

function connectSuppressUntil() {
  const winUntil =
    typeof window !== "undefined"
      ? Number(window.__baklogConnectNetworkSuppressUntil) || 0
      : 0;
  return Math.max(_connectNetworkSuppressUntil, winUntil);
}

/** True while any Connect suppress window is live (refcount + until clock). */
export function isConnectNetworkSuppressActive() {
  return (
    _connectNetworkSuppressDepth > 0 && Date.now() <= connectSuppressUntil()
  );
}

function shouldSuppressConnectNetworkError(url) {
  if (!isConnectNetworkSuppressActive()) return false;
  return CONNECT_SUPPRESS_PATH_RE.test(String(url || ""));
}

/** Soft-fail Connect poll URLs while suppress is active (do not flip apiAvailable). */
export function shouldSoftFailConnectPoll(url) {
  return shouldSuppressConnectNetworkError(url);
}

function shouldSuppressNetworkErrors() {
  if (typeof window === "undefined") return false;
  if (window.__baklogSuppressNetworkErrors) return true;
  try {
    return window.sessionStorage?.getItem(UPDATE_SUPPRESS_NETWORK_KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Low-level fetch with single retry + descriptive error for network failures.
 * Narrow catch: only intercepts TypeError with "Failed to fetch" (server unreachable).
 * All other errors propagate immediately so AbortError, timeout, etc. keep their
 * original semantics for callers that handle them.
 * Forwards AbortSignal from merged.init (callers pass signal via baklogFetch init).
 */
async function _fetchWithRetry(
  url,
  merged,
  { retries = 1, delayMs = 500 } = {},
) {
  const signal = merged?.signal;
  for (let attempt = 0; attempt <= retries; attempt++) {
    if (signal?.aborted) {
      const reason = signal.reason;
      if (reason instanceof Error) throw reason;
      const abortErr = new DOMException(
        reason != null ? String(reason) : "The operation was aborted.",
        "AbortError",
      );
      throw abortErr;
    }
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
        await new Promise((r, reject) => {
          if (signal?.aborted) {
            reject(
              signal.reason instanceof Error
                ? signal.reason
                : new DOMException("The operation was aborted.", "AbortError"),
            );
            return;
          }
          const t = setTimeout(r, delayMs);
          signal?.addEventListener(
            "abort",
            () => {
              clearTimeout(t);
              reject(
                signal.reason instanceof Error
                  ? signal.reason
                  : new DOMException("The operation was aborted.", "AbortError"),
              );
            },
            { once: true },
          );
        });
        continue;
      }
      // Last attempt exhausted — produce a descriptive error + surface via toast
      const descriptive = new Error(
        `Server unreachable: BAKLOG is not responding at ${url}. Check that the server is running.`,
      );
      descriptive.name = "NetworkError";
      // Suppress error persistence when the server is expected to be down
      // (e.g. during update apply/restart). Window flag covers the live poll;
      // sessionStorage survives the post-apply reload until boot clears it.
      // Connect also time-boxes suppress for a few busy poll URLs only.
      const suppress =
        shouldSuppressNetworkErrors() ||
        shouldSuppressConnectNetworkError(url);
      if (typeof window === "undefined" || !suppress) {
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

/** fetch() wrapper that adds X-BAKLOG-Local for POST/PUT/DELETE and Bearer for /api/*.
 *  Pass AbortSignal via init.signal — it is forwarded through auth merge into fetch. */
export async function baklogFetch(url, init = {}) {
  const method = (init.method || "GET").toUpperCase();
  return fetchWithAuthRetry(url, init, method);
}

/** Mint a limited-reuse SSE ticket (EventSource cannot send Authorization).
 *  Pass runId for fetcher streams, or sessionId for Connect auth streams. */
export async function mintStreamTicket(runIdOrOpts = null, maybeOpts = undefined) {
  if (!isAccountAuthMode()) return null;
  let runId = null;
  let sessionId = null;
  if (runIdOrOpts && typeof runIdOrOpts === "object" && !Array.isArray(runIdOrOpts)) {
    runId = runIdOrOpts.runId ?? null;
    sessionId = runIdOrOpts.sessionId ?? null;
  } else {
    runId = runIdOrOpts;
    if (maybeOpts && typeof maybeOpts === "object") {
      sessionId = maybeOpts.sessionId ?? null;
    }
  }
  const payload = {};
  if (sessionId) payload.session_id = sessionId;
  else if (runId) payload.run_id = runId;
  const body = Object.keys(payload).length ? JSON.stringify(payload) : undefined;
  const res = await baklogFetch("/api/auth/stream-ticket", {
    method: "POST",
    body,
  });
  if (!res.ok) return null;
  const data = await res.json().catch(() => ({}));
  return data.ticket || null;
}

/** Append ?ticket= for authenticated SSE streams. */
export async function urlWithStreamTicket(url, { runId = null, sessionId = null } = {}) {
  if (!isAccountAuthMode()) return url;
  const ticket = await mintStreamTicket({ runId, sessionId });
  if (!ticket) {
    throw new Error("Could not mint SSE stream ticket");
  }
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}ticket=${encodeURIComponent(ticket)}`;
}
