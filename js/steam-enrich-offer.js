/**
 * One-time post-Steam-success dialog: offer to enrich the library.
 * First seed stamps newCount=0, so auto-enrich alone never covers the first pull.
 */

import { escapeHtml, formatNum } from './dom-util.js';
import { bindEscapeClose, trapFocus } from './focus-trap.js';
import { ENRICH_ORDER } from './fetcher/enrich-order.js';
import { pendingForEnrich } from './fetcher/source-meta.js';
import {
  estimateHltbSeconds,
  formatHltbEta,
  hltbPendingLookupCount,
  shouldConfirmHltbRun,
} from './hltb-estimate-modal.js';
import { savePrefs } from './prefs.js';
import { state } from './state.js';

const MODAL_ID = 'steamEnrichOfferModal';

/**
 * @param {{
 *   prefs?: { steamEnrichOfferSeen?: boolean, autoEnrichOnAdd?: boolean },
 *   libraryGames?: unknown[],
 *   enrichBusy?: boolean,
 * }} [opts]
 */
export function shouldOfferSteamEnrich(opts = {}) {
  const prefs = opts.prefs ?? state.prefs ?? {};
  if (prefs.steamEnrichOfferSeen) return false;
  const games = opts.libraryGames ?? state.allGames ?? [];
  const hasSteam = games.some((g) => (g?.store || '') === 'steam');
  if (!hasSteam) return false;
  if (opts.enrichBusy === true) return false;
  return true;
}

