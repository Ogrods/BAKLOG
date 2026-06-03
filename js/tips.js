/**
 * Loading-screen tips for the boot curtain — random helpful hints with a
 * rare easter-egg, cross-fading while the curtain stays up (game-style).
 */

// Keep in sync with the inline boot-tip seed list in index.html (body script).
export const TIPS = [
  "Watch your spotlight for anything you want to recategorize.",
  "Own a physical copy? Add it manually — add whatever you want.",
  "See a Humble icon but no other store? You probably still need to redeem the key in your Humble account.",
  "Sort by time played to see what you actually play, then recategorize from there.",
  "Press / to jump straight to the search box.",
  "Press B, N, P, or F to set a status on the highlighted row.",
  "Ctrl+Z undoes your last status change.",
  "Turn on Hide duplicates to collapse the same game across stores.",
  "Click any dashboard chart to drill into those exact games.",
];

export const RARE_TIP = "My backlog is bigger than yours.";
export const RARE_CHANCE = 0.02;

const TIP_INTERVAL_MS = 4000;
const TIP_FADE_MS = 300;

let _tipTimer = null;
let _tipFadeTimer = null;
let _currentTip = null;

function prefersReducedMotion() {
  return (
    typeof matchMedia === "function" &&
    matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function bootCurtainActive() {
  return (
    typeof document !== "undefined" &&
    document.documentElement?.hasAttribute("data-boot-loading")
  );
}

/** Pick the next tip; ~2% rare easter-egg, else random helpful (no immediate repeat). */
export function pickTip(prev = null) {
  if (Math.random() < RARE_CHANCE) return RARE_TIP;
  const pool = prev ? TIPS.filter(t => t !== prev) : TIPS;
  const choices = pool.length ? pool : TIPS;
  return choices[Math.floor(Math.random() * choices.length)];
}

export function stopBootTipRotation() {
  if (_tipTimer) clearInterval(_tipTimer);
  if (_tipFadeTimer) clearTimeout(_tipFadeTimer);
  _tipTimer = null;
  _tipFadeTimer = null;
  const el = document.getElementById("bootLoadingTip");
  if (el) el.classList.remove("is-fading");
}

function showTip(el, text) {
  if (!el) return;
  el.textContent = text;
  _currentTip = text;
}

function advanceTip(el) {
  if (!el || !bootCurtainActive()) {
    stopBootTipRotation();
    return;
  }
  el.classList.add("is-fading");
  if (_tipFadeTimer) clearTimeout(_tipFadeTimer);
  _tipFadeTimer = setTimeout(() => {
    if (!bootCurtainActive()) {
      stopBootTipRotation();
      return;
    }
    const next = pickTip(_currentTip);
    showTip(el, next);
    el.classList.remove("is-fading");
  }, TIP_FADE_MS);
}

/**
 * Show a random tip on the boot curtain and rotate while loading.
 * @param {HTMLElement | null} el - #bootLoadingTip
 */
export function startBootTipRotation(el) {
  stopBootTipRotation();
  if (!el) return;

  const seeded = el.textContent && el.textContent.trim();
  if (seeded) {
    _currentTip = seeded;
  } else {
    showTip(el, pickTip());
  }

  if (prefersReducedMotion()) return;

  _tipTimer = setInterval(() => {
    if (!bootCurtainActive() || !document.getElementById("bootLoadingTip")) {
      stopBootTipRotation();
      return;
    }
    advanceTip(el);
  }, TIP_INTERVAL_MS);
}
