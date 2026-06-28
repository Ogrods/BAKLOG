/** Fetcher health stat tiles + dashboard patch helpers. */
import { escapeAttr, escapeHtml } from '../../dom-util.js';
import { fetcherSources, fetcherRunner } from '../../fetcher-health-shared.js';
import { ensureAgeTicker } from '../../fetcher-chips.js';
import { statLayout } from './layout.js';
import { fetcherFreshness, humanizeAge } from '../freshness.js';
import {
  isFetcherDisconnected,
  isFetcherReconnectRequired,
} from '../reconnect.js';
import { COUNT_PILL_TITLES } from '../source-meta.js';

function isSourceConnected(row) {
  return row.status !== 'missing'
    && row.status !== 'pending'
    && !isFetcherDisconnected(row.src.key)
    && !isFetcherReconnectRequired(row.src.key);
}

function groupConnectedCount(rows, group) {
  const inGroup = rows.filter(r => r.src.group === group);
  const total = inGroup.length;
  const connected = inGroup.filter(isSourceConnected).length;
  return { connected, total };
}

export function buildFetcherHealthRows() {
  return fetcherSources.map(src => ({ src, ...fetcherFreshness(src) }));
}

/** Auth-healthy for chip filter: not disconnected and not reconnect-required. */
export function isFetcherAuthHealthy(key) {
  return !isFetcherDisconnected(key) && !isFetcherReconnectRequired(key);
}

export function filterFetcherHealthRows(rows, { showConnected, showStaleMissing }) {
  if (!showConnected && !showStaleMissing) return rows;
  return rows.filter(r => {
    const matchConnected = showConnected && isFetcherAuthHealthy(r.src.key);
    const matchStaleMissing = showStaleMissing && (r.status === 'stale' || r.status === 'missing');
    return matchConnected || matchStaleMissing;
  });
}

export function fetcherHealthEmptyMessage({ showConnected, showStaleMissing }) {
  if (!showConnected && !showStaleMissing) return 'No fetchers.';
  if (showConnected && showStaleMissing) {
    return 'No connected or stale/missing fetchers match these filters.';
  }
  if (showConnected) return 'No connected fetchers match this filter.';
  return 'No stale or missing fetchers match this filter.';
}

export function fetcherStatTotals(rows) {
  const total = rows.length;
  const connected = rows.filter(isSourceConnected).length;
  const pct = total ? Math.round((connected / total) * 100) : 0;
  const lib = groupConnectedCount(rows, 'library');
  const wish = groupConnectedCount(rows, 'wishlist');
  const enrich = groupConnectedCount(rows, 'enrich');

  let lastSyncValue = 'never';
  let minAge = Infinity;
  for (const r of rows) {
    if (Number.isFinite(r.ageMs) && r.ageMs < minAge) minAge = r.ageMs;
  }
  if (Number.isFinite(minAge) && minAge !== Infinity) {
    lastSyncValue = `${humanizeAge(minAge)} ago`;
  }
  return { total, connected, pct, lib, wish, enrich, lastSyncValue };
}

function statTileHtml(value, label, title, extraClass = '') {
  return `
    <div class="fh-stat${extraClass ? ` ${extraClass}` : ''}" title="${escapeAttr(title)}">
      <span class="fh-stat-value">${escapeHtml(String(value))}</span>
      <span class="fh-stat-label">${escapeHtml(label)}</span>
    </div>`;
}

export function buildStatTilesHtml(rows) {
  const { lib, wish, enrich, lastSyncValue } = fetcherStatTotals(rows);
  return `
      ${statTileHtml(lastSyncValue, 'Last sync', 'Most recent fetch across all sources', 'fh-stat--lastsync')}
      ${statTileHtml(lib.connected, 'Libraries', `${lib.connected} of ${lib.total} library sources connected`)}
      ${statTileHtml(wish.connected, 'Wishlists', `${wish.connected} of ${wish.total} wishlist sources connected`)}
      ${statTileHtml(enrich.connected, 'Enrichment', `${enrich.connected} of ${enrich.total} enrichment sources connected`)}`;
}

export function buildStatStripHtml(rows, mode = statLayout(), extrasHtml = '') {
  const { total, connected, pct } = fetcherStatTotals(rows);
  const heroTitle = `${connected} of ${total} sources have data and are not disconnected`;
  const heroLabel = mode === 'compact' ? 'Sources' : 'Sources connected';
  const barHtml = `<span class="fh-stat-bar" aria-hidden="true"><span class="fh-stat-bar-fill" style="--pct:${pct}%"></span></span>`;
  const meterHtml = `<span class="fh-stat-meter" aria-hidden="true"><span class="fh-stat-meter-fill" style="--pct:${pct}%"></span></span>`;

  if (mode === 'compact') {
    return `
    <div class="fh-stats fh-stats--compact" role="group" aria-label="Fetcher overview">
      <div class="fh-stat fh-stat--hero" title="${escapeAttr(heroTitle)}">
        <span class="fh-stat-value">${connected}/${total}</span>
        <span class="fh-stat-label">${escapeHtml(heroLabel)}</span>
      </div>
      ${extrasHtml}
      ${buildStatTilesHtml(rows)}
      ${barHtml}
    </div>`;
  }

  // Rail: the meter hero is the only thing in this block. The breakdown tiles
  // and the head controls are placed in the middle rail column by the renderer.
  return `
    <div class="fh-stats fh-stats--rail" role="group" aria-label="Fetcher overview">
      <div class="fh-stat fh-stat--hero fh-stat--meter" title="${escapeAttr(heroTitle)}">
        <span class="fh-stat-value">${connected}/${total}</span>
        <span class="fh-stat-label">${escapeHtml(heroLabel)}</span>
        ${meterHtml}
      </div>
    </div>`;
}

