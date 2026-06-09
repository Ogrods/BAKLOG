/**
 * Sitewide page scroll lock.
 *
 * Rather than wiring lock/unlock into every modal open/close path, this module
 * watches the DOM for any open modal-like surface and toggles a page-level
 * scroll lock to match. It covers:
 *   - native <dialog> shown via showModal() (matches :modal)
 *   - any [aria-modal="true"] panel that is currently visible
 *     (full-screen overlay modals, the filters drawer, popovers, etc.)
 *
 * Locking sets overflow:hidden on <html> and compensates for the now-missing
 * scrollbar with padding so the layout behind the modal doesn't shift.
 */

const MODAL_SELECTOR = '[aria-modal="true"], dialog';

let _observer = null;
let _rafId = 0;
let _locked = false;
const _saved = { htmlOverflow: '', bodyPaddingRight: '' };

function supportsModalPseudo() {
  try {
    document.documentElement.matches(':modal');
    return true;
  } catch {
    return false;
  }
}

const HAS_MODAL_PSEUDO = supportsModalPseudo();

function isSurfaceOpen(el) {
  if (el.tagName === 'DIALOG') {
    // Only modal dialogs (showModal) should lock scroll, not show()/inline ones.
    if (HAS_MODAL_PSEUDO) {
      try {
        return el.matches(':modal');
      } catch {
        /* fall through */
      }
    }
    return el.open === true;
  }
  // aria-modal panel: open when not explicitly hidden and it actually renders.
  if (el.hidden) return false;
  if (el.getAttribute('aria-hidden') === 'true') return false;
  return el.getClientRects().length > 0;
}

function anyModalOpen() {
  const nodes = document.querySelectorAll(MODAL_SELECTOR);
  for (const el of nodes) {
    if (isSurfaceOpen(el)) return true;
  }
  return false;
}

function applyLock(shouldLock) {
  if (shouldLock === _locked) return;
  const html = document.documentElement;
  const body = document.body;
  if (shouldLock) {
    const scrollbarGap = window.innerWidth - html.clientWidth;
    _saved.htmlOverflow = html.style.overflow;
    _saved.bodyPaddingRight = body.style.paddingRight;
    html.style.overflow = 'hidden';
    if (scrollbarGap > 0) {
      const current = parseFloat(getComputedStyle(body).paddingRight) || 0;
      body.style.paddingRight = `${current + scrollbarGap}px`;
    }
  } else {
    html.style.overflow = _saved.htmlOverflow;
    body.style.paddingRight = _saved.bodyPaddingRight;
  }
  _locked = shouldLock;
}

function reconcile() {
  _rafId = 0;
  applyLock(anyModalOpen());
}

function scheduleReconcile() {
  if (_rafId) return;
  _rafId = requestAnimationFrame(reconcile);
}

export function initScrollLock() {
  if (_observer) return;
  _observer = new MutationObserver(scheduleReconcile);
  _observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ['class', 'hidden', 'aria-hidden', 'open'],
  });
  reconcile();
}
