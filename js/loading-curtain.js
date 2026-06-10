/**
 * Unified loading UI for cold boot and tab switches.
 *
 * Boot curtain: #bootLoadingOverlay + html[data-boot-loading] (set in index.html
 * FOUC script, lifted by liftBootCurtain after bootstrap).
 * View overlay: #viewLoadingOverlay full-viewport scrim (tab switches, all views).
 */

import { startBootTipRotation, stopBootTipRotation } from './tips.js';

export const LOADING_LABELS = {
  dashboard: "Loading dashboard…",
  library: "Loading library…",
  wishlist: "Loading wishlist…",
  itch: "Loading itch.io…",
  connections: "Loading connections…",
};

const MIN_BOOT_VISIBLE_MS = 150;

let _bootCurtainShownAt = null;

function isBootDebugLog() {
  if (typeof window === 'undefined') return false;
  try {
    if (localStorage.getItem('baklog-debug') === '1') return true;
    if (new URLSearchParams(window.location.search).has('debug')) return true;
  } catch (_) { /* private mode / file:// */ }
  return false;
}

/** Force layout/paint after the boot curtain reveals hidden table chrome. */
function nudgeRevealPaint() {
  const run = () => {
    const tbody = document.getElementById('tbody');
    const tbodyRows = tbody
      ? tbody.querySelectorAll('tr:not(.virtual-spacer)').length
      : 0;
    if (isBootDebugLog()) {
      console.log('[baklog-boot] curtain lifted · tbody rows at reveal:', tbodyRows);
    }
    // renderTable runs the same scroll nudge while tbody is visibility:hidden;
    // repeat it once the shell is visible so cells paint on hard refresh.
    if (tbodyRows > 0) {
      void tbody.offsetHeight;
      window.scrollTo(window.scrollX, window.scrollY);
    }
    const shell = document.getElementById('tableShell');
    if (shell && !shell.classList.contains('hidden')) void shell.offsetHeight;
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run);
  else run();
}

function nowMs() {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

function markBootCurtainShown() {
  if (_bootCurtainShownAt == null && document.documentElement?.hasAttribute("data-boot-loading")) {
    _bootCurtainShownAt = nowMs();
  }
}

/** Sync #bootLoadingLabel with the saved active view (called from hydrateState). */
export function setBootCurtainLabel(view) {
  markBootCurtainShown();
  const lbl = document.getElementById("bootLoadingLabel");
  if (lbl && LOADING_LABELS[view]) lbl.textContent = LOADING_LABELS[view];
  if (document.documentElement?.hasAttribute("data-boot-loading")) {
    startBootTipRotation(document.getElementById("bootLoadingTip"));
  }
}

/**
 * Lift the boot curtain after bootstrap (or on failure).
 * @param {number} startedAt - performance.now() when bootstrap() began
 * @param {{ force?: boolean }} [opts] - force=true skips min-visible delay
 */
export function liftBootCurtain(startedAt, opts = {}) {
  if (!document.documentElement.hasAttribute("data-boot-loading")) return;
  const doLift = () => {
    stopBootTipRotation();
    document.documentElement.removeAttribute("data-boot-loading");
    const ov = document.getElementById("bootLoadingOverlay");
    if (ov) ov.setAttribute("aria-busy", "false");
    setTabsDisabled(false);
    _bootCurtainShownAt = null;
    nudgeRevealPaint();
  };
  if (opts.force) {
    doLift();
    return;
  }
  const elapsed = nowMs() - (startedAt || 0);
  const hold = Math.max(0, MIN_BOOT_VISIBLE_MS - elapsed);
  if (hold > 0) setTimeout(doLift, hold);
  else doLift();
}

/** Table-shell scrim during uncached tab switches. */
export function showViewOverlay(view) {
  // #region agent log
  fetch('http://127.0.0.1:7320/ingest/eeb58a78-e0c0-4118-a652-385a89407500',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'427a43'},body:JSON.stringify({sessionId:'427a43',location:'loading-curtain.js:showViewOverlay',message:'view loading curtain shown',data:{view},timestamp:Date.now(),hypothesisId:'B'})}).catch(()=>{});
  // #endregion
  const label = LOADING_LABELS[view] || LOADING_LABELS.library;
  const ov = document.getElementById("viewLoadingOverlay");
  const lbl = document.getElementById("viewLoadingLabel");
  if (lbl) lbl.textContent = label;
  if (ov) {
    const header = document.querySelector(".app-header");
    const top = header ? Math.ceil(header.getBoundingClientRect().bottom) : 0;
    ov.style.setProperty("--view-overlay-top", `${top}px`);
    ov.setAttribute("aria-hidden", "false");
    ov.classList.add("show");
  }
  document.querySelectorAll(".view-tab").forEach(b => { b.disabled = true; });
}

export function hideViewOverlay() {
  const ov = document.getElementById("viewLoadingOverlay");
  if (ov) {
    ov.classList.remove("show");
    ov.setAttribute("aria-hidden", "true");
  }
  document.querySelectorAll(".view-tab").forEach(b => { b.disabled = false; });
}

export function isViewOverlayVisible() {
  const ov = document.getElementById("viewLoadingOverlay");
  return !!(ov && ov.classList.contains("show"));
}

/** Snapshot for ?debug=1 overlay. */
export function getCurtainState() {
  const bootReason = document.documentElement.getAttribute("data-boot-loading");
  const bootElapsedMs =
    bootReason && _bootCurtainShownAt != null
      ? Math.round(nowMs() - _bootCurtainShownAt)
      : null;
  const viewOv = document.getElementById("viewLoadingOverlay");
  const viewLbl = document.getElementById("viewLoadingLabel");
  return {
    bootReason,
    bootElapsedMs,
    viewOverlayShown: !!viewOv?.classList.contains("show"),
    viewOverlayLabel: viewLbl?.textContent?.trim() || null,
  };
}

function setTabsDisabled(disabled) {
  if (typeof document === "undefined") return;
  document.querySelectorAll(".view-tab").forEach(b => {
    b.disabled = !!disabled;
    if (disabled) b.setAttribute("aria-disabled", "true");
    else b.removeAttribute("aria-disabled");
  });
}

if (typeof document !== "undefined") {
  markBootCurtainShown();
  if (document.documentElement?.hasAttribute("data-boot-loading")) {
    setTabsDisabled(true);
  }
  window.__baklogLiftBootCurtain = (opts) => liftBootCurtain(0, opts || { force: true });
}

export {
  beginRowLoader,
  endRowLoader,
  forceHideRowLoader,
} from './row-loader.js';
