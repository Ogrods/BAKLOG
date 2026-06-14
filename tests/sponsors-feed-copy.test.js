/**
 * Guard for the "edited the JS but the ad copy never changed" class of bug.
 *
 * Root cause it protects against: house-promo copy is FEED-DRIVEN. The app
 * resolves sponsors.json in order local profile -> hosted baklog.app -> bundled
 * curated/sponsors.json, so on any online machine the hosted feed (deployed from
 * landing/sponsors.json) shadows js/sponsored-deals.js HOUSE_DEFAULTS. Softening
 * copy in js/ alone does nothing until BOTH JSON feeds are updated and they stay
 * mirrored. See AGENTS.md hard rule 6 + .cursor/rules/frontend.mdc "Banners & ads".
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const curated = JSON.parse(readFileSync('curated/sponsors.json', 'utf8'));
const landing = JSON.parse(readFileSync('landing/sponsors.json', 'utf8'));

const FEEDS = [
  ['curated/sponsors.json', curated],
  ['landing/sponsors.json', landing],
];

function houseAds(feed) {
  return Object.entries(feed.ads || {}).filter(([, ad]) => ad?.kind === 'house');
}

describe('sponsors.json house-promo copy is softened', () => {
  for (const [name, feed] of FEEDS) {
    it(`${name} has no $5/mo pricing in house ad copy`, () => {
      for (const [id, ad] of houseAds(feed)) {
        const copy = `${ad.title || ''} ${ad.slogan || ''} ${ad.tagline || ''} ${ad.cta || ''}`;
        expect(copy, `${id} still mentions $5/mo`).not.toMatch(/\$5\s*\/\s*mo/i);
        expect(copy, `${id} still mentions $50/yr`).not.toMatch(/\$50\s*\/\s*yr/i);
      }
    });

    it(`${name} house ad CTAs read "Support BAKLOG"`, () => {
      for (const [id, ad] of houseAds(feed)) {
        expect(ad.cta, `${id} CTA not softened`).toBe('Support BAKLOG');
      }
    });
  }
});

describe('sponsors.json feeds stay mirrored', () => {
  it('curated and landing have identical ads + locations (generated_at may differ)', () => {
    expect(curated.ads).toEqual(landing.ads);
    expect(curated.locations).toEqual(landing.locations);
    expect(curated.version).toEqual(landing.version);
  });
});
