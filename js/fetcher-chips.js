/**
 * Fetcher chip DOM helpers — cosmetic age ticker and dashboard chip render.
 * Heavy render logic stays wired from fetcher-health.js to avoid import cycles.
 */
import { fetcherSources, legendTipsOpen } from './fetcher-health-shared.js';

let wired = {};

export function wireFetcherChips(modules) {
  wired = { ...wired, ...modules };
}

const AGE_TICK_MS = 60_000;
const FAST_AGE_TICK_MS = 1_000;
const FAST_AGE_WINDOW_MS = 60_000;

let ageTickTimer = null;
let fastTickTimer = null;
let fastTickRemaining = 0;

function cosmeticAgeLabel(src) {
  const freshness = wired.fetcherFreshness;
  const humanize = wired.humanizeAge;
  if (!freshness || !humanize) return ' - ';
  const { ageMs, ageLabel } = freshness(src);
  if (!Number.isFinite(ageMs)) return ageLabel;
  return humanize(Math.max(0, ageMs));
}

function chipShowsPlainAge(src, deps = {}) {
  const stateFor = deps.stateFor ?? (k => wired.fetcherRunner?.stateFor(k));
  if (stateFor(src.key)) return false;
  if (wired.isFetcherReconnectRequired?.(src.key)) return false;
  if (wired.authCooldownRemainingMs?.(src.key) > 0) return false;
  if (wired.lastRunFailedByKey?.has(src.key)) return false;
  const freshness = wired.fetcherFreshness;
  if (!freshness) return false;
  const { status } = freshness(src);
  if (status === 'missing') return false;
  return true;
}

function tickRefreshChipAges(deps = {}) {
  if (typeof document !== 'undefined' && document.hidden) return true;
  const slot = document.getElementById('dashboardFetcherHealth');
  if (!slot) return false;
  const sources = deps.sources ?? fetcherSources;
  for (const src of sources) {
    if (!chipShowsPlainAge(src, deps)) continue;
    const chip = slot.querySelector(`.fh-chip[data-fetcher-key="${src.key}"]`);
    const ageSpan = chip?.querySelector('.fh-chip-age');
    if (!ageSpan) continue;
    const label = cosmeticAgeLabel(src);
    if (ageSpan.textContent !== label) ageSpan.textContent = label;
  }
  return true;
}

export function refreshChipAgesInPlace(deps = {}) {
  return tickRefreshChipAges(deps);
}

export function stopAgeTicker() {
  if (ageTickTimer) clearInterval(ageTickTimer);
  ageTickTimer = null;
}

export function ensureAgeTicker() {
  if (ageTickTimer) return;
  ageTickTimer = setInterval(() => {
    if (!tickRefreshChipAges()) stopAgeTicker();
  }, AGE_TICK_MS);
}

export function stopFastAgeTick() {
  if (fastTickTimer) clearInterval(fastTickTimer);
  fastTickTimer = null;
  fastTickRemaining = 0;
}

export function isFastAgeTickActive() {
  return fastTickTimer != null;
}

export function startFastAgeTick() {
  const ticks = Math.ceil(FAST_AGE_WINDOW_MS / FAST_AGE_TICK_MS);
  fastTickRemaining = Math.max(fastTickRemaining, ticks);
  if (fastTickTimer) return;
  fastTickTimer = setInterval(() => {
    const cont = tickRefreshChipAges();
    fastTickRemaining -= 1;
    if (!cont || fastTickRemaining <= 0) stopFastAgeTick();
  }, FAST_AGE_TICK_MS);
}

if (typeof document !== 'undefined' && !document.__baklogFetcherAgeVisListener) {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      try { tickRefreshChipAges(); } catch (_) { /* panel not mounted */ }
    }
  });
  document.__baklogFetcherAgeVisListener = true;
}

/** Re-export render helpers owned by fetcher-health (wired at init). */
export function renderDashboardFetcherHealth() {
  return wired.renderDashboardFetcherHealth?.();
}

export function toggleLegendTips() {
  wired.setLegendTipsOpen?.(!legendTipsOpen);
  renderDashboardFetcherHealth();
}

export function cycleStatLayout() {
  return wired.cycleStatLayout?.();
}
