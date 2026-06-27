/** @vitest-environment happy-dom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((arr) => arr),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 10),
  cutBucketClass: vi.fn(() => ''),
  isStealDeal: vi.fn(() => false),
  parsePriceLike: vi.fn(() => null),
}));

function artGame(name, art, overrides = {}) {
  return {
    store: 'steam',
    id: overrides.id ?? name,
    name,
    steam_review_percent: overrides.steam_review_percent ?? 90,
    steam_review_count: overrides.steam_review_count ?? 1000,
    library_image: art,
    header_image: art,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    release_date: overrides.release_date ?? '2018-06-01',
    playtime_minutes: overrides.playtime_minutes ?? 0,
    _personal: { status: 'backlog' },
    ...overrides,
  };
}

/** Mix categories so barrel cap and family balance don't shrink the pool. */
function variedArtLibrary(count) {
  return Array.from({ length: count }, (_, i) => {
    const bucket = i % 4;
    if (bucket === 0) {
      return artGame(`Elite ${i}`, `https://cdn.example/hero-${i}.jpg`, {
        id: String(i),
        steam_review_percent: 94,
        hltb_main_hours: 5,
      });
    }
    if (bucket === 1) {
      return artGame(`Weekend ${i}`, `https://cdn.example/hero-${i}.jpg`, {
        id: String(i),
        steam_review_percent: 74,
        hltb_main_hours: 12,
        release_date: '2016-01-01',
      });
    }
    if (bucket === 2) {
      return artGame(`Co-op ${i}`, `https://cdn.example/hero-${i}.jpg`, {
        id: String(i),
        steam_review_percent: 78,
        coop_online: true,
      });
    }
    return artGame(`Solid ${i}`, `https://cdn.example/hero-${i}.jpg`, {
      id: String(i),
      steam_review_percent: 76,
      hltb_main_hours: 14,
      release_date: '2014-03-01',
    });
  });
}

