// Library-count "1UP" animation: rolling number + scrolling-combat-text popups.
//
// Design constraints:
//   - Cheap: popups use CSS keyframes (composited transform/opacity), not rAF.
//   - Bounded: hard cap on popup count (POPUP_CAP) regardless of delta size.
//   - Safe under churn: each surface owns one episode; a new fire-against
//     the same surface cancels the prior one so back-to-back fetcher reloads
//     don't pile DOM.
//   - Safe under navigation: the spawn loop tracks the host node; if it
//     detaches mid-animation (view switch, dashboard rerender) we abort and
//     clean up the popup pool. Tab visibility hidden -> instant settle.
//   - Honors prefers-reduced-motion: instant text snap, zero popups.

import { state } from './state.js';
import { prefersReducedMotion } from './motion.js';
import {
  countUpDurationForDelta,
  easeInOutCubic,
  heroCountRollMs,
} from './dashboard-shared.js';

// Match landing mega-hero demo (`landing/demo.js` COUNT_ROLL_MS).
const COUNT_ROLL_MS = 1000;
/** Gap between sequential +1 popups — matches runLibraryCountSmallDemo stepMs. */
const SEQ_POPUP_GAP_MS = 300;
const POPUP_LIFETIME_MS = 700;
const POPUP_CAP = 10;
/** Through this delta, one +1 popup per game and each fires on its integer tick. */
const STRICT_POPUP_SYNC_MAX = 15;
// Tight jitter — popups stack as a column off the right edge of the number,
// drifting up + slightly outward. Big values look more like noise than text.
const JITTER_PX = 4;

const SURFACE_KEY = '__baklogLibCountAnim';
/** Every surface with an in-flight episode (survives DOM detachment on tab switch). */
const _activeSurfaces = new Set();
/** Episodes whose roll finished but timed +1 spawns may still be pending. */
const _lingeringEpisodes = new Set();

function fmtPlain(n) { return String(Math.round(n)); }
function fmtCommas(n) {
  return Math.round(n).toLocaleString('en-US');
}

/**
 * Cancel an in-flight episode on `node`.
 *
 * @param {HTMLElement} node
 * @param {{ keepPopups?: boolean }} [opts]
 *   keepPopups=true (default) leaves any popups still climbing alone so a
 *   fresh episode (e.g. another store landing 200ms later) doesn't visually
 *   eat the previous burst. Their own animationend handlers will reap them.
 */
function cancelEpisode(node, opts = {}) {
  if (!node) return;
  const prev = node[SURFACE_KEY];
  if (!prev) return;
  if (prev.rafId) cancelAnimationFrame(prev.rafId);
  if (prev.spawnTimers) {
    for (const id of prev.spawnTimers) clearTimeout(id);
  }
  // Chained demo/fetcher bursts: if a replacement episode cut the roll short,
  // still show one +1 so rapid landings do not look silent.
  if (
    prev.to > prev.from
    && prev.popupsSpawned === 0
    && prev.host
    && opts.keepPopups !== false
  ) {
    mountOnePopup(prev.host, prev.node, 0);
  }
  // Settle text to its final value so we never leave half-rolled digits.
  try { if (prev.format && prev.to != null) node.textContent = prev.format(prev.to); } catch (_) {}
  // Only nuke popups when we're tearing down for real (view switch / page hide).
  // During a chained fetcher landing, we let prior popups finish on their own.
  if (opts.keepPopups === false && prev.host && prev.host.isConnected) {
    prev.host.querySelectorAll('.library-count-popup').forEach(el => el.remove());
  }
  if (opts.keepPopups === false && prev.node?.id) {
    document.querySelectorAll(`.library-count-popup[data-libcount-surface="${prev.node.id}"]`)
      .forEach(el => el.remove());
  }
  _lingeringEpisodes.delete(prev);
  node[SURFACE_KEY] = null;
  _activeSurfaces.delete(node);
}

