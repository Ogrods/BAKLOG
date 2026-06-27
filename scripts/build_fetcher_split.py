#!/usr/bin/env python3
"""Generate js/fetcher/* modules from _extract slices."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "js/fetcher/_extract"


def read(name: str) -> str:
    return (EX / name).read_text(encoding="utf-8")


def write(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not content.endswith("\n"):
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return content.count("\n")


def patch_reconnect_body(body: str) -> str:
    body = body.replace(
        "async function handleFetcherAuthOutcome",
        "export async function handleFetcherAuthOutcome",
    )
    body = body.replace(
        "    try { renderDashboardFetcherHealth(); } catch (_) { /* not mounted */ }",
        "    try { _renderDashboard(); } catch (_) { /* not mounted */ }",
    )
    body = body.replace(
        "    try { fetcherRunner.refreshGlobalIndicator(); } catch (_) { /* runner not ready */ }",
        "    try { _refreshGlobalIndicator(); } catch (_) { /* runner not ready */ }",
    )
    body = body.replace(
        "      renderDashboardFetcherHealth();",
        "      _renderDashboard();",
    )
    # Drop duplicate humanizeMissingRequirements - exported separately in header
    start = body.find("function humanizeMissingRequirements")
    if start >= 0:
        end = body.find(
            "// ---------------------------------------------------------------------------\n"
            "// Per-provider reconnect",
            start,
        )
        if end >= 0:
            body = body[:start] + body[end:]
    return body


def main() -> None:
    counts: dict[str, int] = {}

    counts["js/fetcher/http.js"] = write(
        ROOT / "js/fetcher/http.js",
        """/** Fetch helpers for fetcher health / runner. */
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
""",
    )

    import re

    misc_body = read("misc.txt").split("export const FETCH_TIMEOUT_MS")[0].rstrip()
    misc_body = re.sub(
        r"export \{\n  itadLastAutoRunKey,.*?\n\};\n\n",
        "",
        misc_body,
        count=1,
        flags=re.DOTALL,
    )
    misc_body = misc_body.replace("export { consumeItadAutoRunFlag };\n\n", "")
    counts["js/fetcher/misc.js"] = write(
        ROOT / "js/fetcher/misc.js",
        """/** ITAD diff, chip state, stale sweep rank, auto-refresh re-exports. */
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

"""
        + misc_body
        + "\n",
    )

    reconnect_body = patch_reconnect_body(read("reconnect.txt"))
    counts["js/fetcher/reconnect.js"] = write(
        ROOT / "js/fetcher/reconnect.js",
        """/** Per-provider reconnect state + Connections navigation for fetcher chips. */
import { state } from '../state.js';
import {
  FETCHER_AUTH_PROVIDER,
  noteFetcherAuthFailure,
  showReconnectBanner,
  clearReconnectBanner,
  authStatusLoaded,
  providerStatus,
  ingestAuthStatusProviders,
  groupRepFor,
  isProviderConnected,
} from '../connections.js';
import {
  LS_RECONNECT_DISMISSED,
  profileScopedStorageKey,
} from '../profiles.js';
import {
  authCooldownDurationMs,
  authCooldownRemainingMs as cooldownRemainingMs,
  clearAuthCooldown,
  initAuthCooldowns,
  noteAuthCooldownStrike,
} from '../fetcher-cooldown.js';
import { lastRunFailedByKey } from '../fetcher-health-shared.js';
import { fetchWithTimeout } from './http.js';
import { maybeAutoFetchOnConnect } from '../fetcher-auto-refresh.js';

export { authCooldownDurationMs, clearAuthCooldown, noteAuthCooldownStrike };

let _renderDashboard = () => {};
let _refreshGlobalIndicator = () => {};

/** Wire dashboard refresh callbacks (avoids import cycles at load time). */
export function wireFetcherReconnect({ renderDashboardFetcherHealth, refreshGlobalIndicator } = {}) {
  if (typeof renderDashboardFetcherHealth === 'function') {
    _renderDashboard = renderDashboardFetcherHealth;
  }
  if (typeof refreshGlobalIndicator === 'function') {
    _refreshGlobalIndicator = refreshGlobalIndicator;
  }
}