describe('spotlight sponsored slides', () => {
  let pickSpotlightGames;
  let renderSpotlightHtml;
  let SPOTLIGHT_HOUSE_AD_INTERVAL;
  let setSpotlightCurrentKey;
  let setStinkerChanceForTest;
  let setRandomPickChanceForTest;
  let setCatGameChanceForTest;
  let setScoreJitterForTest;
  let resetSpotlightRecentKeysForTest;
  let __setSponsorsForTest;
  let setSpotlightHouseAdsForTest;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;
    localStorage.clear();

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({
      pickSpotlightGames,
      renderSpotlightHtml,
      SPOTLIGHT_HOUSE_AD_INTERVAL,
      setSpotlightCurrentKey,
      setStinkerChanceForTest,
      setRandomPickChanceForTest,
      setCatGameChanceForTest,
      setScoreJitterForTest,
      resetSpotlightRecentKeysForTest,
    } = await import('../js/dashboard-spotlight.js'));
    ({ __setSponsorsForTest, setSpotlightHouseAdsForTest } = await import('../js/sponsored-deals.js'));

    setSpotlightHouseAdsForTest(true);
    setSpotlightCurrentKey(null);
    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(0);
    setScoreJitterForTest(0);
    resetSpotlightRecentKeysForTest();
    state.prefs = { librarySeenSeeded: true };
    state.personal = {};
    state.libraryFirstSeenByKey = {};
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

  afterEach(() => {
    localStorage.clear();
  });

  it('injects sponsored slides into the rotation pool', () => {
    const games = [artGame('Real Game', 'https://cdn.example/hero.jpg')];
    const pool = pickSpotlightGames(games);
    expect(pool.some(g => g._spotlightAd && g.name === 'Emberfall')).toBe(true);
  });

  it('pins the large-logo Pro slide first and guarantees the permanent Pro house slides', () => {
    const pool = pickSpotlightGames(variedArtLibrary(80));
    expect(pool[0]._spotlightArtMode).toBe('logo');
    expect(pool[0]._spotlightAd?.id).toBe('house-spotlight-pro-logo');
    const ids = pool.map(g => g._spotlightAd?.id);
    expect(ids).toContain('house-spotlight-pro-sync');
    expect(ids).toContain('house-spotlight-pro-noads');
    expect(ids).toContain('house-spotlight-pro-alerts');
    if (pool.length > SPOTLIGHT_HOUSE_AD_INTERVAL * 4) {
      expect(ids).toContain('house-spotlight-library');
    }
  });

  it('spaces permanent Pro house slides ~17 slides apart', () => {
    const pool = pickSpotlightGames(variedArtLibrary(80));
    const gameSlides = pool.filter(g => !g._spotlightAd);
    expect(gameSlides.length).toBeGreaterThan(SPOTLIGHT_HOUSE_AD_INTERVAL * 2);
    const houseIdx = pool
      .map((g, i) => (g._spotlightAd?.id?.startsWith('house-spotlight-') ? i : -1))
      .filter(i => i >= 0);
    expect(houseIdx.length).toBeGreaterThan(2);
    for (let i = 1; i < houseIdx.length; i++) {
      expect(houseIdx[i] - houseIdx[i - 1]).toBeGreaterThanOrEqual(SPOTLIGHT_HOUSE_AD_INTERVAL);
    }
  });

  it('renders the large-logo layout (BAKLOG mark + wordmark, slogan, scheme, no cover img)', () => {
    const slide = {
      store: 'sponsored',
      id: 'house-spotlight-pro-logo',
      name: 'BAKLOG Pro',
      _spotlightArtMode: 'logo',
      _spotlightReason: { eyebrow: 'BAKLOG Pro', score: 50, metaParts: ['Leveled up'], slogan: 'One honest backlog across every store.' },
      _spotlightAd: { id: 'house-spotlight-pro-logo', url: 'https://baklog.app/', cta: "See what's planned", artMode: 'logo', scheme: 'ember', slogan: 'One honest backlog across every store.' },
    };
    const html = renderSpotlightHtml(slide);
    expect(html).toContain('has-logo-art');
    expect(html).toContain('dash-spotlight--scheme-ember');
    expect(html).toContain('dash-spotlight-logo-mark');
    expect(html).toContain('dash-spotlight-wordmark');
    expect(html).toContain('dash-spotlight-slogan');
    expect(html).toContain('One honest backlog across every store.');
    expect(html).toContain('dash-spotlight-logo-cta');
    expect(html).not.toContain('class="dash-spotlight-art"');
  });

  it('collapses a tagline that just restates the slogan on logo slides', () => {
    const slide = {
      store: 'sponsored',
      id: 'house-spotlight-pro-sync',
      name: 'Sync every machine',
      _spotlightArtMode: 'logo',
      _spotlightReason: {
        eyebrow: 'BAKLOG Pro',
        score: 50,
        metaParts: ['BAKLOG Pro keeps your library and personal data aligned across machines - no manual exports.'],
        slogan: 'Keep your library and personal data aligned across machines - no manual exports.',
      },
      _spotlightAd: {
        id: 'house-spotlight-pro-sync',
        url: 'https://baklog.app/',
        cta: 'Get Pro - $5/mo',
        artMode: 'logo',
        scheme: 'sapphire',
        slogan: 'Keep your library and personal data aligned across machines - no manual exports.',
      },
    };
    const html = renderSpotlightHtml(slide);
    expect(html).toContain('dash-spotlight-slogan');
    expect(html).not.toContain('dash-spotlight-meta');
    expect(html).not.toContain('BAKLOG Pro keeps your library');
  });

  it('keeps a tagline that adds new detail on logo slides', () => {
    const slide = {
      store: 'sponsored',
      id: 'house-spotlight-pro-logo',
      name: 'BAKLOG Pro',
      _spotlightArtMode: 'logo',
      _spotlightReason: {
        eyebrow: 'BAKLOG Pro',
        score: 50,
        metaParts: ['Leveled up with bulk refresh, cloud sync, and no ads — $5/mo.'],
        slogan: 'One honest backlog across every store.',
      },
      _spotlightAd: {
        id: 'house-spotlight-pro-logo',
        url: 'https://baklog.app/',
        cta: 'Get Pro',
        artMode: 'logo',
        scheme: 'ember',
        slogan: 'One honest backlog across every store.',
      },
    };
    const html = renderSpotlightHtml(slide);
    expect(html).toContain('dash-spotlight-slogan');
    expect(html).toContain('dash-spotlight-meta');
    expect(html).toContain('Leveled up with bulk refresh');
  });

  it('does not emit a scheme class for non-logo sponsored slides', () => {
    const slide = {
      store: 'sponsored',
      id: 'ad-spot',
      name: 'Emberfall',
      header_image: '/assets/ads-sample/hero-emberfall.webp',
      _spotlightArtMode: '',
      _spotlightReason: { eyebrow: 'Sponsored', score: 50, metaParts: [] },
      _spotlightAd: { id: 'ad-spot', url: 'https://example.com/ad', cta: '', artMode: '', scheme: 'ember' },
    };
    const html = renderSpotlightHtml(slide);
    expect(html).not.toContain('dash-spotlight--scheme-');
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
