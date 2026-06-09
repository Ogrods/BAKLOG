// Tracks which dashboard metric keys the active library actually surfaces
// (data-gated, pre-disable) and keeps the admin Used/Unused split in sync
// automatically: on every dashboard render, metrics your library has no data
// for are pushed to Unused while your manual hides of data-having metrics are
// preserved. The admin Metrics tab just reads the result — no button needed.

import { state } from './state.js';
import { METRIC_KEYS } from './metric-tips.js';
import { savePrefs } from './prefs.js';
import { mergeUntappedBatchSeed } from './metrics-untapped-batch.js';

const RENDERED_BASE = 'baklog-metrics-rendered';
const ACTIVE_PROFILE_LS = 'baklog-active-profile';

function profileSuffix() {
  let pid = 'default';
  try {
    pid = localStorage.getItem(ACTIVE_PROFILE_LS) || 'default';
  } catch {
    pid = 'default';
  }
  return pid && pid !== 'default' ? `:${pid}` : '';
}

function renderedKey() {
  return `${RENDERED_BASE}${profileSuffix()}`;
}

/** @returns {string[]} */
export function loadRenderedMetricKeys() {
  try {
    const raw = localStorage.getItem(renderedKey());
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr.filter((k) => typeof k === 'string' && k) : [];
  } catch {
    return [];
  }
}

function writeRenderedMetricKeys(keys) {
  try {
    localStorage.setItem(renderedKey(), JSON.stringify([...new Set(keys.filter(Boolean))]));
  } catch {
    /* ignore storage failures */
  }
}

/**
 * Effective disabled set for "no-data metrics go to Unused", preserving the
 * user's manual hides of metrics that DO have data.
 * disabled = (currentDisabled ∩ rendered) ∪ (catalog − rendered)
 * @param {string[]} catalogKeys
 * @param {string[]} renderedKeys
 * @param {string[]} currentDisabled
 * @returns {string[]}
 */
export function computeAutoDisabled(catalogKeys, renderedKeys, currentDisabled = []) {
  const rendered = new Set(renderedKeys);
  const preserved = currentDisabled.filter((k) => rendered.has(k));
  const noData = catalogKeys.filter((k) => !rendered.has(k));
  return [...new Set([...preserved, ...noData])];
}

// Per-render-pass key buckets. Builders note their pre-disable keys here; the
// dashboard orchestrator commits the union once both have run.
let _marqueeKeys = [];
let _insightKeys = [];

/** @param {Iterable<string>} keys */
export function noteMarqueeMetricKeys(keys) {
  _marqueeKeys = [...new Set([...keys].filter(Boolean))];
}

/** @param {Iterable<string>} keys */
export function noteInsightMetricKeys(keys) {
  _insightKeys = [...new Set([...keys].filter(Boolean))];
}

function applyAutoDisabled(rendered) {
  try {
    let current = Array.isArray(state.prefs?.metricsDisabled) ? state.prefs.metricsDisabled : [];
    current = mergeUntappedBatchSeed(current);
    const next = computeAutoDisabled(METRIC_KEYS, rendered, current);
    const curSet = new Set(current);
    const changed = next.length !== current.length || next.some((k) => !curSet.has(k));
    if (changed) {
      state.prefs.metricsDisabled = next;
      savePrefs();
    }
  } catch {
    /* ignore — sync is best-effort */
  }
}

/**
 * Persist the current render's data-available metric set and auto-sync the
 * disabled (Unused) set. Call once per dashboard render, after both the
 * marquee and insight pools have been built.
 */
export function commitRenderedMetrics() {
  const union = [...new Set([..._marqueeKeys, ..._insightKeys])];
  if (!union.length) return;
  writeRenderedMetricKeys(union);
  applyAutoDisabled(union);
}