/**
 * Natural end of a roll: drop the animating flag so handoff / charts / a
 * second burst can proceed, but leave CSS popups climbing until animationend.
 * Timed spawn callbacks stay on a lingering episode so cancelAll can still
 * clearTimeout them (do not clear spawnTimers here).
 */
function finishEpisode(node) {
  if (!node) return;
  const prev = node[SURFACE_KEY];
  if (!prev) return;
  if (prev.rafId) {
    cancelAnimationFrame(prev.rafId);
    prev.rafId = 0;
  }
  try {
    if (prev.format && prev.to != null) node.textContent = prev.format(prev.to);
  } catch (_) { /* ignore */ }
  if (prev.spawnTimers && prev.spawnTimers.length) {
    _lingeringEpisodes.add(prev);
  }
  node[SURFACE_KEY] = null;
  _activeSurfaces.delete(node);
}

function ensureHost(node) {
  // Animation surface is a positioned wrapper. We accept either the count
  // node itself (then we mount popups on its offsetParent if it's already
  // .library-count-host) or a designated [data-libcount-host] ancestor.
  if (!node || !node.parentElement) return null;
  // Prefer an explicit declared host so callers can control where popups live.
  const explicit = node.closest('[data-libcount-host]');
  if (explicit) return explicit;
  // Otherwise wrap on demand: idempotent — once wrapped, the wrapper persists.
  const parent = node.parentElement;
  if (parent.classList.contains('library-count-host')) return parent;
  // Fallback: don't wrap silently (we'd risk breaking layout on third-party
  // surfaces). Just position popups against the parent if it's already
  // positioned; otherwise skip popups for that surface this episode.
  return null;
}

function nodeStillAlive(node) {
  return !!(node && node.isConnected);
}

function popupSpawnDelays(delta, popupCount, durationMs) {
  if (popupCount <= 0) return [];
  // Fire slightly before roll end so finishEpisode never clearTimeouts a
  // same-ms spawn (linger path keeps timers, but early is smoother anyway).
  if (popupCount === 1) return [Math.max(0, durationMs - 80)];
  const gapMs = Math.max(
    80,
    Math.min(SEQ_POPUP_GAP_MS, Math.floor((durationMs * 0.92) / (popupCount - 1))),
  );
  return Array.from({ length: popupCount }, (_, i) => i * gapMs);
}

function activePopupStackIndex(anchorNode) {
  const surfaceKey = anchorNode?.id || '';
  if (!surfaceKey || typeof document === 'undefined') return 0;
  return document.querySelectorAll(
    `.library-count-popup[data-libcount-surface="${surfaceKey}"]`,
  ).length;
}

/** Minimum roll duration so tick-synced +1 popups stay readable (not piled on 700ms CSS). */
export function strictSyncRollMs(delta, popupCap) {
  let durationMs = countUpDurationForDelta(delta);
  if (popupCap > 0) {
    const popupTrainMs = (popupCap - 1) * SEQ_POPUP_GAP_MS + countUpDurationForDelta(1);
    durationMs = Math.max(durationMs, popupTrainMs, POPUP_LIFETIME_MS);
  }
  return Math.max(120, durationMs);
}

