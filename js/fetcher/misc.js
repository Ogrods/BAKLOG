/** ITAD diff, chip state, stale sweep rank, auto-refresh re-exports. */
import { consumeItadAutoRunFlag } from '../fetcher-health-shared.js';
export {
  itadLastAutoRunKey,
  claimsLastAutoRunKey,
  ITAD_AUTO_REFRESH_INTERVAL_MS,
  ITAD_AUTO_QUIET_HOUR_END,
  itadAutoRefreshIntervalMs,
  CLAIMS_AUTO_REFRESH_INTERVAL_MS,
  claimsAutoRefreshIntervalMs,
  AUTO_STALE_AGE_MS,
  AUTO_STALE_STAGGER_MS,
  autoStaleLastRunKey,
  maybeAutoRefreshItad,
  maybeAutoRefreshClaims,
  maybeAutoFetchOnConnect,
  maybeAutoFetchStale24h,
  maybeAutoEnrichNewAdditions,
} from '../fetcher-auto-refresh.js';

export { consumeItadAutoRunFlag };

const FRESH_THRESHOLDS = { fresh: 7 * 86400000, recent: 30 * 86400000 };
// ITAD is a deal feed — library-style 7d/30d thresholds are misleading.
const STALE_SWEEP_ORDER = {
  itch: 10,
  gog: 20,
  xbox: 30,
  amazon: 40,
  epic: 50,
  psn: 60,
  steam: 70,
  humble: 80,
  battlenet: 90,
  ubisoft: 100,
  nintendo: 110,
  ea: 120,
  hltb: 200,
  steamReviews: 210,
  steamCovers: 220,
  steamTags: 230,
  protondb: 240,
};

export function staleSweepRank(key) {
  return STALE_SWEEP_ORDER[key] ?? 150;
}
const STALE_OVERRIDES = {
  itad: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
  claims: { fresh: 60 * 60_000, recent: 6 * 60 * 60_000 },
};
/** Compact label for an interval in minutes, e.g. 45 → "45m", 120 → "2h", 90 → "1h 30m". */
export function formatRefreshIntervalLabel(min) {
  const m = Number(min);
  if (!Number.isFinite(m)) return '';
  if (m < 60) return `${m}m`;
  const hours = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${hours}h` : `${hours}h ${rem}m`;
}

export function thresholdsForMetaKey(metaKey) {
  return STALE_OVERRIDES[metaKey] || FRESH_THRESHOLDS;
}

/** Count new sales / historical lows after an ITAD refresh. */
export function diffItadDeals(prev, next) {
  let newSales = 0;
  let newHistoricalLows = 0;
  for (const [key, n] of Object.entries(next || {})) {
    const p = prev?.[key];
    const cut = n?.cut || 0;
    const prevCut = p?.cut || 0;
    if (cut > 0 && prevCut === 0) newSales += 1;
    if (n?.is_historical_low && !p?.is_historical_low) newHistoricalLows += 1;
  }
  return { newSales, newHistoricalLows };
}

/** Map server run status to dashboard chip state. */
export function serverChipState(status) {
  if (status === 'running' || status === 'launching' || status === 'cancelling') return 'running';
  if (status === 'queued') return 'queued';
  return null;
}