/** Map manifest env keys to user-facing Connections guidance. */
export function humanizeMissingRequirements(missing) {
  if (!missing?.length) return '';
  const keys = new Set(missing);
  if (keys.has('STEAM_API_KEY') && keys.has('STEAM_ID')) return 'Steam not connected';
  if (keys.has('STEAM_API_KEY') || keys.has('STEAM_ID')) return 'Steam not connected';
  if (keys.has('GOG_AL')) return 'GOG not connected';
  if (keys.has('PSN_NPSSO')) return 'PlayStation not connected';
  if (keys.has('ITCH_API_KEY')) return 'itch.io API key missing';
  if (keys.has('ITAD_API_KEY')) return 'ITAD API key missing';
  if (keys.has('XBL_API_KEY')) return 'Xbox API key missing';
  return missing.join(', ');
}

"""
        + reconnect_body,
    )

    source_meta = read("source_meta.txt")
    source_meta = source_meta.replace(
        "let reloadGamesFn = async () => {};",
        "export let reloadGamesFn = async () => {};",
    )
    source_meta = source_meta.replace(
        "let reloadAfterFetcherFn = null;",
        "export let reloadAfterFetcherFn = null;",
    )
    source_meta = source_meta.replace(
        "let runStaleCooldownUntil = 0;",
        "export const batchRunCooldowns = { staleUntil: 0, failedUntil: 0 };",
    )
    source_meta = source_meta.replace(
        "let runFailedCooldownUntil = 0;",
        "",
    )
    source_meta = source_meta.replace(
        "export let runStaleCooldownUntil = 0;",
        "export const batchRunCooldowns = { staleUntil: 0, failedUntil: 0 };",
    )
    source_meta = source_meta.replace(
        "export let runFailedCooldownUntil = 0;",
        "",
    )
    source_meta = source_meta.replace(
        "const MAX_SSE_HINT = 'max 8 live streams';",
        "export const MAX_SSE_HINT = 'max 8 live streams';",
    )
    source_meta = source_meta.replace(
        "const ENRICH_KEYS = new Set",
        "export const ENRICH_KEYS = new Set",
    )
    source_meta = source_meta.replace(
        "const BOOT_DEFERRED_FETCHER_KEYS = new Set",
        "export const BOOT_DEFERRED_FETCHER_KEYS = new Set",
    )
    source_meta = source_meta.replace(
        "const GROUP_ORDER = ['library'",
        "export const GROUP_ORDER = ['library'",
    )
    source_meta = source_meta.replace(
        "const GROUP_LABELS = {",
        "export const GROUP_LABELS = {",
    )
    source_meta = source_meta.replace(
        "const GROUP_LABEL_TIPS = {",
        "export const GROUP_LABEL_TIPS = {",
    )
    source_meta = source_meta.replace(
        "const COUNT_PILL_TITLES = {",
        "export const COUNT_PILL_TITLES = {",
    )
    source_meta = source_meta.replace(
        "const ENRICH_ORDER = ['steamTags'",
        "export const ENRICH_ORDER = ['steamTags'",
    )
    source_meta = source_meta.replace(
        "const COUNT_FNS = {",
        "export const COUNT_FNS = {",
    )
    source_meta = source_meta.replace(
        "function clickHintFor(src) {",
        "export function clickHintFor(src) {",
    )
    source_meta = source_meta.replace(
        "function refreshHintFor(src) {",
        "export function refreshHintFor(src) {",
    )
    source_meta = source_meta.replace(
        "function coverageLabel(key) {",
        "export function coverageLabel(key) {",
    )
    source_meta = source_meta.replace(
        "function coverageTooltipLine(key) {",
        "export function coverageTooltipLine(key) {",
    )
    counts["js/fetcher/source-meta.js"] = write(
        ROOT / "js/fetcher/source-meta.js",
        """/** Fetcher source metadata, coverage helpers, manifest loading. */
