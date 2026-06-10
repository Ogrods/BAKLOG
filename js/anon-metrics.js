/**
 * Opt-in anonymous aggregate metrics — session counts + sponsored-slot
 * impressions/clicks. Nothing is sent unless prefs.shareAnonStats is true.
 */
import { state } from './state.js';

export const METRICS_ENDPOINT = 'https://baklog.app/api/metrics';
const FLUSH_MS = 5 * 60 * 1000;
const VALID_TYPES = new Set(['session_start', 'impression', 'click']);

let sessionId = null;
/** @type {Map<string, number>} */
let queue = new Map();
/** @type {Set<string>} */
let impressed = new Set();
let flushTimer = null;
let listenersBound = false;

function queueKey(type, placement, sponsorId) {
  return JSON.stringify([type, placement || '', sponsorId || '']);
}

export function isMetricsEnabled() {
  return state.prefs?.shareAnonStats === true;
}

export function getMetricsEndpoint() {
  return (document.querySelector('meta[name="baklog-metrics-endpoint"]')?.content)
    || window.__BAKLOG_METRICS_ENDPOINT
    || METRICS_ENDPOINT;
}

function appVersion() {
  return document.querySelector('meta[name="baklog-version"]')?.getAttribute('content') || 'unknown';
}

function ensureSessionId() {
  if (!sessionId) {
    const raw = typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `s${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    sessionId = String(raw).slice(0, 64);
  }
  return sessionId;
}

export function recordMetric(type, { placement = '', sponsorId = '' } = {}) {
  if (!isMetricsEnabled() || !VALID_TYPES.has(type)) return;
  const key = queueKey(type, placement, sponsorId);
  queue.set(key, (queue.get(key) || 0) + 1);
}

/** One impression per placement+sponsor per app session (survives re-renders). */
export function noteSponsoredImpression(placement, sponsorId) {
  if (!placement || !sponsorId) return;
  const dedupeKey = `${placement}|${sponsorId}`;
  if (impressed.has(dedupeKey)) return;
  impressed.add(dedupeKey);
  recordMetric('impression', { placement, sponsorId });
}

function firstLocationForAdId(adId) {
  for (const [loc, ids] of Object.entries(state.adLocations || {})) {
    if (Array.isArray(ids) && ids.includes(adId)) return loc;
  }
  const item = (state.sponsoredDeals || []).find(it => it.id === adId);
  if (item) {
    const raw = item?.placements;
    if (raw == null || raw === '') return 'wish-house';
    const list = Array.isArray(raw) ? raw : String(raw).split(',');
    return list.map(s => String(s).trim().toLowerCase()).filter(Boolean)[0] || '';
  }
  return '';
}

export function recordSponsoredClick(sponsorId) {
  if (!sponsorId) return;
  const placement = firstLocationForAdId(sponsorId);
  recordMetric('click', { placement, sponsorId });
}

export async function flushMetrics() {
  if (!isMetricsEnabled() || queue.size === 0) return;
  const events = [];
  for (const [key, n] of queue) {
    const [type, placement, sponsorId] = JSON.parse(key);
    events.push({
      type,
      ...(placement ? { placement } : {}),
      ...(sponsorId ? { sponsor_id: sponsorId } : {}),
      n,
    });
  }
  queue.clear();
  const body = {
    bundle: 'baklog-metrics',
    app_version: appVersion(),
    session_id: ensureSessionId(),
    events,
  };
  try {
    const res = await fetch(getMetricsEndpoint(), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      // Re-queue on transient failure so the next flush retries.
      for (const ev of events) {
        recordMetric(ev.type, { placement: ev.placement || '', sponsorId: ev.sponsor_id || '' });
      }
    }
  } catch (_) { /* offline */ }
}

function onVisibilityHidden() {
  if (document.visibilityState === 'hidden') flushMetrics();
}

function onBeforeUnload() {
  flushMetrics();
}

function bindFlushListeners() {
  if (listenersBound || typeof window === 'undefined') return;
  window.addEventListener('visibilitychange', onVisibilityHidden);
  window.addEventListener('beforeunload', onBeforeUnload);
  listenersBound = true;
}

function unbindFlushListeners() {
  if (!listenersBound || typeof window === 'undefined') return;
  window.removeEventListener('visibilitychange', onVisibilityHidden);
  window.removeEventListener('beforeunload', onBeforeUnload);
  listenersBound = false;
}

export function startMetrics() {
  if (!isMetricsEnabled()) return;
  ensureSessionId();
  recordMetric('session_start');
  bindFlushListeners();
  if (!flushTimer) {
    flushTimer = setInterval(() => { flushMetrics(); }, FLUSH_MS);
  }
}

export function stopMetrics() {
  if (flushTimer) {
    clearInterval(flushTimer);
    flushTimer = null;
  }
  unbindFlushListeners();
  flushMetrics();
  queue.clear();
  impressed.clear();
  sessionId = null;
}

/** Test-only reset between vitest cases. */
export function __resetMetricsForTest() {
  if (flushTimer) {
    clearInterval(flushTimer);
    flushTimer = null;
  }
  unbindFlushListeners();
  queue.clear();
  impressed.clear();
  sessionId = null;
}
