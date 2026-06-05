/**
 * Tests for the canonical storefront display hierarchy (bizcard order).
 */

import { describe, expect, it } from 'vitest';
import {
  STORE_DISPLAY_ORDER,
  storeDisplayRank,
  sortStoresByDisplayOrder,
} from '../js/dashboard-shared.js';
import { storeLogoStripHtml } from '../js/store-logos.js';

describe('STORE_DISPLAY_ORDER', () => {
  it('matches the bizcard hierarchy with itch behind humble', () => {
    expect(STORE_DISPLAY_ORDER).toEqual([
      'steam', 'epic', 'gog', 'humble', 'itch', 'psn', 'xbox',
      'nintendo', 'amazon', 'battlenet', 'ubisoft', 'ea',
    ]);
  });
});

describe('storeDisplayRank', () => {
  it('ranks known stores by their position', () => {
    expect(storeDisplayRank('steam')).toBe(0);
    expect(storeDisplayRank('humble')).toBeLessThan(storeDisplayRank('itch'));
    expect(storeDisplayRank('itch')).toBeLessThan(storeDisplayRank('psn'));
  });

  it('sorts unknown keys after the canonical twelve', () => {
    expect(storeDisplayRank('other')).toBe(STORE_DISPLAY_ORDER.length);
    expect(storeDisplayRank('manual')).toBe(STORE_DISPLAY_ORDER.length);
    expect(storeDisplayRank('')).toBe(STORE_DISPLAY_ORDER.length);
  });
});

describe('sortStoresByDisplayOrder', () => {
  it('reorders an unsorted set into hierarchy order', () => {
    expect(sortStoresByDisplayOrder(['amazon', 'steam', 'epic'])).toEqual([
      'steam', 'epic', 'amazon',
    ]);
  });

  it('places itch directly after humble', () => {
    expect(sortStoresByDisplayOrder(['psn', 'itch', 'humble'])).toEqual([
      'humble', 'itch', 'psn',
    ]);
  });

  it('dedupes, lowercases, and drops empties', () => {
    expect(sortStoresByDisplayOrder(['Steam', 'steam', '', null, 'GOG'])).toEqual([
      'steam', 'gog',
    ]);
  });

  it('appends unknown stores after the canonical twelve', () => {
    expect(sortStoresByDisplayOrder(['other', 'steam'])).toEqual(['steam', 'other']);
  });
});

describe('storeLogoStripHtml display order', () => {
  it('renders glyphs in hierarchy order regardless of input order', () => {
    const html = storeLogoStripHtml(['amazon', 'humble', 'itch', 'steam']);
    const steamIdx = html.indexOf('steam.svg');
    const humbleIdx = html.indexOf('humble-h.svg');
    const itchIdx = html.indexOf('itch.svg');
    const amazonIdx = html.indexOf('amazon.svg');
    expect(steamIdx).toBeGreaterThanOrEqual(0);
    expect(steamIdx).toBeLessThan(humbleIdx);
    expect(humbleIdx).toBeLessThan(itchIdx);
    expect(itchIdx).toBeLessThan(amazonIdx);
  });
});
