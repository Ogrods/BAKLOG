/** Fetcher health barrel: wires submodules and re-exports the public API. */
import { configureFetcherCooldown } from './fetcher-cooldown.js';
import {
  ensureAgeTicker,
  isFastAgeTickActive,
  refreshChipAgesInPlace,
  startFastAgeTick,
  stopAgeTicker,
  stopFastAgeTick,
  wireFetcherChips,
} from './fetcher-chips.js';
import { setFetcherRunner, lastRunFailedByKey, setLegendTipsOpen } from './fetcher-health-shared.js';
import { fetcherRunner } from './fetcher/runner/index.js';
import { fetchWithTimeout, FETCH_TIMEOUT_MS } from './fetcher/http.js';
import { wireFetcherHealthAutoRefresh } from './fetcher/auto-refresh-wire.js';
import {
  wireFetcherReconnect,
  markReconnectRequired,
  fetcherCredentialsSatisfied,
  connectProviderForFetcher,
  authCooldownRemainingMs,
  isFetcherReconnectRequired,
} from './fetcher/reconnect.js';
import { fetcherFreshness, humanizeAge } from './fetcher/freshness.js';
import { renderDashboardFetcherHealth, cycleStatLayout, toggleLegendTips } from './fetcher/render/dashboard.js';

setFetcherRunner(fetcherRunner);

wireFetcherReconnect({
  renderDashboardFetcherHealth,
  refreshGlobalIndicator: () => fetcherRunner.refreshGlobalIndicator(),
});

configureFetcherCooldown({
  onCooldownExpire: () => {
    try { renderDashboardFetcherHealth(); } catch (_) { /* not mounted */ }
  },
  onMaxStrikes: (_key, provider) => markReconnectRequired(provider),
  credentialsSatisfied: fetcherCredentialsSatisfied,
  connectProvider: connectProviderForFetcher,
});

wireFetcherHealthAutoRefresh();

wireFetcherChips({
  fetcherRunner,
  fetcherFreshness,
  humanizeAge,
  authCooldownRemainingMs,
  isFetcherReconnectRequired,
  lastRunFailedByKey,
  setLegendTipsOpen,
  cycleStatLayout,
  renderDashboardFetcherHealth,
});

export { fetcherRunner };
export { fetchWithTimeout, FETCH_TIMEOUT_MS } from './fetcher/http.js';
export {
  authCooldownDurationMs,
  clearAuthCooldown,
  noteAuthCooldownStrike,
  ensureProfileScopedFetcherState,
  authCooldownRemainingMs,
  FETCHER_PROVIDER_GROUP,
  fetcherProviders,
  fetcherCredentialsSatisfied,
  markReconnectRequired,
  clearReconnectRequired,
  dismissReconnectRequired,
  isReconnectDismissed,
  isProviderReconnectRequired,
  reconnectRequiredForFetcherKey,
  syncReconnectFromAuthStatus,
  processAuthStatusTransitions,
  resetAuthStatusTransitionsForTest,
  reconnectProviderForFetcher,
  isFetcherReconnectRequired,
  connectionsNavigateProvider,
  primaryFailureNavigateTarget,
  connectProviderForFetcher,
  isFetcherDisconnected,
  dismissStickyFailedState,
} from './fetcher/reconnect.js';
export {
  staleSweepRank,
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
  formatRefreshIntervalLabel,
  thresholdsForMetaKey,
  diffItadDeals,
  consumeItadAutoRunFlag,
  serverChipState,
} from './fetcher/misc.js';
export {
  coverableRows,
  configureFetcherHealth,
  loadFetcherSources,
} from './fetcher/source-meta.js';
export {
  humanizeAge,
  fetcherFreshness,
  resolveStaleSweepKeys,
  staleSweepEligible,
} from './fetcher/freshness.js';
export {
  refreshChipAgesInPlace,
  stopAgeTicker,
  ensureAgeTicker,
  stopFastAgeTick,
  isFastAgeTickActive,
  startFastAgeTick,
} from './fetcher-chips.js';
export { toggleLegendTips, cycleStatLayout, renderDashboardFetcherHealth } from './fetcher/render/dashboard.js';
export {
  buildFetcherHealthRows,
  isFetcherAuthHealthy,
  filterFetcherHealthRows,
  buildStatTilesHtml,
  buildStatStripHtml,
  tryPatchFetcherHealthDashboard,
} from './fetcher/render/stats.js';
