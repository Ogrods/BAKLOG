/** Minimal focus trap for dialogs, drawers, and popovers. */

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * @param {HTMLElement} container
 * @returns {() => void} release trap + restore focus
 */
export function trapFocus(container) {
  const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  const getFocusable = () =>
    [...container.querySelectorAll(FOCUSABLE)].filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    );

  const focusFirst = () => {
    const nodes = getFocusable();
    (nodes[0] || container).focus();
  };

  const onKeyDown = (ev) => {
    if (ev.key !== 'Tab') return;
    const nodes = getFocusable();
    if (!nodes.length) {
      ev.preventDefault();
      return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
      ev.preventDefault();
      first.focus();
    }
  };

  container.addEventListener('keydown', onKeyDown);
  focusFirst();

  return () => {
    container.removeEventListener('keydown', onKeyDown);
    if (previouslyFocused?.isConnected) previouslyFocused.focus();
  };
}

/**
 * @param {HTMLElement} container
 * @param {() => void} onClose
 * @returns {() => void}
 */
export function bindEscapeClose(container, onClose) {
  const onKeyDown = (ev) => {
    if (ev.key === 'Escape') {
      ev.preventDefault();
      onClose();
    }
  };
  container.addEventListener('keydown', onKeyDown);
  return () => container.removeEventListener('keydown', onKeyDown);
}
