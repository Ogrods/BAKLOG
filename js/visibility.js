/**
 * Central Page Visibility API — single listener for pause/resume of background work.
 */

const _pausables = new Set();
const _onVisible = new Set();
const _onHidden = new Set();
let _listenerAttached = false;

export function isPageHidden() {
  return typeof document !== 'undefined' && document.visibilityState === 'hidden';
}

function syncPageHiddenAttr() {
  if (typeof document === 'undefined') return;
  if (isPageHidden()) document.documentElement.setAttribute('data-page-hidden', '1');
  else document.documentElement.removeAttribute('data-page-hidden');
}

function dispatchVisibility() {
  const hidden = isPageHidden();
  syncPageHiddenAttr();
  if (hidden) {
    for (const p of _pausables) {
      try { p.pause?.(); } catch (_) { /* ignore */ }
    }
    for (const fn of _onHidden) {
      try { fn(); } catch (_) { /* ignore */ }
    }
  } else {
    for (const p of _pausables) {
      try { p.resume?.(); } catch (_) { /* ignore */ }
    }
    for (const fn of _onVisible) {
      try { fn(); } catch (_) { /* ignore */ }
    }
  }
}

function ensureListener() {
  if (_listenerAttached || typeof document === 'undefined') return;
  _listenerAttached = true;
  document.addEventListener('visibilitychange', dispatchVisibility);
}

/**
 * Register work that should pause when the tab is backgrounded.
 * @param {{ pause?: () => void, resume?: () => void }} handlers
 * @returns {() => void} unregister
 */
export function registerPausable(handlers) {
  ensureListener();
  _pausables.add(handlers);
  syncPageHiddenAttr();
  if (isPageHidden()) {
    try { handlers.pause?.(); } catch (_) { /* ignore */ }
  }
  return () => {
    _pausables.delete(handlers);
  };
}

/** Run fn when the tab becomes visible (not on initial subscribe). */
export function onVisible(fn) {
  ensureListener();
  _onVisible.add(fn);
  return () => { _onVisible.delete(fn); };
}

/** Run fn when the tab becomes hidden (not on initial subscribe). */
export function onHidden(fn) {
  ensureListener();
  _onHidden.add(fn);
  return () => { _onHidden.delete(fn); };
}

/** Test helper — reset registry. */
export function _resetVisibilityForTests() {
  _pausables.clear();
  _onVisible.clear();
  _onHidden.clear();
  if (typeof document !== 'undefined' && _listenerAttached) {
    document.removeEventListener('visibilitychange', dispatchVisibility);
  }
  _listenerAttached = false;
}
