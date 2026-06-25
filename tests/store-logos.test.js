/**
 * Tests for js/store-logos.js — shared storefront letter badges.
 */

import { describe, expect, it } from 'vitest';
import { storeLogoHtml, storeLogoStripHtml, storeGlyphHtml, storeDisplayName, storeLetter, STORE_BADGE_LETTERS, STORE_RAIL_GLYPH_OFFSET } from '../js/store-logos.js';

describe('storeLetter', () => {
  it('maps known store keys to canonical letters', () => {
    expect(storeLetter('steam')).toBe('S');
    expect(storeLetter('ea')).toBe('EA');
    expect(storeLetter('itad')).toBe('I');
  });
});

// Stores that render an SVG glyph badge (have a brand logo asset). Everything
// else falls back to a letter badge.
const GLYPH_STORES = new Set([
  'steam', 'epic', 'epic_mobile', 'humble', 'psn', 'xbox',
  'nintendo', 'amazon', 'itch', 'battlenet', 'ubisoft', 'ea',
]);

describe('storeLogoHtml', () => {
  it('renders an SVG glyph badge for known stores', () => {
    const html = storeLogoHtml('steam', { size: 'md' });
    expect(html).toContain('store-badge steam');
    expect(html).toContain('store-badge--md');
    expect(html).toContain('store-badge--glyph');
    expect(html).toContain("--store-badge-glyph:url('assets/store-logos/steam.svg')");
    expect(html).not.toContain('>S<');
    expect(html).toContain('aria-label="Steam"');
  });

  it('renders letter fallback for manual/other', () => {
    const html = storeLogoHtml('manual', { size: 'sm' });
    expect(html).toContain('store-badge manual');
    expect(html).not.toContain('store-badge--glyph');
    expect(html).toContain('>M<');
    expect(html).toContain('aria-label=');
  });

  it('renders glyphs for itch, humble, and EA', () => {
    expect(storeLogoHtml('itch', { size: 'sm' })).toContain("--store-badge-glyph:url('assets/store-logos/itch.svg')");
    expect(storeLogoHtml('humble', { size: 'sm' })).toContain("--store-badge-glyph:url('assets/store-logos/humble-h.svg')");
    expect(storeLogoHtml('ea', { size: 'sm' })).toContain("--store-badge-glyph:url('assets/store-logos/ea.svg')");
  });

  it('renders the Epic glyph for epic_mobile with an Epic Mobile tooltip', () => {
    const html = storeLogoHtml('epic_mobile', { size: 'sm' });
    expect(html).toContain('store-badge epic_mobile');
    expect(html).toContain('store-badge--glyph');
    expect(html).toContain("--store-badge-glyph:url('assets/store-logos/epic.svg')");
    expect(html).not.toContain('>Em<');
    expect(html).toContain('title="Epic Mobile"');
    expect(html).toContain('aria-label="Epic Mobile"');
  });

  it('covers every codified store key', () => {
    for (const key of Object.keys(STORE_BADGE_LETTERS)) {
      const html = storeLogoHtml(key, { size: 'sm' });
      expect(html).toContain(`store-badge ${key}`);
      if (GLYPH_STORES.has(key)) {
        expect(html).toContain('store-badge--glyph');
      } else if (key === 'gog') {
        // GOG renders the lowercase "gog" wordmark sitewide, not a "G" letter.
        expect(html).toContain('store-badge--word');
        expect(html).toContain('>gog<');
      } else {
        expect(html).toContain(`>${STORE_BADGE_LETTERS[key]}<`);
      }
    }
  });
});

describe('rail glyph optical offsets', () => {
  it('injects offset CSS vars only for the connections rail badge', () => {
    const rail = storeLogoHtml('steam', { size: 'sm', className: 'conn-rail-badge' });
    expect(rail).toContain('--store-badge-offset-x:1.5px');

    const elsewhere = storeLogoHtml('steam', { size: 'sm' });
    expect(elsewhere).not.toContain('--store-badge-offset-x');
    expect(elsewhere).not.toContain('--store-badge-offset-y');
  });

  it('omits offset vars for zero-offset stores even in the rail', () => {
    // xbox is geometrically centered (offset {}), so no vars should be emitted.
    const rail = storeLogoHtml('xbox', { size: 'sm', className: 'conn-rail-badge' });
    expect(rail).toContain('store-badge--glyph');
    expect(rail).not.toContain('--store-badge-offset-x');
    expect(rail).not.toContain('--store-badge-offset-y');
  });

  it('emits a y-offset var when a store needs vertical nudging', () => {
    const rail = storeLogoHtml('amazon', { size: 'sm', className: 'conn-rail-badge' });
    expect(rail).toContain('--store-badge-offset-x:-0.5px');
    expect(rail).toContain('--store-badge-offset-y:-0.5px');
  });

  it('has a tuning entry for every glyph store (new glyphs must be tuned)', () => {
    for (const key of GLYPH_STORES) {
      expect(STORE_RAIL_GLYPH_OFFSET).toHaveProperty(key);
    }
  });

  it('renders the GOG wordmark badge sitewide at every size', () => {
    for (const size of ['sm', 'md', 'lg']) {
      const html = storeLogoHtml('gog', { size });
      expect(html).toContain('store-badge--word');
      expect(html).toContain('>gog<');
      expect(html).not.toContain('>G<');
    }
    // Still wraps the text in the inner span so the box stays even with siblings.
    expect(storeLogoHtml('gog', { size: 'sm' })).toContain('<span class="store-badge-word">gog</span>');
  });
});

describe('storeGlyphHtml', () => {
  it('renders a full SVG glyph badge for known stores', () => {
    const html = storeGlyphHtml('steam', { size: 'md' });
    expect(html).toContain('store-logo steam store-logo--glyph');
    expect(html).toContain('store-logo--md');
    expect(html).toContain("--store-logo-glyph:url('assets/store-logos/steam.svg')");
    expect(html).toContain('aria-label="Steam"');
    expect(html).not.toContain('>S<');
  });

  it('falls back to a letter badge for stores without a glyph asset', () => {
    const html = storeGlyphHtml('manual', { size: 'sm' });
    expect(html).toContain('store-logo manual store-logo--letter');
    expect(html).toContain('>M<');
  });

  it('renders a purple lowercase "gog" wordmark badge for GOG (hero)', () => {
    const html = storeGlyphHtml('gog', { size: 'md' });
    expect(html).toContain('store-logo gog store-logo--letter store-logo--word');
    expect(html).toContain('>gog<');
    expect(html).toContain('--store-logo-bg:#5100dc');
    expect(html).not.toContain('gog.svg');
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
