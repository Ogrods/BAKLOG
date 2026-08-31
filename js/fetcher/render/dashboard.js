/** Fetcher health dashboard renderer. */
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
import { statLayoutStorageKey } from '../../profiles.js';
import { statLayout, syncStatLayoutToggle } from './layout.js';

export function toggleLegendTips() {
  setLegendTipsOpen(!legendTipsOpen);
  renderDashboardFetcherHealth();
}

export function cycleStatLayout() {
  const next = statLayout() === 'compact' ? 'landscape' : 'compact';
  try { localStorage.setItem(statLayoutStorageKey(), next); } catch { /* ignore */ }
  renderDashboardFetcherHealth();
  return next;
}

export function renderDashboardFetcherHealth() {
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return;
  const restoreBarToggleFocus = document.activeElement?.matches?.('[data-role="bar-toggle"]');
  const showConnected = state.prefs.fetcherHealthShowConnected !== false;
  const showStaleMissing = state.prefs.fetcherHealthShowStaleMissing !== false;
  const rows = fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
  const staleRows = rows.filter(r => r.status === 'stale');
  const missingRows = rows.filter(r => r.status === 'missing');
  const runnableStale = rows.filter(r => {
    if (r.status !== 'stale' && r.status !== 'missing') return false;
    if (r.src.missingRequirements?.length && !fetcherCredentialsSatisfied(r.src.key)) return false;
    if (fetcherRunner.stateFor(r.src.key)) return false;
    if (isFetcherDisconnected(r.src.key)) return false;
    return true;
  });
  const runnableFailed = rows.filter(r => {
    const key = r.src.key;
    if (!lastRunFailedByKey.has(key)) return false;
    if (fetcherRunner.stateFor(key)) return false;
    if (authCooldownRemainingMs(key) > 0) return false;
    if (isFetcherDisconnected(key)) return false;
    if (r.src.missingRequirements?.length && !fetcherCredentialsSatisfied(key)) return false;
    return true;
  });
  const visible = filterFetcherHealthRows(rows, { showConnected, showStaleMissing });
  // Sort best -> worst by the chip's *effective* status (mirrors the precedence
  // chipHtml uses for displayStatus), so healthy fetchers float to the top and
  // anything needing attention sinks to the bottom. Active runs lead since the
  // user is watching them; alphabetical label is the final tiebreaker.
  const healthRank = (r) => {
    const key = r.src.key;
    const runState = fetcherRunner.stateFor(key);
    if (runState && runState !== 'failed') return 0; // running / queued / launching
    if (!runState && lastRunFailedByKey.has(key)) return 8; // failed (worst)
    if (isFetcherReconnectRequired(key)) return 7; // session expired
    if (isFetcherDisconnected(key)) return 6; // not connected
    if (authCooldownRemainingMs(key) > 0) return 5; // auth cooldown
    const freshRank = { fresh: 1, recent: 2, stale: 3, pending: 3, missing: 4 };
    return freshRank[r.status] ?? 4;
  };
  visible.sort((a, b) => healthRank(a) - healthRank(b) || a.src.label.localeCompare(b.src.label));

  const summaryParts = [];
  if (staleRows.length) summaryParts.push(`${staleRows.length} stale`);
  if (missingRows.length) summaryParts.push(`${missingRows.length} missing`);
  const healthSummary = summaryParts.length ? summaryParts.join(' · ') : 'All fresh';
  fetcherRunner.setBarSummary(healthSummary);
  // The "missing" pill is always shown so it doesn't pop in/out: at 0 it stays
  // put and turns green (fresh). The stale pill remains count-conditional.
  const missingNone = missingRows.length === 0;
  const stalePillHtml = staleRows.length
    ? `<span class="fh-count fh-count--stale" title="${escapeAttr(COUNT_PILL_TITLES.stale)}">${staleRows.length} stale</span>`
    : '';
  const missingPillHtml = `<span class="fh-count ${missingNone ? 'fh-count--fresh' : 'fh-count--missing'}" title="${escapeAttr(missingNone ? COUNT_PILL_TITLES.fresh : COUNT_PILL_TITLES.missing)}">${missingRows.length} missing</span>`;
  const countsHtml = `${stalePillHtml}${missingPillHtml}`;
  const apiReady = fetcherRunner.isApiAvailable();
  const probeDone = fetcherRunner.apiProbeFinished();
  const showReadonly = probeDone && !apiReady;
  const summaryTooltip = [
    'Click a chip → run an incremental sync (fast - fills gaps, uses cache where safe).',
    'Shift+click on library/wishlist chips → force a full refresh that ignores local cache (slower; only on chips that support it).',
    'Shift+click on HLTB / Reviews / Covers → retry titles cached as "no match".',
    'Hover any chip to see exactly what click vs. Shift+click will do for that source.',
  ].join('\n');
  const clickHint = apiReady
    ? `<span class="fh-legend-item" title="${escapeAttr(summaryTooltip)}"><span class="fh-chip-warn" aria-hidden="true">!</span> click a chip = sync &middot; Shift+click = refresh or retry misses</span>`
    : '';
  const readonlyBanner = showReadonly
    ? (isAccountAuthMode()
      ? `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only - the server API did not respond (sign in, restart
          <code>python server.py</code>, or check the terminal for errors).
        </div>`
      : `<div class="fh-readonly-banner" role="status">
          Fetcher health is read-only. Run <code>python server.py</code> and open
          <a href="http://127.0.0.1:8765" class="fh-readonly-link">http://127.0.0.1:8765</a>
          to click chips and stream logs.
        </div>`)
    : '';
  const layout = statLayout();
  const countsBlockHtml = `<span class="fh-counts">${countsHtml}</span>`;
  const infoStripHtml = buildStatStripHtml(rows, 'compact', '');
  const statStripHtml = buildStatStripHtml(rows, layout, '');

  const chipPatches = [];

  function chipHtml({ src, status, count, ageLabel, iso }) {
    const covLabel = ENRICH_KEYS.has(src.key) ? coverageLabel(src.key) : null;
    const countStr = covLabel != null
      ? covLabel
      : (count != null && count > 0 ? formatNum(count) : ' - ');
    // Co-op tags has the longest enrichment label; when it also shows "· N new"
    // the chip gets tight, so drop the " tags" suffix to reclaim space.
    const chipLabel = (src.key === 'steamTags' && covLabel && covLabel.includes('new'))
      ? src.label.replace(/ tags$/i, '')
      : src.label;
    const fetchedLine = iso ? new Date(iso).toLocaleString() : 'not loaded';
    const runState = fetcherRunner.stateFor(src.key);
    // A terminal 'failed' runState (the ~10s post-failure flash) is not an
    // active run: clicks should route to Connections (reconnect / fix creds)
    // exactly like the persisted failed/reconnect state that follows it, so
    // every chip behaves the same the instant it fails — never silently
    // re-running an auth-broken fetcher. Only launching/queued/running/
    // cancelling count as "active" and suppress the Connections route.
    const runActive = !!runState && runState !== 'failed';
    const needsReconnect = !runActive && isFetcherReconnectRequired(src.key);
    const disconnected = !runActive && !needsReconnect && isFetcherDisconnected(src.key);
    const navProvider = !runActive ? connectionsNavigateProvider(src.key) : null;
    const authCooldownMs = (runState || needsReconnect || disconnected) ? 0 : authCooldownRemainingMs(src.key);
    const inAuthCooldown = authCooldownMs > 0;
    const persistFailed = !runState && lastRunFailedByKey.has(src.key);
    const displayStatus = runState
      || (persistFailed ? 'failed' : (needsReconnect ? 'reconnect' : status));
    const runLabel = runState ? ` · ${runState.toUpperCase()}` : '';
    const needsConfig = (src.missingRequirements || []).length > 0
      && !fetcherCredentialsSatisfied(src.key);
    const configHint = needsConfig
      ? ` · missing for this profile: ${src.missingRequirements.join(', ')} (Connections)`
      : '';
    const clickHint = clickHintFor(src);
    const refreshHint = refreshHintFor(src);
    const enrichLine = ENRICH_KEYS.has(src.key) ? coverageTooltipLine(src.key) : null;
    const titleLines = apiReady
      ? [
          `${src.label} · ${countStr} · fetched ${fetchedLine}${runLabel}`,
          enrichLine,
          `Click: ${clickHint}`,
          refreshHint ? `Shift+click: ${refreshHint}` : 'Shift+click: not supported for this fetcher',
          `Command: ${src.cmd}${refreshHint
            ? (src.key === 'hltb' || src.key === 'steamReviews' || src.key === 'steamCovers'
              ? ' [+ --retry-misses on Shift+click]'
              : src.key === 'protondb'
                ? ' [+ --retry-misses --refresh on Shift+click]'
                : ' [+ --refresh on Shift+click]')
            : ''}`,
          needsConfig ? 'Not configured for this profile - open Connections to add keys.' : '',
          configHint ? `Note:${configHint}` : '',
        ].filter(Boolean)
      : [
          `${src.label} · ${countStr} · fetched ${fetchedLine}`,
          enrichLine,
          `Click: ${clickHint}`,
          `Command: ${src.cmd}`,
          needsConfig ? 'Not configured for this profile - open Connections to add keys.' : '',
          configHint ? `Note:${configHint}` : '',
          'Server is offline - start `python server.py` to run fetchers from the UI.',
        ].filter(Boolean);
    const queueFullElsewhere = fetcherRunner.isQueueFullForKey(src.key) && !runState;
    if (queueFullElsewhere) {
      titleLines.push('Queue full - a fetch is already running. Wait for it to finish.');
    }
    if (needsReconnect) {
      titleLines.push('Session expired - reconnect to refresh credentials, or dismiss to hide this hint.');
    }
    if (disconnected) {
      titleLines.push('Not connected - click to connect in Connections.');
    }
    if (inAuthCooldown) {
      titleLines.push(`Auth failed - cooling down ${authCooldownLabel(authCooldownMs)}. Reconnect in Connections to clear, or wait it out.`);
    }
    const platformUnavailable = src.available === false;
    if (platformUnavailable) {
      const plats = formatPlatformList(src.platforms);
      titleLines.push(`Unavailable on this OS - ${src.label} runs on ${plats} only.`);
    }
    const title = titleLines.join('\n');
    // When navProvider is set, the chip routes to Connections (bind-events) instead of running.
    const disabled = platformUnavailable || !apiReady || runState === 'running' || runState === 'queued' || queueFullElsewhere
      || ((inAuthCooldown || needsReconnect) && !navProvider);
    const needsClass = needsConfig ? ' fh-chip-needs-config' : '';
    const readonlyClass = !apiReady ? ' fh-chip-readonly' : '';
    const cooldownClass = inAuthCooldown ? ' fh-chip-auth-cooldown' : '';
    const reconnectClass = needsReconnect ? ' fh-chip-reconnect-required' : '';
    const disconnectedClass = disconnected ? ' fh-chip-disconnected' : '';
    const unavailableClass = platformUnavailable ? ' fh-chip-unavailable' : '';
    const warnBadge = needsConfig
      ? '<span class="fh-chip-warn" title="Missing credentials for this profile - Connections">!</span>'
      : '';
    let ageText = runState
      ? runState
      : (disconnected ? '' : (inAuthCooldown ? authCooldownLabel(authCooldownMs) : ageLabel));
    if (persistFailed && !runState) ageText = 'failed';
    else if (status === 'pending') ageText = '…';
    else if (status === 'missing' && ageLabel === '?' && (count === 0 || count == null)) ageText = 'empty';
    const connectAttr = navProvider
      ? ` data-fetcher-connect="${escapeAttr(navProvider)}"`
      : '';
    const chipAriaLabel = `${chipLabel}, ${countStr}, ${ageText || status}`;
    chipPatches.push({
      key: src.key,
      displayStatus,
      status,
      title,
      disabled,
      connectProvider: navProvider || '',
      chipLabel,
      countStr,
      ageText,
      chipAriaLabel,
      showWarn: needsConfig,
      modifiers: {
        'fh-chip-needs-config': needsConfig,
        'fh-chip-readonly': !apiReady,
        'fh-chip-auth-cooldown': inAuthCooldown,
        'fh-chip-reconnect-required': needsReconnect,
        'fh-chip-disconnected': disconnected,
        'fh-chip-unavailable': platformUnavailable,
      },
    });
    const chipBtn = `<button type="button" class="fh-chip fh-chip-${escapeAttr(displayStatus)}${needsClass}${readonlyClass}${cooldownClass}${reconnectClass}${disconnectedClass}${unavailableClass}" data-fetcher-key="${escapeAttr(src.key)}" data-status="${escapeAttr(status)}"${connectAttr} style="border-left: 3px solid ${escapeAttr(src.color)}" title="${escapeAttr(title)}" aria-label="${escapeAttr(chipAriaLabel)}"${disabled ? ' disabled' : ''} aria-disabled="${disabled ? 'true' : 'false'}">
      <span class="fh-chip-dot"></span>
      ${warnBadge}
      <span class="fh-chip-label">${escapeHtml(chipLabel)}</span>
      <span class="fh-chip-count">${escapeHtml(countStr)}</span>
      <span class="fh-chip-age">${escapeHtml(ageText)}</span>
    </button>`;
    return chipBtn;
  }

  const chipsHtml = visible.length
    ? GROUP_ORDER.map(group => {
        let groupRows = visible.filter(r => r.src.group === group);
        if (!groupRows.length) return '';
        if (group === 'enrich') {
          const ord = k => {
            const i = ENRICH_ORDER.indexOf(k);
            return i < 0 ? ENRICH_ORDER.length : i;
          };
          groupRows = [...groupRows].sort((a, b) => healthRank(a) - healthRank(b) || ord(a.src.key) - ord(b.src.key));
        }
        let groupToggle = '';
        if (group === 'prices') {
          // Each price chip gets its own row paired with its auto-refresh
          // control (checkbox + slider + value). The chip is the label, so the
          // "ITAD auto-refresh" / "Claims auto-refresh" text labels are dropped.
          const itadMin = Number(state.prefs.itadAutoRefreshIntervalMin) || 15;
          const itadOff = !!state.prefs.itadAutoRefreshDisabled;
          const claimsMin = Number(state.prefs.claimsAutoRefreshIntervalMin) || 120;
          const claimsOff = !!state.prefs.claimsAutoRefreshDisabled;
          const itadRow = groupRows.find(r => r.src.key === 'itad');
          const claimsRow = groupRows.find(r => r.src.key === 'claims');
          const otherRows = groupRows.filter(r => r.src.key !== 'itad' && r.src.key !== 'claims');
          const itadCtrl = `<div class="fh-price-ctrl fh-itad-interval" title="How often auto-refresh runs ITAD (15-60 min)">
              <input id="itadAutoRefreshToggle" type="checkbox" class="rounded" ${itadOff ? '' : 'checked'} title="Runs ITAD between 7am and midnight when the dashboard is open." aria-label="ITAD auto-refresh" />
              <input id="itadAutoRefreshInterval" type="range" min="15" max="60" step="5" value="${itadMin}" ${itadOff ? 'disabled' : ''} aria-label="ITAD auto-refresh interval (minutes)" />
              <span id="itadAutoRefreshIntervalVal">${itadMin}m</span>
            </div>`;
          const claimsCtrl = `<div class="fh-price-ctrl fh-claims-interval" title="How often auto-refresh checks free claims (30-360 min)">
              <input id="claimsAutoRefreshToggle" type="checkbox" class="rounded" ${claimsOff ? '' : 'checked'} title="Auto-refresh free game claims while the dashboard is open." aria-label="Claims auto-refresh" />
              <input id="claimsAutoRefreshInterval" type="range" min="30" max="360" step="30" value="${claimsMin}" ${claimsOff ? 'disabled' : ''} aria-label="Claims auto-refresh interval (minutes)" />
              <span id="claimsAutoRefreshIntervalVal">${formatRefreshIntervalLabel(claimsMin)}</span>
            </div>`;
          const priceRows = [
            itadRow ? `<div class="fh-price-row">${chipHtml(itadRow)}${itadCtrl}</div>` : '',
            claimsRow ? `<div class="fh-price-row">${chipHtml(claimsRow)}${claimsCtrl}</div>` : '',
            ...otherRows.map(r => `<div class="fh-price-row">${chipHtml(r)}</div>`),
          ].join('');
          return `<div class="fh-group fh-group--prices">
              <div class="fh-group-head">
                <div class="fh-group-label" title="${escapeAttr(GROUP_LABEL_TIPS[group] || '')}">${escapeHtml(GROUP_LABELS[group] || group)}</div>
              </div>
              <div class="fh-price-rows">${priceRows}</div>
            </div>`;
        } else if (group === 'enrich') {
          groupToggle = `<label class="fh-toggle" title="After a library fetch adds new games, queue HLTB, Reviews, Covers, and Co-op tags">
              <input id="autoEnrichOnAddToggle" type="checkbox" class="rounded" ${state.prefs.autoEnrichOnAdd === true ? 'checked' : ''} />
              Auto-enrich new games
            </label>`;
        }
        return `<div class="fh-group">
            <div class="fh-group-head">
              <div class="fh-group-label" title="${escapeAttr(GROUP_LABEL_TIPS[group] || '')}">${escapeHtml(GROUP_LABELS[group] || group)}</div>
              ${groupToggle}
            </div>
            <div class="fh-group-chips">${groupRows.map(chipHtml).join('')}</div>
          </div>`;
      }).join('')
    : `<span class="fh-empty">${escapeHtml(fetcherHealthEmptyMessage({ showConnected, showStaleMissing }))}</span>`;

  const staleBtnDisabled = !apiReady || !runnableStale.length || Date.now() < batchRunCooldowns.staleUntil;
  const staleBtnLabel = `Run stale (${runnableStale.length})`;
  const failedBtnDisabled = !apiReady || !runnableFailed.length || Date.now() < batchRunCooldowns.failedUntil;
  const failedBtnLabel = `Retry failed (${runnableFailed.length})`;

  const staleButtonHtml = isPro()
    ? `<button type="button" class="fh-run-stale" ${staleBtnDisabled ? 'disabled' : ''} title="Queue every stale store back-to-back (Pro)">${escapeHtml(staleBtnLabel)}</button>`
    : '';
  const failedButtonHtml = runnableFailed.length
    ? `<button type="button" class="fh-run-failed" ${failedBtnDisabled ? 'disabled' : ''} title="Queue every fetcher that failed its last run">${escapeHtml(failedBtnLabel)}</button>`
    : '';
  const batchButtonsHtml = `${failedButtonHtml}${staleButtonHtml}`;
  const filterHint = (!showConnected && !showStaleMissing)
    ? 'Showing all'
    : `Uncheck both to show all ${rows.length}`;
  const filterToggleHtml = `<div class="fh-filter-toggles" title="Each checked box adds fetchers (OR). Disconnected sources with fresh data may stay hidden - uncheck both to reveal all.">
            <label class="fh-toggle" title="Show fetchers whose store/session is connected (not disconnected or expired)">
              <input id="fetcherHealthShowConnected" type="checkbox" class="rounded" ${showConnected ? 'checked' : ''} />
              Connected
            </label>
            <label class="fh-toggle" title="Show fetchers with stale or missing cached data (regardless of connection)">
              <input id="fetcherHealthShowStaleMissing" type="checkbox" class="rounded" ${showStaleMissing ? 'checked' : ''} />
              Stale / missing
            </label>
            <span class="fh-filter-hint">${escapeHtml(filterHint)}</span>
          </div>`;
  const legendTipsItemsHtml = `
          ${clickHint}
          <span class="fh-legend-item" title="Yellow ! on a chip - credentials missing for this profile; open Connections"><span class="fh-chip-warn" aria-hidden="true">!</span> missing keys for this profile</span>
          <span class="fh-legend-item" title="Dim dashed chip border - this source has never been fetched">dim dashed = never fetched</span>
          <span class="fh-legend-item" title="Dot color on each chip - how old the cached data is">dot color = cache age</span>
          <span class="fh-legend-item" title="Reconnect label - session expired; fix in Connections, not by clicking the chip">reconnect = session expired (Connections, not these chips)</span>`;
  const legendToggleHtml = `<button type="button" class="fh-legend-toggle${legendTipsOpen ? ' is-open' : ''}" data-role="fh-legend-toggle" aria-expanded="${legendTipsOpen ? 'true' : 'false'}" aria-controls="fhLegendTips" title="Show fetcher chip legend and tips">ⓘ Legend &amp; tips</button>`;
  const legendTipsHtml = `<div id="fhLegendTips" class="fh-legend-tips${legendTipsOpen ? ' is-open' : ''}" role="region" aria-label="Fetcher legend and tips"${legendTipsOpen ? '' : ' aria-hidden="true"'}>${legendTipsItemsHtml}</div>`;
  const chipsBlockHtml = `<div class="fh-chips">${chipsHtml}</div>`;
  const controlBarHtml = `
      <div class="fh-legend-row fh-legend-row--bar">
        <div class="fh-control-bar">
          ${countsBlockHtml}
          ${batchButtonsHtml}
          ${filterToggleHtml}
          ${legendToggleHtml}
        </div>
      </div>`;

  // Landscape: 3-col rail (meter | tiles+controls | legend+chips).
  // Compact: finalized top-info stack above chips.
  const overviewHtml = layout === 'landscape'
    ? `<div class="fh-rail-grid">
      ${statStripHtml}
      <div class="fh-rail-mid">
        ${buildStatTilesHtml(rows)}
        <div class="fh-head fh-head--stack">
          ${countsBlockHtml}
          ${batchButtonsHtml}
          ${filterToggleHtml}
          ${legendToggleHtml}
        </div>
      </div>
      <div class="fh-rail-main">
        ${chipsBlockHtml}
      </div>
    </div>
    ${legendTipsHtml}`
    : `${infoStripHtml}
    <div class="fh-rail-main">
      ${controlBarHtml}
      ${chipsBlockHtml}
    </div>
    ${legendTipsHtml}`;

  const patchCtx = {
    layout,
    showReadonly,
    legendTipsOpen,
    chipPatches,
    staleCount: staleRows.length,
    missingCount: missingRows.length,
    healthSummary,
    statTotals: fetcherStatTotals(rows),
  };
  if (tryPatchFetcherHealthDashboard(slot, patchCtx)) {
    slot.dataset.statLayout = layout;
    fetcherRunner.applyFetcherRowLayout();
    syncStatLayoutToggle();
    if (restoreBarToggleFocus) {
      document.querySelector('[data-role="bar-toggle"]')?.focus();
    }
    return;
  }

  slot.dataset.statLayout = layout;
  slot.innerHTML = `
    <div class="fh-bar" data-role="fetcher-bar" title="Click to expand the fetcher console">
      <span class="fh-bar-dot" data-role="bar-dot" aria-hidden="true"></span>
      <span class="fh-bar-status" data-role="bar-status">Fetcher health</span>
      <span class="fh-bar-tail" data-role="bar-tail">No fetcher activity yet.</span>
      <button type="button" class="fh-bar-toggle" data-role="bar-toggle" aria-expanded="false" aria-label="Expand fetcher" title="Expand or collapse the fetcher console">▸</button>
    </div>
    ${readonlyBanner}
    ${overviewHtml}
  `;
  ensureAgeTicker();
  fetcherRunner.applyFetcherRowLayout();
  syncStatLayoutToggle();
  if (restoreBarToggleFocus) {
    document.querySelector('[data-role="bar-toggle"]')?.focus();
  }
}