import { baklogFetch } from '../api-client.js';
import { state, ITCH_NON_GAME_CLASSIFICATIONS } from '../state.js';
import { formatNum } from '../dom-util.js';
import { fetcherSources, setFetcherSources } from '../fetcher-health-shared.js';

"""
        + source_meta,
    )

    global_body = read("global_indicator.txt").replace(
        "function updateGlobalFetcherIndicator(runStateByKey, sourceFn) {",
        "export function updateGlobalFetcherIndicator(runStateByKey, sourceFn) {",
    ).replace(
        "function setGlobalFetcherTail(text, kind = 'stdout') {",
        "export function setGlobalFetcherTail(text, kind = 'stdout') {",
    )
    counts["js/fetcher/global-indicator.js"] = write(
        ROOT / "js/fetcher/global-indicator.js",
        """/** Global fetcher status pill + streaming tail helpers. */
import { fetchSuccessLabels, lastRunFailedByKey } from '../fetcher-health-shared.js';
import { primaryFailureNavigateTarget } from './reconnect.js';

"""
        + global_body,
    )

    counts["js/fetcher/freshness.js"] = write(
        ROOT / "js/fetcher/freshness.js",
        """/** Fetcher cache age / stale sweep eligibility. */
import { state } from '../state.js';
import { staleSweepRank, thresholdsForMetaKey } from './misc.js';
import { BOOT_DEFERRED_FETCHER_KEYS } from './source-meta.js';

"""
        + read("freshness.txt"),
    )

    stats_body = read("render_stats.txt").replace(
        "function fetcherStatTotals(rows) {",
        "export function fetcherStatTotals(rows) {",
    ).replace(
        "function fetcherHealthEmptyMessage({ showConnected, showStaleMissing }) {",
        "export function fetcherHealthEmptyMessage({ showConnected, showStaleMissing }) {",
    )
    counts["js/fetcher/render/stats.js"] = write(
        ROOT / "js/fetcher/render/stats.js",
        """/** Fetcher health stat tiles + dashboard patch helpers. */
import { escapeAttr, escapeHtml } from '../../dom-util.js';
import { fetcherSources, fetcherRunner, legendTipsOpen } from '../../fetcher-health-shared.js';
import { ensureAgeTicker } from '../../fetcher-chips.js';
import { statLayout } from './layout.js';
import { fetcherFreshness, humanizeAge } from '../freshness.js';
import {
  isFetcherDisconnected,
  isFetcherReconnectRequired,
} from '../reconnect.js';
import { COUNT_PILL_TITLES } from '../source-meta.js';

"""
        + stats_body,
    )

    layout = """/** Stat layout prefs for fetcher health dashboard. */
import { statLayoutStorageKey } from '../../profiles.js';

const STAT_LAYOUTS = ['compact', 'landscape'];

export function statLayout() {
  try {
    const v = localStorage.getItem(statLayoutStorageKey());
    return STAT_LAYOUTS.includes(v) ? v : 'compact';
  } catch {
    return 'compact';
  }
}

export function syncStatLayoutToggle() {
  const btn = document.getElementById('fetcherStatLayoutToggle');
  if (!btn) return;
  const layout = statLayout();
  const landscape = layout === 'landscape';
  btn.setAttribute('aria-pressed', landscape ? 'true' : 'false');
  btn.setAttribute(
    'aria-label',
    landscape ? 'Switch to compact layout' : 'Switch to landscape layout',
  );
}
"""
    counts["js/fetcher/render/layout.js"] = write(ROOT / "js/fetcher/render/layout.js", layout)

    dash_body = read("render_dashboard.txt")
    dash_body = dash_body.replace("runStaleCooldownUntil", "batchRunCooldowns.staleUntil")
    dash_body = dash_body.replace("runFailedCooldownUntil", "batchRunCooldowns.failedUntil")
    dash_body = dash_body.split("wireFetcherChips({")[0].rstrip()
    counts["js/fetcher/render/dashboard.js"] = write(
        ROOT / "js/fetcher/render/dashboard.js",
        """/** Fetcher health dashboard renderer. */
