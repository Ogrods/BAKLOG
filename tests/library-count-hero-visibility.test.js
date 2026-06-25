/**
 * Regression: dashboard hero "+N" combat-text must be readable and not clipped
 * by .dash-mega overflow. Popups float to document.body via position:fixed.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flashCountUp } from '../js/library-count-animation.js';
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

function mountDashHeroSurface() {
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
  stubLayoutRect(hero);
  return hero;
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
});

describe('library-count hero popup mount (happy-dom + app.css)', () => {
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
    vi.stubGlobal('requestAnimationFrame', (cb) => {
      cb(performance.now() + 2000);
      return 1;
    });
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
    vi.advanceTimersByTime(countUpDurationForDelta(1));
    const popup = document.querySelector('.library-count-popup--floated');
    expect(popup?.isConnected).toBe(true);
    expect(popup?.textContent).toBe('+1');
    expect(parseFloat(getComputedStyle(popup).fontSize)).toBeGreaterThanOrEqual(20);
  });

  it('chip popups float on body sequentially (+1 each)', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    const chip = document.querySelector('[data-count-target="library"]');
    stubLayoutRect(chip, { w: 40, h: 20, left: 50, top: 60 });
    flashCountUp(chip, 10, 12, (n) => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(countUpDurationForDelta(2));
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(2);
    for (const el of popups) {
      expect(el.classList.contains('library-count-popup--floated')).toBe(true);
      expect(el.classList.contains('library-count-popup--floated-chip')).toBe(true);
      expect(el.parentElement).toBe(document.body);
      expect(el.textContent).toBe('+1');
    }
  });
});
