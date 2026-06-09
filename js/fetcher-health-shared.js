/**
 * Shared mutable state for fetcher-health submodules (avoids import cycles).
 */

/** @type {import('./fetcher-health.js').FetcherRunner | null} */
export let fetcherRunner = null;

export function setFetcherRunner(runner) {
  fetcherRunner = runner;
}

/** @type {Array<object>} */
export let fetcherSources = [];

export function setFetcherSources(sources) {
  fetcherSources = sources;
}

/** Chip stays in failed styling until the next successful run. */
export const lastRunFailedByKey = new Map();

/** Labels of fetchers that finished OK since the pill was last cleared. */
export const fetchSuccessLabels = new Set();

/** Survives innerHTML rebuilds — native <details> would re-collapse every render. */
export let legendTipsOpen = false;

export function setLegendTipsOpen(open) {
  legendTipsOpen = open;
}

export let itadPendingAutoRun = false;

export function consumeItadAutoRunFlag() {
  const v = itadPendingAutoRun;
  itadPendingAutoRun = false;
  return v;
}

export function markItadPendingAutoRun() {
  itadPendingAutoRun = true;
}
