/**
 * Regression: dashboard hero "+N" combat-text must be readable and not clipped
 * by .dash-mega overflow. Popups float to document.body via position:fixed.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flashCountUp, strictSyncRollMs } from '../js/library-count-animation.js';
import { countUpDurationForDelta } from '../js/dashboard-shared.js';

const APP_CSS = readFileSync(join(import.meta.dirname, '..', 'app.css'), 'utf8');
/** Keep in sync with js/library-count-animation.js SEQ_POPUP_GAP_MS. */
const SEQ_POPUP_GAP_MS = 300;

function extractRuleBlock(css, selector) {
  const re = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`, 'm');
  return css.match(re)?.[1] ?? '';
}

function stubLayoutRect(el, { w = 120, h = 48, left = 100, top = 200 } = {}) {
  el.getBoundingClientRect = () => ({
    width: w,
    height: h,
    left,
    top,
    right: left + w,
    bottom: top + h,
    x: left,
    y: top,
    toJSON: () => ({}),
  });
}

function mountDashHeroSurface({ w = 220, h = 84, left = 100, top = 200 } = {}) {
  document.body.innerHTML = `
    <div class="dash-mega dash-mega--has-spotlight">
      <div class="dash-mega-hero">
        <div class="dash-hero-eyebrow">Your library</div>
        <span class="library-count-host" data-libcount-host>
          <span class="dash-hero-number" id="dashHeroCount">1,946</span>
        </span>
      </div>
    </div>`;
  const hero = document.getElementById('dashHeroCount');
  stubLayoutRect(hero, { w, h, left, top });
  return hero;
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

describe('library-count hero visibility CSS contract', () => {
  it('escapes .dash-mega overflow via fixed floated popups', () => {
    const mega = extractRuleBlock(APP_CSS, '.dash-mega');
    expect(mega, '.dash-mega rule').toBeTruthy();
    const floated = extractRuleBlock(APP_CSS, '.library-count-popup--floated');
    expect(floated).toMatch(/position:\s*fixed/);
  });

  it('sets hero font-size on floated popups (body mount, no .dash-mega ancestor)', () => {
    expect(APP_CSS).toMatch(
      /\.library-count-popup--floated\s*\{[^}]*font-size:\s*clamp\(/,
    );
  });

  it('sizes chip floated popups smaller than hero floats', () => {
    expect(APP_CSS).toMatch(
      /\.library-count-popup--floated-chip\s*\{[^}]*font-size:\s*clamp\(/,
    );
  });

  it('uses em-scaled hero keyframes on floated popups', () => {
    expect(APP_CSS).toMatch(
      /\.library-count-popup--floated\s*\{[^}]*animation:\s*baklog-libcount-pop-hero/,
    );
    expect(APP_CSS).toMatch(/@keyframes baklog-libcount-pop-hero/);
  });

  it('animates popups via keyframes (not a static end-state transform)', () => {
    expect(APP_CSS).toMatch(/@keyframes baklog-libcount-pop\b/);
    expect(APP_CSS).toMatch(/@keyframes baklog-libcount-pop-hero/);
  });

  it('anchors hero floats from left top (spawn point matches fixed top/left)', () => {
    const heroFloat = extractRuleBlock(
      APP_CSS,
      '.library-count-popup--floated:not(.library-count-popup--floated-chip)',
    );
    const floated = extractRuleBlock(APP_CSS, '.library-count-popup--floated');
    const origin = heroFloat || floated;
    expect(origin).toMatch(/transform-origin:\s*left\s+top/);
  });

  it('does not start hero keyframes below the anchor (no positive 0% Y offset)', () => {
    const heroKeyframes = APP_CSS.match(
      /@keyframes baklog-libcount-pop-hero\s*\{([\s\S]*?)\n\}/,
    )?.[1] ?? '';
    const frame0 = heroKeyframes.match(/0%\s*\{([^}]*)\}/)?.[1] ?? '';
    expect(frame0).not.toMatch(/translate\([^)]*,\s*0\.15em\)/);
    expect(frame0).toMatch(/,\s*0em\)\s*scale/);
  });
});

describe('library-count hero popup mount (happy-dom + app.css)', () => {
  let flushRaf;

  function popupCssFixture() {
    const start = APP_CSS.indexOf('.dash-hero,\n.dash-mega {');
    const popStart = APP_CSS.indexOf('.library-count-host {');
    const popEnd = APP_CSS.indexOf('@media (prefers-reduced-motion: reduce)', popStart);
    return APP_CSS.slice(start, popEnd);
  }

  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: true })));
    document.head.innerHTML = `<style id="app-css-fixture">${popupCssFixture()}
.library-count-popup--floated { font-size: 28px; }</style>`;
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
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 800 });
  });

  afterEach(() => {
    document.head.innerHTML = '';
    document.body.innerHTML = '';
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('floats dash-mega popups on document.body with hero-readable font-size', () => {
    const hero = mountDashHeroSurface();
    flashCountUp(hero, 1946, 1947, (n) => String(Math.round(n)), { popups: true });
    flushRaf(countUpDurationForDelta(1) + 50);
    vi.advanceTimersByTime(countUpDurationForDelta(1));
    const popup = document.querySelector('.library-count-popup');
    expect(popup, 'popup element').toBeTruthy();
    expect(popup.parentElement).toBe(document.body);
    expect(popup.classList.contains('library-count-popup--floated')).toBe(true);
    const px = parseFloat(getComputedStyle(popup).fontSize);
    expect(px, 'floated hero font-size').toBeGreaterThanOrEqual(20);
    expect(px, 'regression: 0.5em body trap').not.toBe(8);
  });

  it('mid-flight floated popup stays mounted with hero font-size', () => {
    const hero = mountDashHeroSurface();
    flashCountUp(hero, 1946, 1947, (n) => String(Math.round(n)), { popups: true });
    flushRaf(countUpDurationForDelta(1) + 50);
    vi.advanceTimersByTime(countUpDurationForDelta(1));
    const popup = document.querySelector('.library-count-popup--floated');
    expect(popup?.isConnected).toBe(true);
    expect(popup?.textContent).toBe('+1');
    expect(parseFloat(getComputedStyle(popup).fontSize)).toBeGreaterThanOrEqual(20);
  });

  it('anchors single +1 at the hero top-right (not bottom-right of digits)', () => {
    const heroTop = 200;
    const heroHeight = 84;
    const hero = mountDashHeroSurface({ top: heroTop, h: heroHeight });
    flashCountUp(hero, 1946, 1947, (n) => String(Math.round(n)), { popups: true });
    flushRaf(countUpDurationForDelta(1) + 50);
    vi.advanceTimersByTime(countUpDurationForDelta(1));
    const popup = document.querySelector('.library-count-popup--floated:not(.library-count-popup--floated-chip)');
    expect(popup, 'hero popup').toBeTruthy();
    const popupTop = parseFloat(popup.style.top);
    const rect = hero.getBoundingClientRect();
    expect(popupTop, 'spawn near hero top edge').toBeLessThanOrEqual(rect.top + 4);
    expect(popupTop, 'not middle/bottom anchored').toBeLessThan(rect.top + rect.height * 0.35);
    const popupLeft = parseFloat(popup.style.left);
    expect(popupLeft, 'spawn to the right of digits').toBeGreaterThanOrEqual(rect.right);
  });

  it('stacks hero +1 popups upward on strict-sync bursts', () => {
    const hero = mountDashHeroSurface();
    flashCountUp(hero, 1946, 1949, (n) => String(Math.round(n)), { popups: true });
    const dur = strictSyncRollMs(3, 3);
    flushRaf(dur + 50);
    if (dur < 900) vi.advanceTimersByTime(Math.ceil(dur));
    const popups = [...document.querySelectorAll(
      '.library-count-popup--floated:not(.library-count-popup--floated-chip)',
    )];
    expect(popups.length).toBe(3);
    const tops = popups.map(el => parseFloat(el.style.top));
    expect(new Set(tops).size).toBe(3);
    expect(tops[1], 'second popup stacks above first').toBeLessThan(tops[0]);
    expect(tops[2], 'third popup stacks above second').toBeLessThan(tops[1]);
  });

  it('chip popups still stack downward (unchanged chip behavior)', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    const chip = document.querySelector('[data-count-target="library"]');
    stubLayoutRect(chip, { w: 40, h: 20, left: 50, top: 60 });
    flashCountUp(chip, 10, 12, (n) => String(Math.round(n)), { popups: true });
    const dur = strictSyncRollMs(2, 2);
    flushRaf(dur + 50);
    vi.advanceTimersByTime(Math.ceil(dur));
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(2);
    for (const el of popups) {
      expect(el.classList.contains('library-count-popup--floated')).toBe(true);
      expect(el.classList.contains('library-count-popup--floated-chip')).toBe(true);
      expect(el.parentElement).toBe(document.body);
      expect(el.textContent).toBe('+1');
    }
    const tops = [...popups].map(el => parseFloat(el.style.top));
    expect(tops[1]).toBeGreaterThan(tops[0]);
  });
});
