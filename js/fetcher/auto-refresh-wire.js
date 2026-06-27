/** Auto-refresh dependency bag for runner + fetcher-auto-refresh. */
import {
  wireFetcherAutoRefresh,
} from '../fetcher-auto-refresh.js';
import { COUNT_FNS, loadFetcherSources } from './source-meta.js';
import { fetcherFreshness } from './freshness.js';
import {
  authCooldownRemainingMs,
  fetcherCredentialsSatisfied,
  isFetcherDisconnected,
  isFetcherReconnectRequired,
} from './reconnect.js';

const ITAD_SOURCE = { key: 'itad', metaKey: 'itad', countFn: COUNT_FNS.itad };
const CLAIMS_SOURCE = { key: 'claims', metaKey: 'claims', countFn: COUNT_FNS.claims };

export function autoRefreshDeps() {
  return {
    itadSource: ITAD_SOURCE,
    claimsSource: CLAIMS_SOURCE,
    isFetcherDisconnected,
    fetcherFreshness,
    fetcherCredentialsSatisfied,
    authCooldownRemainingMs,
    isFetcherReconnectRequired,
    loadFetcherSources,
  };
}

export function wireFetcherHealthAutoRefresh() {
  wireFetcherAutoRefresh({
    itadSource: ITAD_SOURCE,
    claimsSource: CLAIMS_SOURCE,
    fetcherFreshness,
    isFetcherDisconnected,
    fetcherCredentialsSatisfied,
    authCooldownRemainingMs,
    isFetcherReconnectRequired,
  });
}