import { isAccountAuthMode, isPro } from '../../auth-gate.js';
import { state } from '../../state.js';
import { escapeAttr, escapeHtml, formatNum } from '../../dom-util.js';
import { formatPlatformList } from '../../platform-labels.js';
import { authCooldownLabel } from '../../fetcher-cooldown.js';
import {
  fetcherSources,
  fetcherRunner,
  lastRunFailedByKey,
  legendTipsOpen,
  setLegendTipsOpen,
} from '../../fetcher-health-shared.js';
import { ensureAgeTicker } from '../../fetcher-chips.js';
import { formatRefreshIntervalLabel } from '../misc.js';
import { fetcherFreshness } from '../freshness.js';
import {
  authCooldownRemainingMs,
  connectionsNavigateProvider,
  fetcherCredentialsSatisfied,
  isFetcherDisconnected,
  isFetcherReconnectRequired,
} from '../reconnect.js';
import {
  clickHintFor,
  COUNT_PILL_TITLES,
  coverageLabel,
  coverageTooltipLine,
  ENRICH_KEYS,
  ENRICH_ORDER,
  GROUP_LABELS,
  GROUP_LABEL_TIPS,
  GROUP_ORDER,
  refreshHintFor,
  batchRunCooldowns,
} from '../source-meta.js';
import {
  buildStatStripHtml,
  buildStatTilesHtml,
  fetcherHealthEmptyMessage,
  fetcherStatTotals,
  filterFetcherHealthRows,
  tryPatchFetcherHealthDashboard,
} from './stats.js';
import { statLayout, syncStatLayoutToggle } from './layout.js';

export function toggleLegendTips() {
  setLegendTipsOpen(!legendTipsOpen);
  renderDashboardFetcherHealth();
}

export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try { localStorage.setItem(require('../../profiles.js').statLayoutStorageKey(), next); } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}

"""
        + dash_body,
    )
    # Fix cycleStatLayout - use proper import instead of require
    dash_path = ROOT / "js/fetcher/render/dashboard.js"
    dash_text = dash_path.read_text(encoding="utf-8")
    dash_text = dash_text.replace(
        """export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try { localStorage.setItem(require('../../profiles.js').statLayoutStorageKey(), next); } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}
""",
        """export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try {
    const { statLayoutStorageKey } = await import('../../profiles.js');
    localStorage.setItem(statLayoutStorageKey(), next);
  } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}
""",
    )
    # cycleStatLayout must stay sync - fix with import at top
    dash_text = dash_text.replace(
        "import { statLayout, syncStatLayoutToggle } from './layout.js';",
        (
            "import { statLayoutStorageKey } from '../../profiles.js';\n"
            "import { statLayout, syncStatLayoutToggle } from './layout.js';"
        ),
    )
    dash_text = dash_text.replace(
        """export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try {
    const { statLayoutStorageKey } = await import('../../profiles.js');
    localStorage.setItem(statLayoutStorageKey(), next);
  } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}
""",
        """export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try { localStorage.setItem(statLayoutStorageKey(), next); } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}
""",
    )
    counts["js/fetcher/render/dashboard.js"] = write(dash_path, dash_text)

    auto_refresh_wire = """/** Auto-refresh dependency bag for runner + fetcher-auto-refresh. */
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
"""
    counts["js/fetcher/auto-refresh-wire.js"] = write(
        ROOT / "js/fetcher/auto-refresh-wire.js",
        auto_refresh_wire,
    )

    runner_imports = """/** Fetcher runner: queue, SSE streams, log panel, batch runs. */