/** Mount one scrolling-combat-text +1 popup beside `anchorNode`. */
function mountOnePopup(host, anchorNode, stackIndex = null) {
  if (!host || !host.isConnected) return;
  const surfaceKey = anchorNode?.id || '';
  const el = document.createElement('span');
  el.className = 'library-count-popup';
  if (surfaceKey) el.dataset.libcountSurface = surfaceKey;
  el.setAttribute('aria-hidden', 'true');
  el.textContent = '+1';
  const dx = (Math.random() * JITTER_PX * 2) - (JITTER_PX * 0.5);
  el.style.setProperty('--baklog-dx', `${dx.toFixed(1)}px`);
  const anchorEl = anchorNode?.isConnected ? anchorNode : host;
  const rect = anchorEl?.getBoundingClientRect?.();
  const hasRect = rect && (rect.width > 0 || rect.height > 0);
  if (hasRect && typeof document !== 'undefined') {
    const fs = parseFloat(getComputedStyle(anchorEl).fontSize) || 16;
    const isHero = anchorEl.id === 'dashHeroCount';
    el.classList.add('library-count-popup--floated');
    let popupFs;
    if (!isHero) {
      el.classList.add('library-count-popup--floated-chip');
      popupFs = Math.max(20, Math.min(32, fs * 1.75));
      el.style.fontSize = `${popupFs.toFixed(1)}px`;
    } else {
      popupFs = Math.max(28, Math.min(52, fs * 0.48));
      el.style.fontSize = `${popupFs.toFixed(1)}px`;
    }
    const stack = Number.isFinite(stackIndex) ? stackIndex : activePopupStackIndex(anchorNode);
    let left = rect.right + Math.max(3, fs * 0.25);
    let top;
    if (isHero) {
      // Top-right anchor; stack upward so bursts do not pile at the bottom-right.
      top = rect.top - stack * popupFs * 0.55;
    } else {
      top = rect.top + stack * fs * 0.55;
    }
    if (typeof window !== 'undefined') {
      left = Math.min(left, window.innerWidth - 80);
      top = Math.max(8, Math.min(top, window.innerHeight - 40));
    }
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
    document.body.appendChild(el);
  } else {
    host.appendChild(el);
  }
  const reap = setTimeout(() => { if (el.isConnected) el.remove(); }, POPUP_LIFETIME_MS + 200);
  el.addEventListener('animationend', () => {
    clearTimeout(reap);
    if (el.isConnected) el.remove();
  }, { once: true });
}

function syncPopupsOnTick(episode, v) {
  if (!episode.tickPopups || !episode.host) return;
  const displayed = Math.min(episode.to, Math.round(v));
  // One popup per animation frame — a stalled main thread must not dump the
  // whole strict-sync train in a single rAF callback.
  if (
    episode.lastPopupInt < displayed
    && episode.popupsSpawned < episode.popupCap
    && episode.lastPopupInt < episode.to
  ) {
    episode.lastPopupInt += 1;
    if (episode.lastPopupInt > episode.from) {
      mountOnePopup(episode.host, episode.node, episode.popupsSpawned);
      episode.popupsSpawned += 1;
    }
  }
}

/**
 * Spawn a train of sequential "+1" popups beside `anchorNode`. Each label is
 * always +1 (combat-text style); large imports cap at POPUP_CAP pops, not
 * chunked sums like +44. Small deltas (<= STRICT_POPUP_SYNC_MAX) fire one popup
 * per integer step; larger deltas loosen across ~92% of the roll.
 */
function spawnPopups(host, popupCount, opts) {
  if (!host || !host.isConnected || popupCount <= 0) return [];
  const timers = [];
  const anchorNode = opts?.anchorNode || host;
  const delays = opts?.delays ?? popupSpawnDelays(
    opts?.delta ?? popupCount,
    popupCount,
    opts?.durationMs ?? COUNT_ROLL_MS,
  );
  for (let i = 0; i < popupCount; i++) {
    const delay = delays[i];
    const id = setTimeout(() => {
      if (!host.isConnected && !anchorNode.isConnected) return;
      mountOnePopup(host, anchorNode, i);
      if (i === popupCount - 1 && opts?.episode) {
        _lingeringEpisodes.delete(opts.episode);
      }
    }, delay);
    timers.push(id);
  }
  if (opts && opts.onTimers) opts.onTimers(timers);
  return timers;
}

/**
 * Animate `node.textContent` from `from` to `to` and (optionally) spawn
 * scrolling-combat-text style "+N" popups inside its host wrapper.
 *
 * @param {HTMLElement} node - The element whose textContent is the count.
 * @param {number} from
 * @param {number} to
 * @param {(n:number)=>string} format
 * @param {{ popups?: boolean, durationMs?: number }} [opts]
 */
