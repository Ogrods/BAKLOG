/** Headers required for mutating BAKLOG API calls (localhost CSRF guard). */
export const BAKLOG_LOCAL_HEADER = 'X-BAKLOG-Local';
export const BAKLOG_LOCAL_HEADER_VALUE = '1';

/** Merge the local-only header into fetch init (plain object headers). */
export function withBaklogHeaders(init = {}) {
  const headers = { ...(init.headers && typeof init.headers === 'object' && !(init.headers instanceof Headers)
    ? init.headers
    : {}) };
  headers[BAKLOG_LOCAL_HEADER] = BAKLOG_LOCAL_HEADER_VALUE;
  if (init.headers instanceof Headers) {
    const h = new Headers(init.headers);
    h.set(BAKLOG_LOCAL_HEADER, BAKLOG_LOCAL_HEADER_VALUE);
    return { ...init, headers: h };
  }
  return { ...init, headers };
}

/** fetch() wrapper that adds X-BAKLOG-Local for POST/PUT/DELETE. */
export function baklogFetch(url, init = {}) {
  const method = (init.method || 'GET').toUpperCase();
  if (method === 'GET' || method === 'HEAD') {
    return fetch(url, init);
  }
  return fetch(url, withBaklogHeaders(init));
}
