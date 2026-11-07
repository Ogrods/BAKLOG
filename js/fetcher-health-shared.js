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

/**
 * Short last-failure message per fetcher key (for Connections cards).
 * @type {Map<string, { message: string, at: number }>}
 */
export const lastRunErrorByKey = new Map();

/** Labels of fetchers that finished OK since the pill was last cleared. */
export const fetchSuccessLabels = new Set();

/** Pick a short user-facing reason from a fetcher run log / exit code. */
export function summarizeRunFailure(logText, exitCode) {
  const lines = String(logText || "")
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter(Boolean);
  let pick = "";
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i].replace(/^\[.*?\]\s*/, "");
    if (/error|fail|http|rate|refus|auth|denied|401|403|429|5\d\d/i.test(line)) {
      pick = line;
      break;
    }
  }
  if (!pick && lines.length) {
    pick = lines[lines.length - 1].replace(/^\[.*?\]\s*/, "");
  }
  pick = String(pick || "").slice(0, 160);
  if (!pick) {
    if (exitCode === 2) pick = "empty result refused";
    else if (exitCode === 3) pick = "drift refused";
    else if (exitCode === 4) pick = "auth failure";
    else if (exitCode != null) pick = `exit ${exitCode}`;
    else pick = "unknown error";
  }
  return pick;
}

/**
 * Most recent sticky last-run error for a Connections provider.
 * @param {string} provider
 * @param {(fetcherKey: string) => string | null | undefined} providerForFetcher
 */
export function lastRunErrorForProvider(provider, providerForFetcher) {
  if (!provider || typeof providerForFetcher !== "function") return null;
  let best = null;
  for (const [key, at] of lastRunFailedByKey.entries()) {
    if (providerForFetcher(key) !== provider) continue;
    const err = lastRunErrorByKey.get(key);
    if (!err?.message) continue;
    const t = typeof at === "number" ? at : err.at || 0;
    if (!best || t >= best.at) {
      best = { message: err.message, at: t, key };
    }
  }
  return best;
}

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