/** Quietly consume the one-shot if auto-enrich is already on. */
export function markSteamEnrichOfferSeenIfNeeded(prefs = state.prefs) {
  if (!prefs) return false;
  if (prefs.steamEnrichOfferSeen) return false;
  if (prefs.autoEnrichOnAdd !== true) return false;
  prefs.steamEnrichOfferSeen = true;
  savePrefs();
  return true;
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
 * @param {{ unchecked?: number, noMatch?: number } | null} [hltbPending]
 * @returns {Promise<boolean>} true = enrich, false = dismiss
 */
export function confirmSteamEnrichOffer(hltbPending = null) {
  const showEta = shouldConfirmHltbRun(hltbPending, { refresh: false });
  const lookups = hltbPendingLookupCount(hltbPending, { refresh: false });
  const eta = formatHltbEta(estimateHltbSeconds(lookups));
  const etaBlock = showEta
    ? `<p class="text-sm text-slate-300 mt-3">
        HowLongToBeat alone is about <strong>${escapeHtml(formatNum(lookups))}</strong> lookups
        (rough ETA: <strong>${escapeHtml(eta)}</strong>). Keep this machine awake - progress streams in Fetcher health.
      </p>`
    : '';

  return new Promise((resolve) => {
    const modal = ensureModal();
    modal.className =
      'app-modal fixed inset-0 z-50 flex items-center justify-center bg-black/60';
    modal.replaceChildren();
    modal.insertAdjacentHTML(
      'beforeend',
      `<div class="app-modal-panel bg-slate-800 border border-slate-600 rounded-lg shadow-xl max-w-md w-full mx-4 p-6" role="dialog" aria-modal="true" aria-labelledby="steamEnrichOfferTitle">
        <div class="app-modal-body">
          <h2 id="steamEnrichOfferTitle" class="text-lg font-semibold text-slate-100">Enrich your Steam library?</h2>
          <p class="text-sm text-slate-300 mt-3">
            Your Steam games are in. Enrichment adds review scores, co-op tags, covers, ProtonDB tiers, and HowLongToBeat playtimes so filters and picks work better.
          </p>
          ${etaBlock}
          <p class="text-xs text-slate-400 mt-3">
            You can turn auto-enrich for new games on or off anytime under Fetcher health.
          </p>
        </div>
        <div class="app-modal-actions">
          <button type="button" class="steam-enrich-offer-dismiss text-sm px-3 py-2 rounded hover:bg-slate-700 text-slate-300">Not now</button>
          <button type="button" class="steam-enrich-offer-run bg-cyan-700 hover:bg-cyan-600 px-3 py-2 rounded text-sm text-white">Enrich library</button>
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
    modal.querySelector('.steam-enrich-offer-dismiss')?.addEventListener(
      'click',
      () => finish(false),
      { once: true },
    );
    modal.querySelector('.steam-enrich-offer-run')?.addEventListener(
      'click',
      () => finish(true),
      { once: true },
    );
    modal.querySelector('.steam-enrich-offer-run')?.focus();
  });
}

function enrichLaneBusy(stateForFn) {
  return ENRICH_ORDER.some((key) => !!stateForFn(key));
}

const ENRICH_OFFER_TOAST_ID = 'steamEnrichOfferNotice';
/** Past AUTO_ENRICH_COOLDOWN_MS (3s) so a deferred retry can clear the gate. */
export const STEAM_ENRICH_OFFER_RETRY_MS = 4000;

async function notifyEnrichDidNotStart(deps = {}) {
  const html =
    'Enrichment could not start right now. Retrying shortly - or open <strong>Fetcher health</strong> and run enrichers there.';
  if (typeof deps.notifyFn === 'function') {
    deps.notifyFn(html);
    return;
  }
  try {
    const { showNoticeToast } = await import('./notice-toast.js');
    showNoticeToast({
      id: ENRICH_OFFER_TOAST_ID,
      html,
      variant: 'info',
    });
  } catch {
    /* non-fatal */
  }
}

async function refreshFetcherHealthPanel() {
  try {
    const { renderDashboardFetcherHealth } = await import('./fetcher/render/dashboard.js');
    renderDashboardFetcherHealth();
  } catch {
    /* non-fatal */
  }
}

/**
 * After a successful Steam catalog reload: one-time offer to enrich.
 * @param {Record<string, unknown>} [deps]
 * @returns {Promise<'skipped'|'seen-quiet'|'dismissed'|'enriched'|'enrich-deferred'|false>}
 */
export async function maybeShowSteamEnrichOffer(deps = {}) {
  const prefs = deps.prefs ?? state.prefs;
  if (!prefs) return 'skipped';

  if (markSteamEnrichOfferSeenIfNeeded(prefs)) return 'seen-quiet';

  let stateForFn = deps.stateFor;
  if (!stateForFn) {
    try {
      const { fetcherRunner } = await import('./fetcher-health-shared.js');
      stateForFn = (k) => fetcherRunner?.stateFor?.(k) ?? null;
    } catch {
      stateForFn = () => null;
    }
  }
  const enrichBusy = deps.enrichBusy ?? enrichLaneBusy(stateForFn);

  if (
    !shouldOfferSteamEnrich({
      prefs,
      libraryGames: deps.libraryGames ?? state.allGames,
      enrichBusy,
    })
  ) {
    return 'skipped';
  }

  const hltbPending = deps.hltbPending ?? pendingForEnrich('hltb');

  const confirmFn = deps.confirmFn ?? confirmSteamEnrichOffer;
  const accepted = await confirmFn(hltbPending);
  const savePrefsFn = deps.savePrefs ?? savePrefs;

  if (!accepted) {
    prefs.steamEnrichOfferSeen = true;
    savePrefsFn();
    return 'dismissed';
  }

  // Consent stands even if the first bootstrap queue is refused.
  prefs.autoEnrichOnAdd = true;
  prefs.steamEnrichOfferSeen = true;
  savePrefsFn();

  const runBootstrap =
    deps.runEnrichBootstrap ??
    (async (bootstrapDeps) => {
      const { runEnrichBootstrap } = await import('./fetcher-auto-refresh.js');
      return runEnrichBootstrap(bootstrapDeps);
    });

  const bootstrapDeps = {
    ...deps,
    stateFor: stateForFn,
    reason: 'steam-first-offer',
  };
  const started = await runBootstrap(bootstrapDeps);

  if (started) {
    await refreshFetcherHealthPanel();
    return 'enriched';
  }

  await notifyEnrichDidNotStart(deps);

  const delayMs = deps.retryDelayMs ?? STEAM_ENRICH_OFFER_RETRY_MS;
  const schedule = deps.setTimeoutFn ?? setTimeout;
  schedule(() => {
    void (async () => {
      try {
        const ok = await runBootstrap({
          ...bootstrapDeps,
          reason: 'steam-first-offer-retry',
          // Fresh clock so cooldown checks use wall time, not the failed call's stub.
          now: undefined,
        });
        if (ok) await refreshFetcherHealthPanel();
      } catch {
        /* non-fatal */
      }
    })();
  }, delayMs);

  return 'enrich-deferred';
}
