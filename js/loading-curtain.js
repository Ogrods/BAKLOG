/**
 * Unified loading UI for cold boot and tab switches.
 *
 * Boot curtain: #bootLoadingOverlay + html[data-boot-loading] (set in index.html
 * FOUC script, lifted by liftBootCurtain after bootstrap).
 * View overlay: #viewLoadingOverlay scrim on #tableShell (tab switches only).
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
  const label = LOADING_LABELS[view] || LOADING_LABELS.library;
  const ov = document.getElementById("viewLoadingOverlay");
  const lbl = document.getElementById("viewLoadingLabel");
  if (lbl) lbl.textContent = label;
  if (ov) {
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
}

export {
  beginRowLoader,
  endRowLoader,
  forceHideRowLoader,
} from './row-loader.js';
