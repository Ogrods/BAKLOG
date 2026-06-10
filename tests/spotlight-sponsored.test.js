import { beforeEach, describe, expect, it } from 'vitest';
import { pickSpotlightGames, renderSpotlightHtml } from '../js/dashboard-spotlight.js';
import { __setSponsorsForTest, setSpotlightHouseAdsForTest } from '../js/sponsored-deals.js';
import { state } from '../js/state.js';

function artGame(name, art) {
  return {
    store: 'steam',
    id: name,
    name,
    steam_review_percent: 90,
    steam_review_count: 1000,
    library_image: art,
    header_image: art,
    hltb_main_hours: 10,
    release_date: '2020-01-01',
    playtime_minutes: 0,
    _personal: { status: 'backlog' },
  };
}

beforeEach(() => {
  setSpotlightHouseAdsForTest(true);
  state.prefs = {};
  state.personal = {};
  state.ownedNormNames = new Set();
  state.wishlistGames = [];
  state.wishlistCrossStoreHiddenKeys = new Set();
  __setSponsorsForTest({
    version: 2,
    ads: {
      'ad-spot': {
        kind: 'sponsor',
        title: 'Emberfall',
        tagline: 'Critically acclaimed',
        url: 'https://example.com/ad',
        cover: '/assets/ads-sample/hero-emberfall.webp',
        enabled: true,
      },
    },
    locations: { 'dash-spotlight': ['ad-spot'] },
  });
});

describe('spotlight sponsored slides', () => {
  it('injects sponsored slides into the rotation pool', () => {
    const games = [artGame('Real Game', 'https://cdn.example/hero.jpg')];
    const pool = pickSpotlightGames(games);
    // Paid sponsor from the feed is injected.
    expect(pool.some(g => g._spotlightAd && g.name === 'Emberfall')).toBe(true);
  });

  it('pins the large-logo Pro slide first and guarantees the 3 permanent Pro slides', () => {
    const games = [artGame('Real Game', 'https://cdn.example/hero.jpg')];
    const pool = pickSpotlightGames(games);
    expect(pool[0]._spotlightArtMode).toBe('logo');
    expect(pool[0]._spotlightAd?.id).toBe('house-spotlight-pro-logo');
    const ids = pool.map(g => g._spotlightAd?.id);
    expect(ids).toContain('house-spotlight-pro-sync');
    expect(ids).toContain('house-spotlight-pro-noads');
  });

  it('renders the large-logo layout (BAKLOG mark, no cover img)', () => {
    const slide = {
      store: 'sponsored',
      id: 'house-spotlight-pro-logo',
      name: 'BAKLOG Pro',
      _spotlightArtMode: 'logo',
      _spotlightReason: { eyebrow: 'BAKLOG Pro', score: 50, metaParts: ['Leveled up'] },
      _spotlightAd: { id: 'house-spotlight-pro-logo', url: 'https://baklog.app/', cta: "See what's planned", artMode: 'logo' },
    };
    const html = renderSpotlightHtml(slide);
    expect(html).toContain('has-logo-art');
    expect(html).toContain('dash-spotlight-logo-mark');
    expect(html).toContain('dash-spotlight-logo-cta');
    expect(html).not.toContain('class="dash-spotlight-art"');
  });

  it('renders sponsored disclosure and click action on spotlight ad', () => {
    const ad = {
      store: 'sponsored',
      id: 'ad-spot',
      name: 'Emberfall',
      header_image: '/assets/ads-sample/hero-emberfall.webp',
      _spotlightReason: { eyebrow: 'Sponsored', score: 50 },
      _spotlightAd: { id: 'ad-spot', url: 'https://example.com/ad', disclosure: 'Sponsored' },
    };
    const html = renderSpotlightHtml(ad);
    expect(html).toContain('data-action="sponsored-deal"');
    // Disclosure lives in the eyebrow; no separate badge pill on spotlight ads.
    expect(html).toContain('dash-spotlight-eyebrow');
    expect(html).toContain('>Sponsored<');
    expect(html).not.toContain('sponsored-badge');
    expect(html).toContain('https://example.com/ad');
  });

  it('omits the dismiss affordance on spotlight ads (skippable via nav)', () => {
    const ad = {
      store: 'sponsored',
      id: 'ad-spot',
      name: 'Emberfall',
      header_image: '/assets/ads-sample/hero-emberfall.webp',
      _spotlightReason: { eyebrow: 'Sponsored', score: 50 },
      _spotlightAd: { id: 'ad-spot', url: 'https://example.com/ad', disclosure: 'Sponsored' },
    };
    const html = renderSpotlightHtml(ad);
    expect(html).not.toContain('sponsored-dismiss');
    expect(html).not.toContain('data-action="sponsored-dismiss"');
  });
});
