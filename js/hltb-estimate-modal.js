/**
 * Pre-run confirm for large HowLongToBeat enrich jobs.
 * Shows pending count + rough ETA so multi-hour runs are intentional.
 */

import { escapeHtml, formatNum } from './dom-util.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';

const MODAL_ID = 'hltbEstimateModal';
/** Match enrichers/enrich_hltb.py QUERY_DELAY_SEC + LOOKUP_NETWORK_SEC. */
export const HLTB_LOOKUP_SEC = 0.15 + 7.5;
export const HLTB_MODAL_UNCHECKED_MIN = 50;
export const HLTB_MODAL_ETA_MIN_MINUTES = 15;
export const HLTB_MODAL_NOMATCH_MIN = 50;

/**
 * @param {{ unchecked?: number, noMatch?: number, retry?: number } | null} pending
 * @param {{ refresh?: boolean }} [opts]
 */
export function hltbPendingLookupCount(pending, { refresh = false } = {}) {
  if (!pending) return 0;
  const unchecked = pending.unchecked || 0;
  const noMatch = refresh ? (pending.noMatch || 0) : 0;
  return unchecked + noMatch;
}

/** @param {number} pendingLookups */
export function estimateHltbSeconds(pendingLookups) {
  return Math.max(0, Math.round(pendingLookups)) * HLTB_LOOKUP_SEC;
}

/**
 * @param {{ unchecked?: number, noMatch?: number } | null} pending
 * @param {{ refresh?: boolean }} [opts]
 */
export function shouldConfirmHltbRun(pending, { refresh = false } = {}) {
  if (!pending) return false;
  const lookups = hltbPendingLookupCount(pending, { refresh });
  if (lookups <= 0) return false;
  const etaMin = estimateHltbSeconds(lookups) / 60;
  if (pending.unchecked > HLTB_MODAL_UNCHECKED_MIN) return true;
  if (etaMin > HLTB_MODAL_ETA_MIN_MINUTES) return true;
  if (refresh && (pending.noMatch || 0) >= HLTB_MODAL_NOMATCH_MIN) return true;
  return false;
}

function formatEta(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `about ${s}s`;
  const m = Math.round(s / 60);
  if (m < 120) return `about ${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `about ${h}h ${rem}m` : `about ${h}h`;
}

function ensureModal() {
  let modal = document.getElementById(MODAL_ID);
  if (modal) return modal;
  modal = document.createElement('div');
  modal.id = MODAL_ID;
  modal.className =
    'app-modal fixed inset-0 z-50 hidden flex items-center justify-center bg-black/60';
  modal.tabIndex = -1;
  document.body.appendChild(modal);
  return modal;
}

/**
 * @param {{ unchecked?: number, noMatch?: number } | null} pending
 * @param {{ refresh?: boolean }} [opts]
 * @returns {Promise<boolean>}
 */
export function confirmHltbEstimate(pending, { refresh = false } = {}) {
  const lookups = hltbPendingLookupCount(pending, { refresh });
  const eta = formatEta(estimateHltbSeconds(lookups));
  const unchecked = pending?.unchecked || 0;
  const noMatch = pending?.noMatch || 0;
  const retryLine = refresh && noMatch > 0
    ? `<p class="text-sm text-slate-300 mt-2">Shift+click will also retry ${escapeHtml(formatNum(noMatch))} titles cached as no match.</p>`
    : '';

  return new Promise((resolve) => {
    const modal = ensureModal();
    modal.className =
      'app-modal fixed inset-0 z-50 flex items-center justify-center bg-black/60';
    modal.replaceChildren();
    modal.insertAdjacentHTML(
      'beforeend',
      `<div class="app-modal-panel bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-w-md w-full mx-4 p-6" role="dialog" aria-modal="true" aria-labelledby="hltbEstimateTitle">
        <div class="app-modal-body">
          <h2 id="hltbEstimateTitle" class="text-lg font-semibold text-slate-100">Run HowLongToBeat?</h2>
          <p class="text-sm text-slate-300 mt-3">
            About <strong>${escapeHtml(formatNum(lookups))}</strong> lookups
            (${escapeHtml(formatNum(unchecked))} new${refresh && noMatch ? `, ${escapeHtml(formatNum(noMatch))} retries` : ''}).
            Rough ETA: <strong>${escapeHtml(eta)}</strong>.
          </p>
          ${retryLine}
          <p class="text-xs text-slate-400 mt-3">
            Keep this machine awake. Leaving the dashboard open is fine - progress streams in Fetcher health.
            Matched hours save as the run goes.
          </p>
        </div>
        <div class="app-modal-actions">
          <button type="button" class="hltb-estimate-cancel text-sm px-3 py-2 rounded hover:bg-slate-700 text-slate-300">Cancel</button>
          <button type="button" class="hltb-estimate-run bg-cyan-700 hover:bg-cyan-600 px-3 py-2 rounded text-sm text-white">Run HLTB</button>
        </div>
      </div>`,
    );
    modal.classList.remove('hidden');

    let releaseFocus = null;
    const finish = (ok) => {
      releaseFocus?.();
      releaseFocus = null;
      modal.classList.add('hidden');
      modal.replaceChildren();
      resolve(ok);
    };

    const panel = modal.querySelector('.app-modal-panel');
    releaseFocus = trapFocus(panel || modal);
    bindEscapeClose(modal, () => finish(false));
    modal.addEventListener(
      'click',
      (ev) => {
        if (ev.target === modal) finish(false);
      },
      { once: true },
    );
    modal.querySelector('.hltb-estimate-cancel')?.addEventListener(
      'click',
      () => finish(false),
      { once: true },
    );
    modal.querySelector('.hltb-estimate-run')?.addEventListener(
      'click',
      () => finish(true),
      { once: true },
    );
    modal.querySelector('.hltb-estimate-run')?.focus();
  });
}
