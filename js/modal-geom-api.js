/**
 * Playwright modal geometry helpers (window.__baklogModalGeom).
 * Pass: body bottom + gapPx <= actions top; actions bottom inside panel.
 */

export const MODAL_GEOM_GAP_PX = 4;

/**
 * @param {string} modalId
 * @returns {{ ok: boolean, reason?: string, gap?: number, bodyBottom?: number, actionsTop?: number, actionsBottom?: number, panelBottom?: number }}
 */
export function measureModalLayout(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal || modal.classList.contains('hidden')) {
    return { ok: false, reason: 'modal-hidden' };
  }
  const panel =
    modal.querySelector('[role="dialog"]') ||
    modal.querySelector('.app-modal-panel');
  if (!panel) return { ok: false, reason: 'no-panel' };
  const body = panel.querySelector('.app-modal-body');
  const actions = panel.querySelector('.app-modal-actions');
  if (!body || !actions) return { ok: false, reason: 'missing-body-actions' };

  const bodyRect = body.getBoundingClientRect();
  const actionsRect = actions.getBoundingClientRect();
  const panelRect = panel.getBoundingClientRect();
  const gap = actionsRect.top - bodyRect.bottom;
  const bodyActionsOk = gap >= MODAL_GEOM_GAP_PX - 0.5;
  const actionsInPanel = actionsRect.bottom <= panelRect.bottom + 1;
  const bodyVisible = bodyRect.height > 0 && bodyRect.bottom > panelRect.top;
  const actionsVisible = actionsRect.height > 0;

  let reason;
  if (!bodyActionsOk) reason = `overlap gap=${Math.round(gap * 10) / 10}`;
  else if (!actionsInPanel) reason = 'actions-outside-panel';
  else if (!bodyVisible) reason = 'body-not-visible';
  else if (!actionsVisible) reason = 'actions-not-visible';

  return {
    ok: bodyActionsOk && actionsInPanel && bodyVisible && actionsVisible,
    gap: Math.round(gap * 10) / 10,
    bodyBottom: Math.round(bodyRect.bottom),
    actionsTop: Math.round(actionsRect.top),
    actionsBottom: Math.round(actionsRect.bottom),
    panelBottom: Math.round(panelRect.bottom),
    reason,
  };
}

function firstListKey() {
  return window.__baklogDrillGeom?.visibleListKeys?.()?.[0] || null;
}

/** Expose modal geometry helpers for Playwright audits. */
export function installModalGeomApi() {
  if (typeof window === 'undefined') return;
  window.__baklogModalGeom = {
    gapPx: MODAL_GEOM_GAP_PX,
    measure: measureModalLayout,
    firstGameKey: firstListKey,
    async openHltb() {
      const { confirmHltbEstimate } = await import('./hltb-estimate-modal.js');
      void confirmHltbEstimate({ unchecked: 100, noMatch: 0 });
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    },
    closeHltb() {
      document.querySelector('#hltbEstimateModal .hltb-estimate-cancel')?.click();
      const modal = document.getElementById('hltbEstimateModal');
      modal?.classList.add('hidden');
      modal?.replaceChildren();
    },
    async openNotes(key) {
      const k = key || firstListKey();
      if (!k) return false;
      const { openNotesDialog } = await import('./notes-dialog.js');
      openNotesDialog(k);
      return true;
    },
    closeNotes() {
      import('./notes-dialog.js').then((m) => m.closeNotesDialog());
    },
    async openAddGame() {
      document.getElementById('addGameBtn')?.click();
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const modal = document.getElementById('addGameModal');
      return !!(modal && !modal.classList.contains('hidden'));
    },
    closeAddGame() {
      document.getElementById('addGameClose')?.click();
      const modal = document.getElementById('addGameModal');
      modal?.classList.add('hidden');
      modal?.classList.remove('flex');
    },
  };
}
