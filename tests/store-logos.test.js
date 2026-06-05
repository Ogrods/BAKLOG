/**
 * Tests for js/store-logos.js — shared storefront letter badges.
 */

import { describe, expect, it } from 'vitest';
import { storeLogoHtml, storeLogoStripHtml, storeGlyphHtml, storeDisplayName, storeLetter, STORE_BADGE_LETTERS } from '../js/store-logos.js';

describe('storeLetter', () => {
  it('maps known store keys to canonical letters', () => {
    expect(storeLetter('steam')).toBe('S');
    expect(storeLetter('ea')).toBe('EA');
    expect(storeLetter('itad')).toBe('I');
  });
});

describe('storeLogoHtml', () => {
  it('renders letter badge for known stores', () => {
    const html = storeLogoHtml('steam', { size: 'md' });
    expect(html).toContain('store-badge steam');
    expect(html).toContain('store-badge--md');
    expect(html).toContain('>S<');
    expect(html).not.toContain('store-logo--glyph');
    expect(html).toContain('aria-label="Steam"');
  });

  it('renders letter fallback for manual/other', () => {
    const html = storeLogoHtml('manual', { size: 'sm' });
    expect(html).toContain('store-badge manual');
    expect(html).toContain('>M<');
    expect(html).toContain('aria-label=');
  });

  it('uses canonical letters for itch, humble, and EA', () => {
    expect(storeLogoHtml('itch', { size: 'sm' })).toContain('>I<');
    expect(storeLogoHtml('humble', { size: 'sm' })).toContain('>H<');
    expect(storeLogoHtml('ea', { size: 'sm' })).toContain('>EA<');
  });

  it('covers every codified store key', () => {
    for (const key of Object.keys(STORE_BADGE_LETTERS)) {
      const html = storeLogoHtml(key, { size: 'sm' });
      expect(html).toContain(`store-badge ${key}`);
      expect(html).toContain(`>${STORE_BADGE_LETTERS[key]}<`);
    }
  });
});

describe('storeGlyphHtml', () => {
  it('renders a full SVG glyph badge for known stores', () => {
    const html = storeGlyphHtml('steam', { size: 'md' });
    expect(html).toContain('store-logo store-logo--glyph');
    expect(html).toContain('store-logo--md');
    expect(html).toContain("--store-logo-glyph:url('assets/store-logos/steam.svg')");
    expect(html).toContain('aria-label="Steam"');
    expect(html).not.toContain('>S<');
  });

  it('falls back to a letter badge for stores without a glyph asset', () => {
    const html = storeGlyphHtml('manual', { size: 'sm' });
    expect(html).toContain('store-logo store-logo--letter');
    expect(html).toContain('>M<');
  });
});

describe('storeLogoStripHtml', () => {
  it('dedupes and limits stores, rendering glyphs (hero)', () => {
    const html = storeLogoStripHtml(['steam', 'steam', 'epic', 'gog'], { max: 2 });
    expect(html).toContain('store-logo-strip');
    expect(html).toContain('store-logo--glyph');
    expect(html).toContain("url('assets/store-logos/steam.svg')");
    expect(html).toContain("url('assets/store-logos/epic.svg')");
    expect(html).not.toContain("url('assets/store-logos/gog.svg')");
  });
});

describe('storeDisplayName', () => {
  it('maps known store keys', () => {
    expect(storeDisplayName('psn')).toBeTruthy();
    expect(storeDisplayName('amazon')).toBeTruthy();
  });
});