export function flashCountUp(node, from, to, format = fmtCommas, opts = {}) {
  if (!node || !node.isConnected) return;
  const safeFrom = Number.isFinite(from) ? from : 0;
  const safeTo = Number.isFinite(to) ? to : safeFrom;
  if (safeTo === safeFrom) {
    node.textContent = format(safeTo);
    return;
  }
  cancelEpisode(node);

  // Reduced motion: skip popups AND the roll; jump straight to final.
  if (prefersReducedMotion()) {
    node.textContent = format(safeTo);
    return;
  }
  // Document hidden: don't burn an animation no one will see.
  if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
    node.textContent = format(safeTo);
    return;
  }

  const wantPopups = opts.popups !== false && safeTo > safeFrom;
  const host = wantPopups ? ensureHost(node) : null;
  const delta = safeTo - safeFrom;
  const strictSync = delta <= STRICT_POPUP_SYNC_MAX;
  const popupCap = host && wantPopups
    ? (strictSync ? delta : Math.min(delta, POPUP_CAP))
    : 0;
  const popupCount = popupCap;
  const isHeroMount = !!(host && host.closest('.dash-mega'));
  const userDuration = Number.isFinite(opts.durationMs) ? opts.durationMs : null;
  let durationMs = userDuration;
  if (!userDuration) {
    if (strictSync) {
      durationMs = strictSyncRollMs(delta, popupCap);
    } else {
      durationMs = isHeroMount ? heroCountRollMs(delta, popupCount) : COUNT_ROLL_MS;
    }
  }
  if (!userDuration && !strictSync) {
    const popupTrainMs = popupCount > 0 ? (popupCount - 1) * SEQ_POPUP_GAP_MS + 400 : 0;
    durationMs = Math.max(120, durationMs, popupTrainMs);
  } else {
    durationMs = Math.max(120, durationMs);
  }
  // Keep the digit roll alive at least as long as one +1 CSS flight so a
  // single acquisition does not "finish" while the popup is still climbing.
  if (!userDuration && popupCap > 0) {
    durationMs = Math.max(durationMs, POPUP_LIFETIME_MS);
  }
  // Strict sync stays linear so integer ticks stay evenly spaced; large
  // capped trains ease for a softer stop.
  const easeRoll = !strictSync;
  const episode = {
    node,
    host,
    from: safeFrom,
    to: safeTo,
    format,
    delta,
    popupCap,
    lastPopupInt: safeFrom,
    popupsSpawned: 0,
    tickPopups: !!(host && wantPopups && popupCap > 0 && strictSync),
    rafId: 0,
    spawnTimers: [],
  };
  node[SURFACE_KEY] = episode;
  _activeSurfaces.add(node);

  if (host && wantPopups && popupCap > 0 && !strictSync) {
    episode.spawnTimers = spawnPopups(host, popupCount, {
      anchorNode: node,
      delta,
      durationMs,
      episode,
    });
  }

  const start = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  function tick(now) {
    // Guardrail: if the user navigated away and our host detached
    // mid-animation, snap to final and bail.
    if (!nodeStillAlive(node)) {
      cancelEpisode(node, { keepPopups: false });
      return;
    }
    // Tab went hidden mid-roll: settle now, drop scheduled spawns.
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
      node.textContent = format(safeTo);
      cancelEpisode(node, { keepPopups: false });
      return;
    }
    const elapsed = (now || performance.now()) - start;
    const t = Math.min(1, elapsed / durationMs);
    const eased = easeRoll ? easeInOutCubic(t) : t;
    const v = safeFrom + (safeTo - safeFrom) * eased;
    node.textContent = format(v);
    if (episode.tickPopups) syncPopupsOnTick(episode, v);
    if (t < 1) {
      episode.rafId = requestAnimationFrame(tick);
    } else {
      node.textContent = format(safeTo);
      if (episode.tickPopups) syncPopupsOnTick(episode, safeTo);
      episode.rafId = 0;
      // Clear sticky animating flag; CSS popups finish on their own.
      finishEpisode(node);
    }
  }
  episode.rafId = requestAnimationFrame(tick);
}

