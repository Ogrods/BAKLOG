/** Fetcher cache age / stale sweep eligibility. */
import { state } from '../state.js';
import { staleSweepRank, thresholdsForMetaKey } from './misc.js';
import { BOOT_DEFERRED_FETCHER_KEYS } from './source-meta.js';

export function humanizeAge(ms) {
  if (!Number.isFinite(ms)) return ' - ';
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h`;
  const d = Math.floor(h / 24);
  if (d < 14) return `${d}d`;
  const w = Math.floor(d / 7);
  if (w < 8) return `${w}w`;
  return `${Math.floor(d / 30)}mo`;
}

export function fetcherFreshness(source) {
  const thresholds = thresholdsForMetaKey(source.metaKey);
  const meta = state.libraryMeta[source.metaKey];
  const count = meta
    ? (source.countFn ? source.countFn(meta) : (meta.game_count ?? null))
    : null;
  const deferKey = source.key || source.metaKey;
  const fetchedAt = meta?.fetched_at || meta?.generated_at || null;
  if (!meta || !fetchedAt) {
    if (!state.dashboardDataReady && BOOT_DEFERRED_FETCHER_KEYS.has(deferKey)) {
      return { status: 'pending', ageMs: Infinity, count, ageLabel: '…', iso: null };
    }
    return { status: 'missing', ageMs: Infinity, count, ageLabel: meta ? '?' : ' - ', iso: null };
  }
  const ts = Date.parse(fetchedAt);
  const ageMs = Number.isFinite(ts) ? Date.now() - ts : Infinity;
  let status = 'stale';
  if (ageMs < thresholds.fresh) status = 'fresh';
  else if (ageMs < thresholds.recent) status = 'recent';
  return { status, ageMs, count, ageLabel: humanizeAge(ageMs), iso: fetchedAt };
}

/**
 * Whether a source should be auto-run by the "run all stale" sweep. Pure so the
 * gating rules (notably the auth-cooldown skip) can be tested without driving
 * the whole runAllStale pipeline. Inputs are the already-resolved dependency
 * results for `src`.
 */
export function resolveStaleSweepKeys(sources, {
  freshnessStatus,
  credentialsSatisfied,
  hasRunState,
  cooldownMs,
  disconnected,
} = {}) {
  return sources
    .filter(src => staleSweepEligible(src, {
      freshnessStatus: freshnessStatus(src),
      credentialsSatisfied: credentialsSatisfied(src.key),
      hasRunState: hasRunState(src.key),
      cooldownMs: cooldownMs(src.key),
      disconnected: disconnected(src.key),
    }))
    .map(src => src.key)
    .sort((a, b) => staleSweepRank(a) - staleSweepRank(b));
}

export function staleSweepEligible(src, {
  freshnessStatus,
  credentialsSatisfied,
  hasRunState,
  cooldownMs = 0,
  disconnected,
} = {}) {
  if (freshnessStatus !== 'stale' && freshnessStatus !== 'missing') return false;
  if (src?.missingRequirements?.length && !credentialsSatisfied) return false;
  if (hasRunState) return false;
  if (cooldownMs > 0) return false;
  if (disconnected) return false;
  return true;
}
