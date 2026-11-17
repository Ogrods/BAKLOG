/**
 * Fixed bottom-right status notices (no document-flow layout shift).
 * Replaces in-flow .migration-banner slots for ITAD / claims / watch / etc.
 */

const STACK_ID = "noticeToastStack";

export function ensureNoticeToastStack() {
  if (typeof document === "undefined") return null;
  let stack = document.getElementById(STACK_ID);
  if (!stack) {
    stack = document.createElement("div");
    stack.id = STACK_ID;
    stack.className = "notice-toast-stack";
    stack.setAttribute("aria-live", "polite");
    document.body.appendChild(stack);
  }
  return stack;
}

/**
 * @param {{ id: string, html: string, variant?: string, role?: string, live?: string }} opts
 * @returns {HTMLElement | null}
 */
export function showNoticeToast({
  id,
  html,
  variant = "info",
  role = "status",
  live = "polite",
}) {
  if (!id || typeof document === "undefined") return null;
  const stack = ensureNoticeToastStack();
  if (!stack) return null;
  let el = document.getElementById(id);
  if (!el) {
    el = document.createElement("div");
    el.id = id;
    stack.appendChild(el);
  } else if (el.parentElement !== stack) {
    stack.appendChild(el);
  }
  el.className = `app-notice-toast app-notice-toast--${variant}`;
  el.setAttribute("role", role);
  el.setAttribute("aria-live", live);
  el.innerHTML = html;
  el.classList.remove("hidden");
  return el;
}

/** @param {string} id */
export function hideNoticeToast(id) {
  const el = typeof document !== "undefined" ? document.getElementById(id) : null;
  if (!el) return;
  el.classList.add("hidden");
  el.innerHTML = "";
}

/** @param {string} id */
export function isNoticeToastVisible(id) {
  const el = typeof document !== "undefined" ? document.getElementById(id) : null;
  return !!(el && !el.classList.contains("hidden") && el.parentElement?.id === STACK_ID);
}
