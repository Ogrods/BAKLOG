/**
 * Regression: dashboard hero "+N" combat-text must be readable and not clipped
 * by .dash-mega overflow. Body-mounted floats must carry hero font-size without
 * a .dash-mega ancestor (js/library-count-animation.js spawnPopups).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flashCountUp } from '../js/library-count-animation.js';

const APP_CSS = readFileSync(join(import.meta.dirname, '..', 'app.css'), 'utf8');

function extractRuleBlock(css, selector) {
  const re = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`, 'm');
  return css.match(re)?.[1] ?? '';
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
  return document.getElementById('dashHeroCount');
}

describe('library-count hero visibility CSS contract', () => {
  it('does not clip combat-text with overflow:hidden on .dash-mega', () => {
    const block = extractRuleBlock(APP_CSS, '.dash-mega');
    expect(block, '.dash-mega rule').toBeTruthy();
    expect(block).not.toMatch(/overflow:\s*hidden/);
  });

  it('sets hero font-size on floated popups (body mount, no .dash-mega ancestor)', () => {
    expect(APP_CSS).toMatch(
      /\.library-count-popup--floated\s*\{[^}]*font-size:\s*clamp\(/,
    );
  });

  it('keeps in-host hero popup sizing for non-floated surfaces', () => {
    expect(APP_CSS).toMatch(
      /\.dash-mega\s+\.library-count-popup\s*\{[^}]*font-size:\s*clamp\(/,
    );
  });

  it('uses em-scaled hero keyframes on floated popups', () => {
    expect(APP_CSS).toMatch(
      /\.library-count-popup--floated\s*\{[^}]*animation:\s*baklog-libcount-pop-hero/,
    );
    expect(APP_CSS).toMatch(/@keyframes baklog-libcount-pop-hero/);
  });

  it('does not set a resting transform on base popups', () => {
    const block = extractRuleBlock(APP_CSS, '.library-count-popup');
    expect(block).not.toMatch(/^\s*transform:/m);
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
    vi.advanceTimersByTime(100);
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
    vi.advanceTimersByTime(200);
    const popup = document.querySelector('.library-count-popup--floated');
    expect(popup?.isConnected).toBe(true);
    expect(popup?.textContent).toBe('+1');
    expect(parseFloat(getComputedStyle(popup).fontSize)).toBeGreaterThanOrEqual(20);
  });

  it('chip popups stay in-host without --floated', () => {
    document.body.innerHTML = `
      <span class="library-count-host" data-libcount-host>
        <span data-count-target="library">10</span>
      </span>`;
    const chip = document.querySelector('[data-count-target="library"]');
    flashCountUp(chip, 10, 12, (n) => String(Math.round(n)), { popups: true });
    vi.advanceTimersByTime(200);
    const popups = document.querySelectorAll('.library-count-popup');
    expect(popups.length).toBe(2);
    for (const el of popups) {
      expect(el.classList.contains('library-count-popup--floated')).toBe(false);
      expect(el.parentElement?.classList.contains('library-count-host')).toBe(true);
    }
  });
});