import { baklogFetch, urlWithStreamTicket } from '../../api-client.js';
import { isPageHidden, registerPausable } from '../../visibility.js';
import { state } from '../../state.js';
import { escapeAttr, escapeHtml } from '../../dom-util.js';
import {
  LOG_PANEL_CHROME_HTML,
  LOG_EMPTY_MESSAGE,
  logCollapseLabel,
} from '../../fetcher-health-log.js';
import {
  FETCHER_AUTH_PROVIDER,
  showReconnectBanner,
  clearReconnectBanner,
} from '../../connections.js';
import {
  LS_FETCHER_SUPPRESSED_RUNS,
  LS_FETCHER_LAST_SEQ,
  profileScopedStorageKey,
} from '../../profiles.js';
import { markClaimsPendingAutoRun } from '../../claimable.js';
import { savePrefs } from '../../prefs.js';
import { bindEscapeClose, trapFocus } from '../../focus-trap.js';
import { authCooldownLabel, clearAuthCooldown } from '../../fetcher-cooldown.js';
import {
  maybeAutoRefreshItad,
  maybeAutoRefreshClaims,
  maybeAutoFetchStale24h,
} from '../../fetcher-auto-refresh.js';
import { autoRefreshDeps } from '../auto-refresh-wire.js';
import {
  fetcherSources,
  fetchSuccessLabels,
  lastRunFailedByKey,
  markItadPendingAutoRun,
} from '../../fetcher-health-shared.js';
import { startFastAgeTick, stopAgeTicker, stopFastAgeTick } from '../../fetcher-chips.js';
import { FETCH_TIMEOUT_MS, fetchWithTimeout } from '../http.js';
import { serverChipState } from '../misc.js';
import { renderDashboardFetcherHealth, cycleStatLayout } from '../render/dashboard.js';
import { updateGlobalFetcherIndicator, setGlobalFetcherTail } from '../global-indicator.js';
import {
  handleFetcherAuthOutcome,
  authCooldownRemainingMs,
  isFetcherDisconnected,
  connectProviderForFetcher,
  fetcherCredentialsSatisfied,
  clearReconnectRequired,
  syncReconnectFromAuthStatus,
  humanizeMissingRequirements,
} from '../reconnect.js';
import {
  loadFetcherSources,
  reloadGamesFn,
  reloadAfterFetcherFn,
  batchRunCooldowns,
  MAX_SSE_HINT,
} from '../source-meta.js';
import { fetcherFreshness, resolveStaleSweepKeys } from '../freshness.js';

"""
    runner_body = read("runner_body.txt").replace(
            "import('./error-boundary.js')",
            "import('../../error-boundary.js')",
        ).replace(
            "runStaleCooldownUntil = Date.now() + 2000;",
            "batchRunCooldowns.staleUntil = Date.now() + 2000;",
        ).replace(
            "runFailedCooldownUntil = Date.now() + 2000;",
            "batchRunCooldowns.failedUntil = Date.now() + 2000;",
        )
    counts["js/fetcher/runner/index.js"] = write(
        ROOT / "js/fetcher/runner/index.js",
        runner_imports + runner_body,
    )

    barrel = """/** Fetcher health barrel: wires submodules and re-exports the public API. */
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
import { setFetcherRunner } from './fetcher-health-shared.js';
import { fetcherRunner } from './fetcher/runner/index.js';
import { fetchWithTimeout, FETCH_TIMEOUT_MS } from './fetcher/http.js';
import { wireFetcherHealthAutoRefresh } from './fetcher/auto-refresh-wire.js';
import {
  wireFetcherReconnect,
  markReconnectRequired,
  fetcherCredentialsSatisfied,
  connectProviderForFetcher,
} from './fetcher/reconnect.js';
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

import { fetcherFreshness, humanizeAge } from './fetcher/freshness.js';
import {
  authCooldownRemainingMs,
  isFetcherReconnectRequired,
} from './fetcher/reconnect.js';
import { lastRunFailedByKey, setLegendTipsOpen } from './fetcher-health-shared.js';
"""
    counts["js/fetcher-health.js"] = write(ROOT / "js/fetcher-health.js", barrel)

    print("Generated modules:")
    for path, n in sorted(counts.items()):
        print(f"  {path}: {n} lines")


if __name__ == "__main__":
    main()
