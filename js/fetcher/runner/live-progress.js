/**
 * Live-run progress chip + soft stall watch (before the server 60s stall line).
 */

import { updateStallNotice } from './stall-notice.js';
import { SOFT_STALL_NO_PROGRESS_MS } from '../progress-summary.js';

/**
 * @param {{
 *   logPanel: () => HTMLElement | null | undefined,
 *   setStatus: (kind: string, text: string) => void,
 *   getLiveRunId: () => string | null,
 *   resolveChipKey: (key: string | null | undefined) => string | null | undefined,
 * }} deps
 */
export function createLiveProgressController(deps) {
  let lastProgressSummary = '';
  let lastProgressAt = 0;
  let softStallTimer = null;
  let softStallShowing = false;
  let serverStallActive = false;

  function clearSoftStallWatch() {
    if (softStallTimer) {
      clearTimeout(softStallTimer);
      softStallTimer = null;
    }
  }

  function clearSoftStallNotice() {
    softStallShowing = false;
    if (!serverStallActive) updateStallNotice(deps.logPanel(), null);
  }

  function scheduleSoftStallWatch() {
    clearSoftStallWatch();
    if (!deps.getLiveRunId()) return;
    softStallTimer = setTimeout(() => {
      softStallTimer = null;
      if (!deps.getLiveRunId() || serverStallActive) return;
      const ageMs = Date.now() - (lastProgressAt || 0);
      if (ageMs < SOFT_STALL_NO_PROGRESS_MS) {
        scheduleSoftStallWatch();
        return;
      }
      softStallShowing = true;
      updateStallNotice(deps.logPanel(), {
        seconds: Math.round(ageMs / 1000),
        fatal: false,
        soft: true,
      });
    }, SOFT_STALL_NO_PROGRESS_MS);
  }

  function applyProgressSummary(summary, key = null) {
    if (!summary) return;
    lastProgressSummary = summary;
    lastProgressAt = Date.now();
    softStallShowing = false;
    if (!serverStallActive) updateStallNotice(deps.logPanel(), null);
    if (deps.getLiveRunId()) deps.setStatus('running', summary);
    const chipKey = deps.resolveChipKey(key);
    if (chipKey && /^[A-Za-z0-9_-]+$/.test(chipKey)) {
      const chip = document.querySelector(`.fh-chip[data-fetcher-key="${chipKey}"]`);
      if (chip) chip.title = summary;
    }
    scheduleSoftStallWatch();
  }

  function endLiveProgressTracking() {
    clearSoftStallWatch();
    serverStallActive = false;
    softStallShowing = false;
    lastProgressSummary = '';
    lastProgressAt = 0;
    updateStallNotice(deps.logPanel(), null);
  }

  function noteServerStall() {
    serverStallActive = true;
    softStallShowing = false;
    clearSoftStallWatch();
  }

  function clearServerStallFlag() {
    serverStallActive = false;
  }

  function getLastProgressSummary() {
    return lastProgressSummary;
  }

  return {
    applyProgressSummary,
    endLiveProgressTracking,
    clearSoftStallWatch,
    clearSoftStallNotice,
    scheduleSoftStallWatch,
    noteServerStall,
    clearServerStallFlag,
    getLastProgressSummary,
  };
}