const FH_CHIP_MODIFIER_CLASSES = new Set([
  'fh-chip-needs-config',
  'fh-chip-readonly',
  'fh-chip-auth-cooldown',
  'fh-chip-reconnect-required',
  'fh-chip-disconnected',
  'fh-chip-unavailable',
]);

function patchFetcherChipEl(btn, patch) {
  const statusClasses = [...btn.classList].filter(
    (cls) => cls.startsWith('fh-chip-') && !FH_CHIP_MODIFIER_CLASSES.has(cls),
  );
  for (const cls of statusClasses) btn.classList.remove(cls);
  btn.classList.add(`fh-chip-${patch.displayStatus}`);
  for (const cls of FH_CHIP_MODIFIER_CLASSES) btn.classList.toggle(cls, !!patch.modifiers[cls]);
  btn.dataset.status = patch.status;
  btn.title = patch.title;
  btn.disabled = patch.disabled;
  btn.setAttribute('aria-disabled', patch.disabled ? 'true' : 'false');
  btn.setAttribute('aria-label', patch.chipAriaLabel);
  if (patch.connectProvider) btn.dataset.fetcherConnect = patch.connectProvider;
  else delete btn.dataset.fetcherConnect;
  btn.querySelector('.fh-chip-label').textContent = patch.chipLabel;
  btn.querySelector('.fh-chip-count').textContent = patch.countStr;
  btn.querySelector('.fh-chip-age').textContent = patch.ageText;
  const warn = btn.querySelector('.fh-chip-warn');
  if (patch.showWarn && !warn) {
    btn.insertAdjacentHTML(
      'afterbegin',
      '<span class="fh-chip-warn" title="Missing credentials for this profile - Connections">!</span>',
    );
  } else if (!patch.showWarn && warn) {
    warn.remove();
  }
}

/**
 * Patch chip DOM in place when structure is unchanged (poll refresh without resetting scroll/focus).
 * @returns {boolean}
 */
export function tryPatchFetcherHealthDashboard(slot, ctx) {
  if (!slot?.querySelector?.('.fh-bar')) return false;
  if (slot.dataset.statLayout !== ctx.layout) return false;
  if (!!slot.querySelector('.fh-readonly-banner') !== ctx.showReadonly) return false;
  const legend = slot.querySelector('#fhLegendTips');
  if (!!legend?.classList.contains('is-open') !== ctx.legendTipsOpen) return false;
  const chips = [...slot.querySelectorAll('.fh-chips [data-fetcher-key]')];
  if (chips.length !== ctx.chipPatches.length) return false;
  for (let i = 0; i < chips.length; i++) {
    if (chips[i].dataset.fetcherKey !== ctx.chipPatches[i].key) return false;
  }
  for (let i = 0; i < chips.length; i++) patchFetcherChipEl(chips[i], ctx.chipPatches[i]);

  const staleEl = slot.querySelector('.fh-count--stale');
  if (ctx.staleCount > 0) {
    if (!staleEl) return false;
    staleEl.textContent = `${ctx.staleCount} stale`;
  } else if (staleEl) return false;

  const missingEl = slot.querySelector('.fh-count--missing, .fh-count--fresh');
  if (!missingEl) return false;
  missingEl.textContent = `${ctx.missingCount} missing`;
  missingEl.classList.toggle('fh-count--fresh', ctx.missingCount === 0);
  missingEl.classList.toggle('fh-count--missing', ctx.missingCount > 0);
  missingEl.title = ctx.missingCount === 0 ? COUNT_PILL_TITLES.fresh : COUNT_PILL_TITLES.missing;

  const { lib, wish, enrich, lastSyncValue, connected, total } = ctx.statTotals;
  const hero = slot.querySelector('.fh-stat--hero .fh-stat-value');
  if (hero) hero.textContent = ctx.layout === 'compact' ? `${connected}/${total}` : `${connected}/${total}`;
  const statValues = [...slot.querySelectorAll('.fh-stat-value')];
  const tileValues = statValues.filter((el) => !el.closest('.fh-stat--hero'));
  const tileOrder = [lastSyncValue, String(lib.connected), String(wish.connected), String(enrich.connected)];
  if (tileValues.length !== tileOrder.length) return false;
  for (let i = 0; i < tileOrder.length; i++) tileValues[i].textContent = tileOrder[i];

  const fillEls = slot.querySelectorAll('.fh-stat-bar-fill, .fh-stat-meter-fill');
  for (const el of fillEls) el.style.setProperty('--pct', `${ctx.statTotals.pct}%`);

  fetcherRunner.setBarSummary(ctx.healthSummary);
  ensureAgeTicker();
  return true;
}
