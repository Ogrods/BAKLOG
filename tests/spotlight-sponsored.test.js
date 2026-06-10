import { beforeEach, describe, expect, it } from 'vitest';
import { pickSpotlightGames, renderSpotlightHtml } from '../js/dashboard-spotlight.js';
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
  state.prefs = {};
  state.personal = {};
  state.ownedNormNames = new Set();
  state.wishlistGames = [];
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.sponsoredDeals = [
    {
      id: 'ad-spot',
      kind: 'sponsor',
      title: 'Emberfall',
      tagline: 'Critically acclaimed',
      url: 'https://example.com/ad',
      cover: '/assets/ads-sample/hero-emberfall.webp',
      placements: 'spotlight',
      enabled: true,
      priority: 1,
    },
  ];
});

describe('spotlight sponsored slides', () => {
  it('injects sponsored slides into the rotation pool', () => {
    const games = [artGame('Real Game', 'https://cdn.example/hero.jpg')];
    const pool = pickSpotlightGames(games);
    const ad = pool.find(g => g._spotlightAd);
    expect(ad).toBeTruthy();
    expect(ad.name).toBe('Emberfall');
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
    expect(html).toContain('sponsored-badge');
    expect(html).toContain('>Sponsored<');
    expect(html).toContain('https://example.com/ad');
  });
});
