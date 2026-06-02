/**
 * In-tab table rebuild indicator (filter / sort / search).
 * Tab switches use viewLoadingOverlay; boot uses bootLoadingOverlay.
 */

import { prefersReducedMotion } from './motion.js';

const SHOW_DELAY_MS = 120;
const HIDE_DELAY_MS = 100;

let _tokenSeq = 0;
let _activeToken = 0;
let _showTimer = null;
let _hideTimer = null;
let _visible = false;

function tableShell() {
  return document.getElementById('tableShell');
}

function overlayEl() {
  return document.getElementById('rowLoadingOverlay');
}

function showOverlay() {
  const shell = tableShell();
  const ov = overlayEl();
  if (!ov || !shell || _visible) return;
  _visible = true;
  shell.setAttribute('aria-busy', 'true');
  ov.setAttribute('aria-hidden', 'false');
  ov.classList.add('show');
}

function hideOverlayNow() {
  const shell = tableShell();
  const ov = overlayEl();
  _visible = false;
  ov?.classList.remove('show');
  ov?.setAttribute('aria-hidden', 'true');
  shell?.removeAttribute('aria-busy');
}

function hideOverlay() {
  if (!_visible) return;
  if (prefersReducedMotion()) {
    hideOverlayNow();
    return;
  }
  clearTimeout(_hideTimer);
  _hideTimer = setTimeout(() => {
    _hideTimer = null;
    hideOverlayNow();
  }, HIDE_DELAY_MS);
}

/** Call before an expensive renderTable() path. Returns opaque token for endRowLoader. */
export function beginRowLoader() {
  const token = ++_tokenSeq;
  _activeToken = token;
  clearTimeout(_showTimer);
  clearTimeout(_hideTimer);
  _showTimer = setTimeout(() => {
    if (_activeToken !== token) return;
    showOverlay();
  }, SHOW_DELAY_MS);
  return token;
}

/** Dismiss loader started with matching token (no-op if superseded). */
export function endRowLoader(token) {
  if (token !== _activeToken) return;
  clearTimeout(_showTimer);
  _showTimer = null;
  _activeToken = 0;
  hideOverlay();
}

/** Hard reset (view switch / invalidate). */
export function forceHideRowLoader() {
  _activeToken = 0;
  clearTimeout(_showTimer);
  clearTimeout(_hideTimer);
  _showTimer = _hideTimer = null;
  hideOverlayNow();
}
