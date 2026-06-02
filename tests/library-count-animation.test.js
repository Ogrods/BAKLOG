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
} from '../js/library-count-animation.js';
import { state } from '../js/state.js';

function mountCountSurface() {
  document.body.innerHTML = `
    <span class="library-count-host" data-libcount-host>
      <span id="count" data-count-target="library">10</span>
    </span>`;
  return document.getElementById('count');
}

function rafSync() {
  vi.stubGlobal('requestAnimationFrame', (cb) => {
    cb(performance.now() + 2000);
    return 1;
  });
}

describe('flashCountUp', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
    vi.useFakeTimers();
    rafSync();
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
  });

  afterEach(() => {
    cancelAllLibraryCountAnimations();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('spawns one popup per game for small deltas', () => {
    const node = mountCountSurface();
    flashCountUp(node, 10, 12, n => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(200);
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(2);
    expect(popups[0].textContent).toBe('+1');
    expect(popups[1].textContent).toBe('+1');
    expect(node.textContent).toBe('12');
  });

  it('caps popups at 10 for large deltas', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 1946, n => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(800);
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(10);
    const sum = [...popups].reduce((s, el) => s + parseInt(el.textContent.slice(1).replace(/,/g, ''), 10), 0);
    expect(sum).toBeGreaterThanOrEqual(1946);
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
    // Let the first 2 popups spawn before firing a second episode.
    vi.advanceTimersByTime(150);
    const firstBurstCount = document.querySelectorAll('.library-count-popup').length;
    expect(firstBurstCount).toBeGreaterThan(0);
    flashCountUp(node, 3, 6, n => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(400);
    const second = document.querySelectorAll('.library-count-popup').length;
    // Popups from the first episode + new ones — second total should be >= first.
    expect(second).toBeGreaterThanOrEqual(firstBurstCount);
    expect(node.textContent).toBe('6');
  });

  it('cancelAllLibraryCountAnimations rips down active episodes AND stray popups', () => {
    const node = mountCountSurface();
    flashCountUp(node, 0, 5, n => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(200);
    expect(document.querySelectorAll('.library-count-popup').length).toBeGreaterThan(0);
    cancelAllLibraryCountAnimations();
    expect(isSurfaceAnimating(node)).toBe(false);
    expect(document.querySelectorAll('.library-count-popup').length).toBe(0);
  });

  it('fireLibraryCountFlash is a silent no-op when no surfaces are mounted', () => {
    document.body.innerHTML = '';
    expect(() => fireLibraryCountFlash('library', 10, 100)).not.toThrow();
    expect(() => fireLibraryCountFlash('wishlist', 10, 100)).not.toThrow();
  });

  it('fireLibraryCountFlash routes library deltas to the library chip when active', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    state.activeView = 'library';
    fireLibraryCountFlash('library', 10, 13);
    vi.advanceTimersByTime(300);
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
    // Spawn loop fires its setTimeouts; let them resolve and the popups appear.
    vi.advanceTimersByTime(500);
    const hero = document.getElementById('dashHeroCount');
    // After all +1 bursts the count climbed from 1946 to 1950.
    expect(hero.textContent.replace(/,/g, '')).toBe('1950');
    // Final restore timer fires at total*stepMs + 900 = 4*100 + 900 = 1300ms.
    vi.advanceTimersByTime(1500);
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
    vi.advanceTimersByTime(500);
    const hero = document.getElementById('dashHeroCount');
    // If the second call had taken effect we'd see 199 here, not 103.
    expect(hero.textContent.replace(/,/g, '')).toBe('103');
  });
});