// The combat-text popups must NOT fire during the initial page-load count-up
// (boot does at least one applyMergedLibrary, sometimes 0 -> full, which would
// otherwise read as a giant addition). We stay disarmed until bootstrap
// finishes and explicitly arms us, so popups only appear on genuine live
// fetcher/manual additions. The rolling count-up on the hero is unaffected —
// that's animateCount, not this module.
let _armed = false;

/** Called once at the end of bootstrap so live additions can animate. */
export function armLibraryCountAnimations() {
  _armed = true;
}

/** Test/diagnostic helper — re-disarm (used by tests). */
export function disarmLibraryCountAnimations() {
  _armed = false;
}

/**
 * High-level entry point: animate every mounted surface for this `kind`.
 * Called from applyMergedLibrary() with `prev` and `next` counts.
 */
export function fireLibraryCountFlash(kind, prev, next, rowOpts = {}) {
  if (typeof document === 'undefined') return;
  // Disarmed until boot completes — initial count-up never spawns popups.
  if (!_armed) return;
  if (!Number.isFinite(prev) || !Number.isFinite(next)) return;
  if (next === prev) return;
  // We never visualize decreases as "−1" popups; just settle text quietly.
  const isDecrease = next < prev;
  const surfaces = collectSurfaces(kind, prev, next, rowOpts);
  for (const surface of surfaces) {
    const from = surface.prev;
    const to = surface.next;
    if (!Number.isFinite(from) || !Number.isFinite(to) || to === from) continue;
    flashCountUp(surface.node, from, to, surface.format, {
      popups: !isDecrease && to > from,
    });
  }
}

function collectSurfaces(kind, prev, next, rowOpts = {}) {
  const out = [];
  if (kind === 'library') {
    // Hero number on Dashboard. Only animate if visible (Dashboard mounted
    // AND active view is Dashboard). Otherwise the user wouldn't see it
    // and the next switchView() will paint the final value cleanly.
    if (state.activeView === 'dashboard') {
      const hero = document.getElementById('dashHeroCount');
      if (hero) out.push({ node: hero, format: fmtCommas, prev, next });
    }
    // Summary chip: "Games <N>"
    const libChip = document.querySelector('[data-count-target="library"]');
    if (libChip && state.activeView === 'library') {
      out.push({ node: libChip, format: fmtPlain, prev, next });
    }
    // Row count under the table ("Showing N of …") — respects active filters.
    const rowPrev = rowOpts.rowPrev;
    const rowNext = rowOpts.rowNext;
    const rowChip = document.querySelector('[data-count-target="rowcount-library"]');
    if (
      rowChip
      && state.activeView === 'library'
      && Number.isFinite(rowPrev)
      && Number.isFinite(rowNext)
      && rowNext > rowPrev
    ) {
      out.push({ node: rowChip, format: fmtPlain, prev: rowPrev, next: rowNext });
    }
  } else if (kind === 'wishlist') {
    const wlChip = document.querySelector('[data-count-target="wishlist"]');
    if (wlChip && state.activeView === 'wishlist') {
      out.push({ node: wlChip, format: fmtPlain, prev, next });
    }
    const rowPrev = rowOpts.rowPrev;
    const rowNext = rowOpts.rowNext;
    const rowChip = document.querySelector('[data-count-target="rowcount-wishlist"]');
    if (
      rowChip
      && state.activeView === 'wishlist'
      && Number.isFinite(rowPrev)
      && Number.isFinite(rowNext)
      && rowNext > rowPrev
    ) {
      out.push({ node: rowChip, format: fmtPlain, prev: rowPrev, next: rowNext });
    }
  }
  return out;
}

/** True when this surface has an in-flight roll or pending popup spawns. */
export function isSurfaceAnimating(node) {
  return !!(node && node[SURFACE_KEY]);
}

/**
 * Abort any in-flight count animations on every surface we know about and
 * remove any popups still climbing. Called from view switches and visibility
 * change. Use this when we're tearing down for real — for fresh episodes on
 * the same surface, flashCountUp does a soft cancel that preserves climbing
 * popups for a smoother chained-fetcher experience.
 */
