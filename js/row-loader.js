/**
 * In-tab table rebuild indicator (filter / sort / search).
 * Tab switches use viewLoadingOverlay; boot uses bootLoadingOverlay.
 */

import { prefersReducedMotion } from './motion.js';

const SHOW_DELAY_MS = 60;
const MIN_VISIBLE_MS = 0;
const HIDE_DELAY_MS = 0;

let _tokenSeq = 0;
let _activeToken = 0;
let _showTimer = null;
let _hideTimer = null;
let _minVisibleTimer = null;
let _shownAt = 0;
let _visible = false;
let _hidePending = false;

function tableShell() {
  return document.getElementById('tableShell');
}

function overlayEl() {
  return document.getElementById('rowLoadingOverlay');
}

function nowMs() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

function showOverlay() {
  const shell = tableShell();
  const ov = overlayEl();
  if (!ov || !shell || _visible) return;
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'427a43'},body:JSON.stringify({sessionId:'427a43',location:'row-loader.js:showOverlay',message:'row loading curtain shown',data:{activeView:typeof document!=='undefined'?document.documentElement?.getAttribute('data-active-view'):null},timestamp:Date.now(),hypothesisId:'B'})}).catch(()=>{});
  // #endregion
  _visible = true;
  _shownAt = nowMs();
  shell.setAttribute('aria-busy', 'true');
  ov.setAttribute('aria-hidden', 'false');
  ov.classList.add('show');
}

function hideOverlayNow() {
  const shell = tableShell();
  const ov = overlayEl();
  _visible = false;
  _hidePending = false;
  ov?.classList.remove('show');
  ov?.setAttribute('aria-hidden', 'true');
  shell?.removeAttribute('aria-busy');
}

function hideOverlay() {
  if (!_visible) {
    _hidePending = false;
    return;
  }
  const elapsed = nowMs() - _shownAt;
  const remaining = Math.max(0, MIN_VISIBLE_MS - elapsed);
  if (remaining > 0) {
    _hidePending = true;
    clearTimeout(_minVisibleTimer);
    _minVisibleTimer = setTimeout(() => {
      _minVisibleTimer = null;
      if (_hidePending) hideOverlay();
    }, remaining);
    return;
  }
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
  _hidePending = false;
  clearTimeout(_showTimer);
  clearTimeout(_hideTimer);
  clearTimeout(_minVisibleTimer);
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
  clearTimeout(_minVisibleTimer);
  _showTimer = _hideTimer = _minVisibleTimer = null;
  hideOverlayNow();
}
