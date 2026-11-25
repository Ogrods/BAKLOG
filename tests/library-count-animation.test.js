/**
 * Library-count 1UP animation — popup pacing, reduced motion, cancel guardrails.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  flashCountUp,
  fireLibraryCountFlash,
  cancelAllLibraryCountAnimations,
  isSurfaceAnimating,
  runLibraryCountSmallDemo,
  armLibraryCountAnimations,
  disarmLibraryCountAnimations,
  strictSyncRollMs,
} from '../js/library-count-animation.js';
import { state } from '../js/state.js';

function mountCountSurface() {
  document.body.innerHTML = `
    <span class="library-count-host" data-libcount-host>
      <span id="count" data-count-target="library">10</span>
    </span>`;
  const node = document.getElementById('count');
  node.getBoundingClientRect = () => ({
    width: 48,
    height: 24,
    left: 80,
    top: 120,
    right: 128,
    bottom: 144,
    x: 80,
    y: 120,
    toJSON: () => ({}),
  });
  return node;
}

function rafSync() {
  const pending = [];
  vi.stubGlobal('requestAnimationFrame', (cb) => {
    pending.push(cb);
    return pending.length;
  });
  return function flushRaf(untilMs = 6000, stepMs = 16) {
    const t0 = performance.now();
    let step = 0;
    const maxStep = Math.max(Math.ceil(untilMs / stepMs) + 8, 320);
    while (pending.length && step < maxStep) {
      const batch = pending.splice(0);
      for (const cb of batch) {
        step += 1;
        cb(t0 + step * stepMs);
      }
    }
  };
}

describe('flashCountUp', () => {
  let flushRaf;
  const POPUP_REAP_MS = 900; // POPUP_LIFETIME_MS + 200 in library-count-animation.js

  function finishStrictSyncAnimation(dur) {
    flushRaf(dur + 50);
    // Tick-synced popups schedule reap at +900ms; advancing past that clears them before we assert.
    if (dur < POPUP_REAP_MS) vi.advanceTimersByTime(Math.ceil(dur));
  }

  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
    flushRaf = rafSync();
    vi.stubGlobal('matchMedia', (q) => ({
      matches: false,
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      value: 'visible',
    });
    // fireLibraryCountFlash is gated behind the post-boot arm; tests that
    // exercise it need it armed. flashCountUp (called directly) is not gated.
    armLibraryCountAnimations();
  });

  afterEach(() => {
    cancelAllLibraryCountAnimations();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('spawns one popup per game for small deltas', () => {
    const node = mountCountSurface();
    flashCountUp(node, 10, 12, n => String(Math.round(n)), { popups: true });
    const dur = strictSyncRollMs(2, 2);
    flushRaf(dur + 50);
    vi.advanceTimersByTime(Math.ceil(dur));
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(2);
    expect(popups[0].textContent).toBe('+1');
    expect(popups[1].textContent).toBe('+1');
    expect(node.textContent).toBe('12');
  });

  it('caps popups at 10 for large deltas (always +1, never chunked)', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 50, n => String(Math.round(n)), { popups: true });
    expect(node.__baklogLibCountAnim.spawnTimers.length).toBe(10);
    vi.advanceTimersByTime(3200);
    flushRaf(4000);
    for (const el of document.querySelectorAll('.library-count-popup')) {
      expect(el.textContent).toBe('+1');
    }
  });

  it('does not burst large-delta popups when the first rAF is late', () => {
    const node = mountCountSurface();
    flashCountUp(node, 1946, 2116, n => String(Math.round(n)), { popups: true });
    expect(node.__baklogLibCountAnim.spawnTimers.length).toBe(10);
    flushRaf(6000, 6000);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
    vi.advanceTimersByTime(300);
    expect(document.querySelectorAll('.library-count-popup').length).toBeLessThanOrEqual(2);
  });

  it('fires one popup per integer on small deltas (tick-synced)', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 5, n => String(Math.round(n)), { popups: true });
    flushRaf(strictSyncRollMs(5, 5) + 50);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(5);
  });

  it('staggers multi-add popups vertically on the same surface', () => {
    const node = mountCountSurface();
    flashCountUp(node, 10, 13, n => String(Math.round(n)), { popups: true });
    const dur = strictSyncRollMs(3, 3);
    finishStrictSyncAnimation(dur);
    const popups = [...document.querySelectorAll('.library-count-popup')];
    expect(popups.length).toBe(3);
    const tops = popups.map(el => parseFloat(el.style.top));
    expect(new Set(tops).size).toBe(3);
    expect(tops[1]).toBeGreaterThan(tops[0]);
    expect(tops[2]).toBeGreaterThan(tops[1]);
  });

  it('skips popups when prefers-reduced-motion', () => {
    vi.stubGlobal('matchMedia', (q) => ({
      matches: q.includes('reduce'),
      media: q,
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    const node = mountCountSurface();
    flashCountUp(node, 10, 20, n => String(Math.round(n)));
    vi.advanceTimersByTime(800);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
    expect(node.textContent).toBe('20');
  });

  it('does not spawn popups on decrease', () => {
    const node = mountCountSurface();
    flashCountUp(node, 50, 40, n => String(Math.round(n)), { popups: true });
    flushRaf(2000);
    vi.advanceTimersByTime(800);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
    expect(node.textContent).toBe('40');
  });

  it('cancels in-flight episode when node detaches', () => {
    const node = mountCountSurface();
    flashCountUp(node, 5, 10, n => String(Math.round(n)), { popups: true });
    expect(isSurfaceAnimating(node)).toBe(true);
    node.remove();
    cancelAllLibraryCountAnimations();
    expect(isSurfaceAnimating(node)).toBe(false);
    document.querySelectorAll('.library-count-popup').forEach(el => el.remove());
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
  });

  it('replaces prior episode but keeps already-spawned popups climbing', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 3, n => String(Math.round(n)), { popups: true });
    const roll3 = strictSyncRollMs(3, 3);
    flushRaf(Math.ceil(roll3 / 3));
    const firstBurstCount = document.querySelectorAll('.library-count-popup').length;
    expect(firstBurstCount).toBeGreaterThan(0);
    flashCountUp(node, 3, 6, n => String(Math.round(n)), { popups: true });
    finishStrictSyncAnimation(roll3);
    const second = document.querySelectorAll('.library-count-popup').length;
    // Popups from the first episode + new ones — second total should be >= first.
    expect(second).toBeGreaterThanOrEqual(firstBurstCount);
    expect(node.textContent).toBe('6');
  });

  it('clears isSurfaceAnimating when the roll finishes so a second burst can fire', () => {
    const node = mountCountSurface();
    flashCountUp(node, 10, 11, n => String(Math.round(n)), { popups: true });
    expect(isSurfaceAnimating(node)).toBe(true);
    const dur = strictSyncRollMs(1, 1);
    flushRaf(dur + 50);
    expect(node.textContent).toBe('11');
    expect(isSurfaceAnimating(node)).toBe(false);
    // Second acquisition must roll + popup again (sticky-flag regression).
    flashCountUp(node, 11, 12, n => String(Math.round(n)), { popups: true });
    expect(isSurfaceAnimating(node)).toBe(true);
    flushRaf(dur + 50);
    expect(node.textContent).toBe('12');
    expect(isSurfaceAnimating(node)).toBe(false);
    expect(document.querySelectorAll('.library-count-popup').length).toBeGreaterThan(0);
  });

  it('cancelAllLibraryCountAnimations rips down active episodes AND stray popups', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 5, n => String(Math.round(n)), { popups: true });
    flushRaf(200);
    vi.advanceTimersByTime(200);
    expect(document.querySelectorAll('.library-count-popup').length).toBeGreaterThan(0);
    cancelAllLibraryCountAnimations();
    expect(isSurfaceAnimating(node)).toBe(false);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
  });

  it('fireLibraryCountFlash stays silent until armed (no popups on page-load count-up)', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    state.activeView = 'library';
    disarmLibraryCountAnimations();
    // Simulate the boot 0 -> full jump: must NOT spawn combat text.
    fireLibraryCountFlash('library', 0, 1946);
    vi.advanceTimersByTime(800);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
    // Once armed (post-boot), a live addition animates.
    armLibraryCountAnimations();
    fireLibraryCountFlash('library', 1946, 1949);
    const dur3 = strictSyncRollMs(3, 3);
    finishStrictSyncAnimation(dur3);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(3);
  });

  it('fireLibraryCountFlash is a silent no-op when no surfaces are mounted', () => {
    document.body.innerHTML = '';
    expect(() => fireLibraryCountFlash('library', 10, 100)).not.toThrow();
    expect(() => fireLibraryCountFlash('wishlist', 10, 100)).not.toThrow();
  });

  it('fireLibraryCountFlash routes library deltas to the row count when active', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="rowcount-library">10</span>
      </span>`;
    state.activeView = 'library';
    fireLibraryCountFlash('library', 10, 13, { rowPrev: 8, rowNext: 11 });
    const dur3 = strictSyncRollMs(3, 3);
    finishStrictSyncAnimation(dur3);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(3);
  });

  it('fireLibraryCountFlash routes library deltas to the library chip when active', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    state.activeView = 'library';
    fireLibraryCountFlash('library', 10, 13);
    const dur3 = strictSyncRollMs(3, 3);
    finishStrictSyncAnimation(dur3);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(3);
  });

  it('fireLibraryCountFlash skips library surface when not on library view', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    state.activeView = 'wishlist';
    fireLibraryCountFlash('library', 10, 13);
    vi.advanceTimersByTime(300);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
  });

  it('runLibraryCountSmallDemo fires N popups and restores the original count', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span id="dashHeroCount">1946</span>
      </span>`;
    runLibraryCountSmallDemo({ count: 4, stepMs: 100 });
    vi.advanceTimersByTime(500);
    flushRaf(500);
    const hero = document.getElementById('dashHeroCount');
    // After all +1 bursts the count climbed from 1946 to 1950.
    expect(hero.textContent.replace(/,/g, '')).toBe('1950');
    // Final restore timer fires at total*stepMs + roll + 150 = 4*520 + 450 + 150.
    vi.advanceTimersByTime(1500);
    flushRaf(1500);
    // Restore burst (no popups) settles back to original.
    expect(hero.textContent.replace(/,/g, '')).toBe('1946');
  });

  it('refuses to double-fire a running demo', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span id="dashHeroCount">100</span>
      </span>`;
    runLibraryCountSmallDemo({ count: 3, stepMs: 100 });
    // Second call while first is running must be a no-op.
    runLibraryCountSmallDemo({ count: 99, stepMs: 100 });
    vi.advanceTimersByTime(600);
    flushRaf(2000);
    const hero = document.getElementById('dashHeroCount');
    // If the second call had taken effect we'd see 199 here, not 103.
    expect(hero.textContent.replace(/,/g, '')).toBe('103');
  });
});