export function cancelAllLibraryCountAnimations() {
  for (const node of [..._activeSurfaces]) cancelEpisode(node, { keepPopups: false });
  for (const ep of [..._lingeringEpisodes]) {
    if (ep.spawnTimers) {
      for (const id of ep.spawnTimers) clearTimeout(id);
    }
    ep.spawnTimers = [];
    _lingeringEpisodes.delete(ep);
  }
  document.querySelectorAll('[data-count-target]').forEach(n => cancelEpisode(n, { keepPopups: false }));
  const hero = document.getElementById('dashHeroCount');
  if (hero) cancelEpisode(hero, { keepPopups: false });
  // Sweep stray popups anywhere on the page.
  document.querySelectorAll('.library-count-popup').forEach(el => el.remove());
  // Aborts any running demo so view switches kill it dead.
  clearDemoTimers();
  _demoRunning = false;
}

// One-time visibility listener: if the user backgrounds the tab mid-animation
// we forcibly settle every surface instead of letting setTimeout drift fire
// late when they tab back.
if (typeof document !== 'undefined' && !document.__baklogLibCountVisListener) {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      cancelAllLibraryCountAnimations();
    }
  });
  document.__baklogLibCountVisListener = true;
}

// Demo mode — fires a sequence of fake fetcher landings so the 1UP burst is
// reproducible for screen recordings or live demos without needing real data.
// Each entry mirrors a typical store delta (Steam claim history, GOG, PSN,
// Epic free Thursdays, itch.io bundle). The hero counter actually counts up
// so the demo looks like the real first-run experience.
// Per-store deltas only — gap between landings comes from `stepMs` (so callers
// can speed up / slow down the whole sequence with a single option).
const _demoStoreSequence = [
  { label: 'Steam',   delta: 257  },
  { label: 'GOG',     delta: 673  },
  { label: 'PSN',     delta: 597  },
  { label: 'Epic',    delta: 259  },
  { label: 'Amazon',  delta: 154  },
  { label: 'itch.io', delta: 1044 },
];

/** Demo timer pool so cancelAllLibraryCountAnimations can also abort demos. */
let _demoTimers = [];
function clearDemoTimers() {
  for (const id of _demoTimers) clearTimeout(id);
  _demoTimers = [];
}

let _demoRunning = false;
let _demoSavedHeroBase = null;

/**
 * Fire a sequence of fake fetcher landings against #dashHeroCount so the
 * 1UP animation can be demoed without a real refresh. Mutates the hero
 * text only; never touches state.allGames, never persists.
 *
 * Options:
 *   - stores: optional override of the sequence ([{label, delta}, ...]).
 *   - startFrom: starting count (default: current hero count text or 0).
 *   - stepMs: gap between stores (default: 850ms).
 */
export function runLibraryCountDemo(opts = {}) {
  if (_demoRunning) return;
  if (typeof document === 'undefined') return;
  const hero = document.getElementById('dashHeroCount');
  if (!hero) {
    console.warn('[baklog-demo] dashHeroCount not on page - switch to Dashboard first.');
    return;
  }
  _demoRunning = true;
  clearDemoTimers();
  try {
    const sequence = Array.isArray(opts.stores) ? opts.stores : _demoStoreSequence;
    const stepMs = Number.isFinite(opts.stepMs) ? opts.stepMs : 850;
    const parseHero = () => {
      const n = parseInt((hero.textContent || '0').replace(/[^\d]/g, ''), 10);
      return Number.isFinite(n) ? n : 0;
    };
    _demoSavedHeroBase = parseHero();
    let running = Number.isFinite(opts.startFrom) ? opts.startFrom : 0;
    // Reset the hero to startFrom so the demo looks like a fresh first-run.
    hero.textContent = running.toLocaleString('en-US');

    let elapsed = 0;
    for (let i = 0; i < sequence.length; i++) {
      const step = sequence[i];
      // First step fires immediately; subsequent steps respect stepMs unless
      // the caller pinned a per-step delayBeforeMs override.
      elapsed += i === 0 ? 0 : (Number.isFinite(step.delayBeforeMs) ? step.delayBeforeMs : stepMs);
      const prev = running;
      const next = running + step.delta;
      running = next;
      const t = setTimeout(() => {
        if (!hero.isConnected) return;
        flashCountUp(hero, prev, next, fmtCommas, { popups: true });
      }, elapsed);
      _demoTimers.push(t);
    }
    // After the last burst, restore the real hero text so the demo doesn't
    // leave the dashboard reading 2,984 when the actual library is 1,946.
    const lastStep = sequence[sequence.length - 1];
    const lastRoll = lastStep
      ? heroCountRollMs(lastStep.delta, Math.min(lastStep.delta, POPUP_CAP))
      : 1600;
    const restoreAt = elapsed + lastRoll + 200;
    const restoreId = setTimeout(() => {
      _demoRunning = false;
      if (hero.isConnected) {
        const realCount = _demoSavedHeroBase != null ? _demoSavedHeroBase : parseHero();
        flashCountUp(hero, running, realCount, fmtCommas, { popups: false, durationMs: 600 });
      }
    }, restoreAt);
    _demoTimers.push(restoreId);
  } catch (err) {
    _demoRunning = false;
    console.warn('[baklog-demo] runLibraryCountDemo failed', err);
  }
}

/**
 * Smaller demo — fires N single-game (+1) bursts in sequence, then animates
 * the count back down to its real value. Captures the "one game at a time"
 * feel for tighter screen recordings or quick live demos.
 *
 * Options:
 *   - count: number of +1 bursts (default 5).
 *   - stepMs: gap between bursts (default 520ms — clears each +1 roll).
 *   - startFrom: starting count (default: current hero count).
 */
export function runLibraryCountSmallDemo(opts = {}) {
  if (_demoRunning) return;
  if (typeof document === 'undefined') return;
  const hero = document.getElementById('dashHeroCount');
  if (!hero) {
    console.warn('[baklog-demo] dashHeroCount not on page - switch to Dashboard first.');
    return;
  }
  _demoRunning = true;
  clearDemoTimers();
  try {
    const total = Number.isFinite(opts.count) && opts.count > 0 ? Math.floor(opts.count) : 5;
    const stepMs = Number.isFinite(opts.stepMs) ? opts.stepMs : 520;
    const parseHero = () => {
      const n = parseInt((hero.textContent || '0').replace(/[^\d]/g, ''), 10);
      return Number.isFinite(n) ? n : 0;
    };
    const original = parseHero();
    let running = Number.isFinite(opts.startFrom) ? opts.startFrom : original;
    _demoSavedHeroBase = original;
    hero.textContent = running.toLocaleString('en-US');

    for (let i = 0; i < total; i++) {
      const prev = running;
      const next = running + 1;
      running = next;
      const id = setTimeout(() => {
        if (!hero.isConnected) return;
        flashCountUp(hero, prev, next, fmtCommas, { popups: true });
      }, i * stepMs);
      _demoTimers.push(id);
    }
    const restoreAt = total * stepMs + countUpDurationForDelta(1) + 150;
    const restoreId = setTimeout(() => {
      _demoRunning = false;
      if (!hero.isConnected) return;
      flashCountUp(hero, running, original, fmtCommas, { popups: false, durationMs: 700 });
    }, restoreAt);
    _demoTimers.push(restoreId);
  } catch (err) {
    _demoRunning = false;
    console.warn('[baklog-demo] runLibraryCountSmallDemo failed', err);
  }
}

if (typeof window !== 'undefined') {
  window.baklogDemoLibraryCount = runLibraryCountDemo;
  window.baklogDemoLibraryCountSmall = runLibraryCountSmallDemo;
  window.baklogCancelLibraryCountAnimations = cancelAllLibraryCountAnimations;
}
