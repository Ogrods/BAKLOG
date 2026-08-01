/**
 * Tests for js/sponsored-deals.js — the disclosed sponsored/house deal slot.
 *
 * Scope: eligibility gating (enabled, date window, dismissed, ownership, paid-tier
 * opt-out) and the disclosure markup. These rules are what keep the slot honest:
 * a sponsored card must never show for a game you already own, must always carry
 * a visible disclosure, and must disappear when the user opts out.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  getEligibleSponsoredDeal,
  getEligibleSponsors,
  getAdsForLocation,
  rotateLocationAd,
  getSpotlightHouseAds,
  setSpotlightHouseAdsForTest,
  setHouseProBannersForTest,
  __resetHouseProBannersForTest,
  HOUSE_PRO_BANNERS_ENABLED,
  itemPlacements,
  sponsorCoverUrl,
  sponsorActionAttrs,
  sponsoredDealCardHtml,
  sponsoredDealSlotHtml,
  sponsoredPickCardHtml,
  sponsoredDashPicksCardHtml,
  sponsoredFeatureBannerHtml,
  sponsorToSpotlightGame,
  proPromoBannerHtml,
  proPromoSlotHtml,
  dismissSponsoredDeal,
  placementsForDismissRefresh,
  __resetDismissedSponsorsForTest,
  __resetSpotlightHouseAdsForTest,
  __resetLocationCursorsForTest,
  __setSponsorsForTest,
  __migrateV1ForTest,
  loadSponsoredDeals,
  renderHouseLocationSlot,
  SPONSORS_HOSTED_URL,
  SPONSOR_PLACEMENTS,
  HOUSE_DEAL_ITEM,
  houseDealBannerHtml,
  houseStripeCardHtml,
  houseLibBacklogStatsTitle,
  HOUSE_LIB_BACKLOG_FAKE_STATS,
  houseTableRowHtml,
  sponsoredTableRowHtml,
} from '../js/sponsored-deals.js';
import { buildWishlistStatsHtml } from '../js/dashboard-cards.js';
import * as authGate from '../js/auth-gate.js';
import * as anonMetrics from '../js/anon-metrics.js';
import * as apiClient from '../js/api-client.js';
import { state } from '../js/state.js';

function sponsor(overrides = {}) {
  const { id, ...rest } = {
    id: 'sp1',
    kind: 'sponsor',
    title: 'Cool Game',
    tagline: 'Now 50% off',
    cta: 'Grab it',
    url: 'https://example.com/aff',
    enabled: true,
    ...overrides,
  };
  return { id, ...rest };
}

function v2Doc(adsById, locations) {
  const ads = {};
  for (const [id, fields] of Object.entries(adsById)) {
    const { id: _drop, ...rest } = sponsor({ id, ...fields });
    ads[id] = rest;
  }
  return { version: 2, ads, locations };
}

function wireWishHouse(item = HOUSE_DEAL_ITEM) {
  const { id, ...rest } = item;
  __setSponsorsForTest(v2Doc({ [id]: rest }, { 'wish-house': [id] }));
}

function proPromoItem(overrides = {}) {
  return {
    id: 'house-pro-promo',
    kind: 'house',
    banner: 'pro',
    title: 'Refresh faster. See fewer ads.',
    tagline: 'Queue stale stores, sync across machines, and remove sponsored deal cards. Nothing you use today moves behind paywall.',
    cta: 'Get Pro — $5/mo',
    url: 'https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw',
    placements: 'dash-deal-rail',
    enabled: true,
    ...overrides,
  };
}

beforeEach(() => {
  state.prefs = {};
  state.personal = {};
  state.ownedNormNames = new Set();
  __resetDismissedSponsorsForTest();
  __resetSpotlightHouseAdsForTest();
  __resetLocationCursorsForTest();
  // Existing house-creative suites exercise the on path; flag-off coverage is separate.
  setHouseProBannersForTest(true);
  __setSponsorsForTest({ version: 2, ads: {}, locations: {} });
});

afterEach(() => {
  __resetHouseProBannersForTest();
  state.sponsoredDeals = [];
  state.sponsoredAds = {};
  state.adLocations = {};
  state.personal = {};
});

describe('getEligibleSponsoredDeal', () => {
  it('returns the first eligible ad at the wish-deal-hero location', () => {
    __setSponsorsForTest(v2Doc(
      { low: sponsor({ id: 'low', title: 'Low' }), high: sponsor({ id: 'high', title: 'High' }) },
      { 'wish-deal-hero': ['high', 'low'] },
    ));
    expect(getEligibleSponsoredDeal().id).toBe('high');
  });

  it('skips disabled slots', () => {
    __setSponsorsForTest(v2Doc(
      { sp1: sponsor({ enabled: false }) },
      { 'wish-deal-hero': ['sp1'] },
    ));
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('returns null for the paid (pro) entitlement', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    __setSponsorsForTest(v2Doc({ sp1: sponsor() }, { 'wish-deal-hero': ['sp1'] }));
    expect(getEligibleSponsoredDeal()).toBeNull();
    spy.mockRestore();
  });

  it('skips a slot for a game the user already owns', () => {
    __setSponsorsForTest(v2Doc(
      { sp1: sponsor({ match_title: 'Cool Game' }) },
      { 'wish-deal-hero': ['sp1'] },
    ));
    state.ownedNormNames = new Set(['cool game']);
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('backfills with the next ad when the top slot is for an owned game', () => {
    __setSponsorsForTest(v2Doc(
      { owned: sponsor({ id: 'owned', match_title: 'Cool Game', title: 'Owned' }),
        next: sponsor({ id: 'next', title: 'Next Game' }) },
      { 'wish-deal-hero': ['owned', 'next'] },
    ));
    state.ownedNormNames = new Set(['cool game']);
    expect(getEligibleSponsoredDeal().id).toBe('next');
  });

  it('honors the date window', () => {
    const future = new Date(Date.now() + 86400000).toISOString();
    const past = new Date(Date.now() - 86400000).toISOString();
    __setSponsorsForTest(v2Doc({ sp1: sponsor({ starts: future }) }, { 'wish-deal-hero': ['sp1'] }));
    expect(getEligibleSponsoredDeal()).toBeNull();
    __setSponsorsForTest(v2Doc({ sp1: sponsor({ ends: past }) }, { 'wish-deal-hero': ['sp1'] }));
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('excludes dismissed slots', () => {
    __setSponsorsForTest(v2Doc({ sp1: sponsor({ id: 'sp1' }) }, { 'wish-deal-hero': ['sp1'] }));
    dismissSponsoredDeal('sp1');
    expect(getEligibleSponsoredDeal()).toBeNull();
  });
});

describe('sponsoredDealCardHtml', () => {
  it('always renders a Sponsored disclosure for paid placements', () => {
    const html = sponsoredDealCardHtml(sponsor());
    expect(html).toContain('sponsored-badge');
    expect(html).toContain('>Sponsored<');
    expect(html).toContain('data-action="sponsored-deal"');
    expect(html).toContain('https://example.com/aff');
  });

  it('omits the disclosure badge for house promos', () => {
    const html = sponsoredDealCardHtml(sponsor({ kind: 'house' }));
    expect(html).not.toContain('>House<');
    expect(html).toContain('sponsored-deal-house');
  });

  it('escapes untrusted title text', () => {
    const html = sponsoredDealCardHtml(sponsor({ title: '<img src=x onerror=alert(1)>' }));
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });
});

describe('getEligibleSponsors', () => {
  it('filters by legacy placement via location mapping', () => {
    __setSponsorsForTest(v2Doc(
      { rail: sponsor({ id: 'rail', title: 'Rail' }), spot: sponsor({ id: 'spot', title: 'Spot Ad' }) },
      { 'wish-house': ['rail'], 'dash-spotlight': ['spot'] },
    ));
    expect(getEligibleSponsors('deal-rail').map(x => x.id)).toEqual(['rail']);
    expect(getEligibleSponsors('spotlight').map(x => x.id)).toEqual(['spot']);
  });

  it('defaults missing placements to lib-pick for itemPlacements helper', () => {
    const item = sponsor({ id: 'rail' });
    expect(itemPlacements(item)).toEqual(['lib-pick']);
    expect(getEligibleSponsors('picks')).toEqual([]);
  });
});

describe('getAdsForLocation round-robin', () => {
  it('persists and advances the per-location cursor', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a', title: 'A' }), b: sponsor({ id: 'b', title: 'B' }) },
      { 'lib-pick': ['a', 'b'] },
    ));
    expect(getAdsForLocation('lib-pick')[0].id).toBe('a');
    const cursors = JSON.parse(localStorage.getItem('baklog-ad-cursors') || '{}');
    expect(cursors['lib-pick']).toBe(1);
    expect(getAdsForLocation('lib-pick')[0].id).toBe('a');
  });

  it('resumes from a persisted cursor on a fresh session', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a', title: 'A' }), b: sponsor({ id: 'b', title: 'B' }) },
      { 'lib-pick': ['a', 'b'] },
    ));
    localStorage.setItem('baklog-ad-cursors', JSON.stringify({ 'lib-pick': 1 }));
    expect(getAdsForLocation('lib-pick')[0].id).toBe('b');
  });

  it('rotateLocationAd advances to the next ad within a session', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a', title: 'A' }), b: sponsor({ id: 'b', title: 'B' }) },
      { 'lib-row': ['a', 'b'] },
    ));
    expect(getAdsForLocation('lib-row')[0].id).toBe('a');
    // Without a rotate, the session pick stays pinned to 'a'.
    expect(getAdsForLocation('lib-row')[0].id).toBe('a');
    rotateLocationAd('lib-row');
    expect(getAdsForLocation('lib-row')[0].id).toBe('b');
    rotateLocationAd('lib-row');
    expect(getAdsForLocation('lib-row')[0].id).toBe('a');
  });

  it('returns up to three claim-cards', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a' }), b: sponsor({ id: 'b' }), c: sponsor({ id: 'c' }), d: sponsor({ id: 'd' }) },
      { 'claim-cards': ['a', 'b', 'c', 'd'] },
    ));
    expect(getAdsForLocation('claim-cards', { count: 3 }).map(x => x.id)).toEqual(['a', 'b', 'c']);
  });

  it('returns no ads when isPro()', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a', title: 'A' }) },
      { 'claim-cards': ['a'], 'lib-pick': ['a'] },
    ));
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    expect(getAdsForLocation('claim-cards')).toEqual([]);
    expect(getAdsForLocation('lib-pick')).toEqual([]);
    spy.mockRestore();
  });
});

describe('sponsorCoverUrl', () => {
  it('accepts same-origin paths', () => {
    expect(sponsorCoverUrl('/assets/ads-sample/hero.webp')).toBe('/assets/ads-sample/hero.webp');
  });

  it('rejects unsafe paths', () => {
    expect(sponsorCoverUrl('//evil.example/x.png')).toBe('');
  });
});

describe('house table row', () => {
  const houseRow = (overrides = {}) => ({
    id: 'house-table-every-store',
    kind: 'house',
    title: 'BAKLOG Pro',
    tagline: 'Bulk-refresh every store at once and sync your library across machines. $5/mo.',
    cta: 'Get Pro - $5/mo',
    url: 'https://buy.polar.sh/polar_cl_1BV0qvxl87f2YEGmZo36HvXdmTf4GHthbIjh92P2yNw',
    dismissible: true,
    enabled: true,
    ...overrides,
  });

  it('renders house promo in sponsor shell when tableLayout is sponsor', () => {
    const html = sponsoredTableRowHtml(houseRow(), { tableLayout: 'sponsor' });
    expect(html).toContain('sponsored-deal-house');
    expect(html).not.toContain('sponsored-table-row--house');
    expect(html).toContain('From BAKLOG');
    expect(html).not.toContain('<span class="house-table-kicker">');
    expect(html).toContain('sponsored-table-badge');
    expect(html).not.toContain('sponsored-table-deal-pill');
    expect(html).not.toContain('sponsored-table-status-pill');
  });

  it('renders a branded house row without faux game stats', () => {
    const html = houseTableRowHtml(houseRow());
    expect(html).toContain('sponsored-table-row--house');
    expect(html).toContain('sponsored-deal-house');
    expect(html).toContain('From BAKLOG');
    expect(html).toContain('BAKLOG Pro');
    expect(html).toContain('Support BAKLOG');
    expect(html).not.toContain('Get Pro - $5/mo');
    expect(html).toContain('data-sponsor-house="1"');
    expect(html).not.toContain('>Sponsored<');
    expect(html).not.toContain('sponsored-table-deal-pill');
    expect(html).not.toContain('sponsored-table-status-pill');
  });

  it('never includes dismiss on house rows', () => {
    const html = houseTableRowHtml(houseRow({ dismissible: true }));
    expect(html).not.toContain('sponsored-dismiss');
  });

  it('routes kind house through sponsoredTableRowHtml', () => {
    const html = sponsoredTableRowHtml(houseRow());
    expect(html).toContain('sponsored-table-row--house');
    expect(html).not.toContain('sponsored-table-deal-pill');
  });
});

describe('sponsoredPickCardHtml', () => {
  it('renders cover from same-origin path', () => {
    const html = sponsoredPickCardHtml(sponsor({
      cover: '/assets/ads-sample/cover.webp',
      placements: 'picks',
    }));
    expect(html).toContain('/assets/ads-sample/cover.webp');
    expect(html).toContain('sponsored-pick-card');
  });
});

describe('sponsoredDashPicksCardHtml', () => {
  const dawnbanner = (overrides = {}) => sponsor({
    id: 'ad-dash-picks-dawnbanner',
    kind: 'sponsor',
    title: 'Dawnbanner',
    tagline: 'Lead a band of exiles across a sundered kingdom.',
    cta: 'View the deal',
    cover: '/assets/ads-sample/hero-dawnbanner.webp',
    placements: 'dash-picks',
    network: 'Lantern Forge Studios',
    genres: ['Tactical RPG', 'Strategy'],
    steam_review_percent: 94,
    metacritic_score: 88,
    hltb_hours: 32,
    release_year: 2025,
    discount: 35,
    price_base: 29.99,
    ...overrides,
  });

  it('returns empty string for a missing item', () => {
    expect(sponsoredDashPicksCardHtml(null)).toBe('');
  });

  it('renders the full feature card with the Sponsored disclosure', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner());
    expect(html).toContain('sponsored-feature-card');
    expect(html).toContain('sponsored-badge'); // Sponsored disclosure for paid placement
    expect(html).toContain('>Sponsored<');
    expect(html).toContain('Dawnbanner');
    expect(html).toContain('View the deal');
  });

  it('renders the right-to-left fade art layers from the authored cover', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner());
    expect(html).toContain('sponsored-feature-art-bg');
    expect(html).toContain('sponsored-feature-art');
    expect(html).toContain('sponsored-feature-fade');
    expect(html).toContain('/assets/ads-sample/hero-dawnbanner.webp');
  });

  it('surfaces authored stats and sponsor details in sub-cards', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner());
    expect(html).toContain('sponsored-feature-hero');
    expect(html).toContain('sponsored-feature-panel');
    expect(html).toContain('94%'); // steam review
    expect(html).toContain('>88<'); // metacritic
    expect(html).toContain('32h'); // hltb main story
    expect(html).toContain('2025'); // release year
    expect(html).toContain('-35%'); // discount
    expect(html).toContain('$19.49'); // 29.99 * (1 - 0.35)
    expect(html).toContain('sponsored-feature-was');
    expect(html).toContain('$29.99'); // MSRP strikethrough
    expect(html).toContain('Tactical RPG, Strategy'); // genres
    expect(html).toContain('Lantern Forge Studios'); // sponsor/studio detail
  });

  it('renders a filled CTA pill instead of a text link', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner());
    expect(html).toContain('sponsored-feature-cta');
    expect(html).not.toMatch(/sponsored-deal-cta sponsored-feature-cta/);
  });

  it('includes the dismiss control', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner());
    expect(html).toContain('data-action="sponsored-dismiss"');
    expect(html).toContain('data-sponsor-id="ad-dash-picks-dawnbanner"');
  });

  it('falls back to a no-art card when the cover is missing', () => {
    const html = sponsoredDashPicksCardHtml(dawnbanner({ cover: '' }));
    expect(html).toContain('sponsored-feature-card no-art');
    expect(html).not.toContain('sponsored-feature-art-bg');
  });
});

describe('sponsoredDashPicksCardHtml bundle variant', () => {
  const prideBundle = (overrides = {}) => sponsor({
    id: 'ad-dash-picks-itch-pride',
    kind: 'sponsor',
    title: 'The Power of Pride Bundle 2026',
    tagline: '396 indie games, zines, and more from 284 queer creators.',
    cta: 'Grab the bundle',
    url: 'https://itch.io/b/3682/the-power-of-pride-bundle-2026-60-edition',
    cover: '/assets/ads/itch-pride-bundle.webp',
    network: 'itch.io',
    discount: 94,
    price_base: 1087,
    price_sale: 60,
    bundle_items: 396,
    bundle_creators: 284,
    featured_titles: [
      'Where Winter Crows Go',
      'Syrup 2: Candy Alchemy RPG',
      'A TAVERN FOR TEA',
    ],
    ...overrides,
  });

  it('renders the bundle variant with itch accent class and metrics', () => {
    const html = sponsoredDashPicksCardHtml(prideBundle());
    expect(html).toContain('sponsored-feature-card--bundle');
    expect(html).toContain('Featured bundle');
    expect(html).toContain('The Power of Pride Bundle 2026');
    expect(html).toContain('Grab the bundle');
    expect(html).toContain('396');
    expect(html).toContain('284');
    expect(html).toContain('-94%');
    expect(html).toContain('$60.00');
    expect(html).toContain('$1087.00');
    expect(html).toContain('itch.io');
  });

  it('lists featured bundle titles in compact rows', () => {
    const html = sponsoredDashPicksCardHtml(prideBundle());
    expect(html).toContain('sponsored-bundle-titles');
    expect(html).toContain('Where Winter Crows Go');
    expect(html).toContain('Syrup 2: Candy Alchemy RPG');
    expect(html).toContain('A TAVERN FOR TEA');
  });

  it('tags itch sponsor clicks with the affiliate code', () => {
    const html = sponsoredDashPicksCardHtml(prideBundle());
    expect(html).toContain('ac=eob7ZQcpthHDp');
  });
});

describe('sponsorActionAttrs affiliate tagging', () => {
  it('appends itch ac= to sponsor deal URLs', () => {
    const attrs = sponsorActionAttrs({
      id: 'ad-test',
      kind: 'sponsor',
      url: 'https://itch.io/b/3682/the-power-of-pride-bundle-2026-60-edition',
    });
    expect(attrs).toContain('ac=eob7ZQcpthHDp');
  });

  it('does not tag house promo URLs', () => {
    const attrs = sponsorActionAttrs({
      id: 'house-test',
      kind: 'house',
      url: 'https://itch.io/games',
    });
    expect(attrs).not.toContain('ac=');
  });
});

describe('sponsoredFeatureBannerHtml', () => {
  const emberfall = (overrides = {}) => sponsor({
    id: 'ad-feature-banner-emberfall',
    kind: 'sponsor',
    title: 'Emberfall',
    tagline: 'Forge your legend in a dying world.',
    cta: 'View the deal',
    cover: '/assets/ads-sample/hero-emberfall.webp',
    placements: 'dash-feature-banner',
    network: 'Cinderpeak Games',
    genres: ['Action RPG', 'Open World'],
    steam_review_percent: 96,
    metacritic_score: 91,
    hltb_hours: 45,
    release_year: 2025,
    discount: 40,
    price_base: 39.99,
    ...overrides,
  });

  it('returns empty string for a missing item', () => {
    expect(sponsoredFeatureBannerHtml(null)).toBe('');
  });

  it('reuses the feature-card aesthetic with the banner modifier', () => {
    const html = sponsoredFeatureBannerHtml(emberfall());
    expect(html).toContain('sponsored-feature-card');
    expect(html).toContain('sponsored-feature-card--banner');
    expect(html).toContain('sponsored-feature-art');
    expect(html).toContain('sponsored-feature-fade');
    expect(html).toContain('/assets/ads-sample/hero-emberfall.webp');
  });

  it('carries the Sponsored disclosure, stats, and CTA', () => {
    const html = sponsoredFeatureBannerHtml(emberfall());
    expect(html).toContain('>Sponsored<');
    expect(html).toContain('Emberfall');
    expect(html).toContain('96%');
    expect(html).toContain('>91<');
    expect(html).toContain('45h');
    expect(html).toContain('-40%');
    expect(html).toContain('Cinderpeak Games');
    expect(html).toContain('sponsored-feature-cta');
    expect(html).toContain('View the deal');
  });
});

describe('sponsorToSpotlightGame', () => {
  it('maps feed item to spotlight slide with ad metadata', () => {
    const slide = sponsorToSpotlightGame(sponsor({
      id: 'ad1',
      title: 'Emberfall',
      cover: '/assets/ads-sample/hero.webp',
      placements: 'spotlight',
    }));
    expect(slide.name).toBe('Emberfall');
    expect(slide.header_image).toBe('/assets/ads-sample/hero.webp');
    expect(slide._spotlightAd.id).toBe('ad1');
    expect(slide._spotlightReason.eyebrow).toBe('Sponsored');
    expect(slide._spotlightArtMode).toBe('');
  });

  it('carries art_mode logo + cta and a BAKLOG Pro eyebrow for house slides', () => {
    const slide = sponsorToSpotlightGame({
      id: 'house-spotlight-pro-logo',
      kind: 'house',
      title: 'BAKLOG Pro',
      tagline: 'Leveled up',
      cta: "See what's planned",
      url: 'https://baklog.app/',
      art_mode: 'logo',
    });
    expect(slide._spotlightArtMode).toBe('logo');
    expect(slide._spotlightAd.artMode).toBe('logo');
    expect(slide._spotlightAd.cta).toBe("See what's planned");
    expect(slide._spotlightReason.eyebrow).toBe('BAKLOG Pro');
  });

  it('propagates a known premium scheme + slogan and drops unknown schemes', () => {
    const slide = sponsorToSpotlightGame({
      id: 'house-spotlight-pro-logo',
      kind: 'house',
      title: 'BAKLOG Pro',
      slogan: 'One honest backlog across every store.',
      cta: "See what's planned",
      url: 'https://baklog.app/',
      art_mode: 'logo',
      scheme: 'ember',
    });
    expect(slide._spotlightAd.scheme).toBe('ember');
    expect(slide._spotlightAd.slogan).toBe('One honest backlog across every store.');
    expect(slide._spotlightReason.slogan).toBe('One honest backlog across every store.');

    const unknown = sponsorToSpotlightGame({
      id: 'x',
      kind: 'house',
      title: 'X',
      art_mode: 'logo',
      scheme: 'rainbow',
    });
    expect(unknown._spotlightAd.scheme).toBe('');
  });
});

describe('HOUSE_PRO_BANNERS_ENABLED', () => {
  beforeEach(() => {
    setHouseProBannersForTest(false);
  });

  it('defaults to false for stranger beta', () => {
    expect(HOUSE_PRO_BANNERS_ENABLED).toBe(false);
  });

  it('filters house creatives from locations but keeps paid placements', () => {
    __setSponsorsForTest(v2Doc(
      {
        house: { id: 'house', kind: 'house', title: 'Pro stripe' },
        paid: sponsor({ id: 'paid', kind: 'sponsor', title: 'Paid Deal' }),
      },
      { 'dash-house': ['house'], 'wish-deal-hero': ['paid'], 'lib-pick': ['paid'] },
    ));
    expect(getAdsForLocation('dash-house')).toEqual([]);
    expect(getAdsForLocation('wish-deal-hero').map((x) => x.id)).toEqual(['paid']);
    expect(getAdsForLocation('lib-pick').map((x) => x.id)).toEqual(['paid']);
  });

  it('returns no spotlight house slides', () => {
    setSpotlightHouseAdsForTest(true);
    expect(getSpotlightHouseAds()).toEqual([]);
  });

  it('returns empty markup for dash/wish house slots', () => {
    wireWishHouse();
    expect(sponsoredDealSlotHtml()).toBe('');
    expect(proPromoSlotHtml()).toBe('');
  });

  it('hides renderHouseLocationSlot DOM when the funnel flag is off', () => {
    document.body.innerHTML = '<div id="dashHouse">stale</div><div id="libHouse">stale</div>';
    __setSponsorsForTest(v2Doc(
      { pro: { kind: 'house', title: 'Pro slot', tagline: 'Upsell', cta: 'Go', url: 'https://baklog.app/' } },
      { 'dash-house': ['pro'], 'lib-house': ['pro'] },
    ));
    renderHouseLocationSlot('dash-house', 'dashHouse');
    renderHouseLocationSlot('lib-house', 'libHouse', { variant: 'lib' });
    const dash = document.getElementById('dashHouse');
    const lib = document.getElementById('libHouse');
    expect(dash.classList.contains('hidden')).toBe(true);
    expect(dash.innerHTML).toBe('');
    expect(lib.classList.contains('hidden')).toBe(true);
    expect(lib.innerHTML).toBe('');
  });

  it('restores house creatives when setHouseProBannersForTest(true)', () => {
    setHouseProBannersForTest(true);
    setSpotlightHouseAdsForTest(true);
    wireWishHouse();
    expect(sponsoredDealSlotHtml()).toContain('sponsored-deal-house');
    expect(getSpotlightHouseAds().length).toBeGreaterThan(0);
  });
});

describe('getSpotlightHouseAds', () => {
  beforeEach(() => {
    setSpotlightHouseAdsForTest(true);
  });

  it('returns the permanent spotlight slides with the large-logo slide first', () => {
    const ads = getSpotlightHouseAds();
    expect(ads.map(a => a.id)).toEqual([
      'house-spotlight-pro-logo',
      'house-spotlight-pro-sync',
      'house-spotlight-pro-noads',
      'house-spotlight-pro-alerts',
      'house-spotlight-library',
    ]);
    expect(ads[0].art_mode).toBe('logo');
  });

  it('falls back to defaults even when the feed omits them', () => {
    __setSponsorsForTest(v2Doc({ x: sponsor({ id: 'x', title: 'X' }) }, { 'lib-pick': ['x'] }));
    expect(getSpotlightHouseAds().map(a => a.id)).toEqual([
      'house-spotlight-pro-logo',
      'house-spotlight-pro-sync',
      'house-spotlight-pro-noads',
      'house-spotlight-pro-alerts',
      'house-spotlight-library',
    ]);
  });

  it('returns nothing for Pro subscribers', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    expect(getSpotlightHouseAds()).toEqual([]);
    spy.mockRestore();
  });
});

describe('v1 migration', () => {
  it('maps deal-rail to wish-deal-hero and seeds house slots', () => {
    const out = __migrateV1ForTest({
      items: [
        { id: 'rail-ad', title: 'Rail Ad', placements: 'deal-rail', kind: 'sponsor' },
        { id: 'dash-rail', title: 'Dash Rail', placements: 'dash-deal-rail', kind: 'house' },
      ],
    });
    expect(out.locations['wish-deal-hero']).toContain('rail-ad');
    expect(out.locations['dash-house']).toContain('dash-rail');
    expect(out.locations['wish-house']).toContain('house-support-baklog');
  });

  it('defaults empty placements to deal-rail → wish-deal-hero', () => {
    const out = __migrateV1ForTest({ items: [{ id: 'orphan', title: 'Orphan' }] });
    expect(out.locations['wish-deal-hero']).toContain('orphan');
  });
});

describe('native v2 load', () => {
  it('hydrates state.adLocations from a v2 doc', () => {
    __setSponsorsForTest(v2Doc(
      { x: sponsor({ id: 'x', title: 'X' }) },
      { 'lib-pick': ['x'], 'wish-deal-hero': ['x'] },
    ));
    expect(state.adLocations['lib-pick']).toEqual(['x']);
    expect(state.adLocations['wish-deal-hero']).toEqual(['x']);
    expect(state.sponsoredAds.x.title).toBe('X');
  });
});

describe('renderHouseLocationSlot', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="dashHouse"></div><div id="wishHouse"></div>';
  });

  it('uses Pro upsell markup for house kind at dash-house', () => {
    __setSponsorsForTest(v2Doc(
      { pro: { kind: 'house', title: 'Pro slot', tagline: 'Upsell', cta: 'Go', url: 'https://baklog.app/' } },
      { 'dash-house': ['pro'] },
    ));
    renderHouseLocationSlot('dash-house', 'dashHouse');
    expect(document.getElementById('dashHouse').innerHTML).toContain('sponsored-deal-pro');
  });

  it('uses sponsored deal card for sponsor kind at dash-house', () => {
    __setSponsorsForTest(v2Doc(
      { sp: sponsor({ id: 'sp', title: 'Sponsor Dash', kind: 'sponsor' }) },
      { 'dash-house': ['sp'] },
    ));
    renderHouseLocationSlot('dash-house', 'dashHouse');
    const html = document.getElementById('dashHouse').innerHTML;
    expect(html).toContain('Sponsor Dash');
    expect(html).not.toContain('sponsored-deal-pro');
    expect(html).toContain('sponsored-badge');
  });

  it('applies green accent on wish-house', () => {
    wireWishHouse();
    renderHouseLocationSlot('wish-house', 'wishHouse');
    expect(document.getElementById('wishHouse').innerHTML).toContain('sponsored-deal-banner--green');
  });
});

describe('house promo dismiss', () => {
  it('uses placeholder stats when the library is empty', () => {
    state.allGames = [];
    state.playedTitleNorms = new Set();
    expect(houseLibBacklogStatsTitle()).toBe(
      `You own ${HOUSE_LIB_BACKLOG_FAKE_STATS.owned} games. You've played ${HOUSE_LIB_BACKLOG_FAKE_STATS.played}.`,
    );
    const stripe = houseStripeCardHtml({
      id: 'house-lib-backlog',
      kind: 'house',
      title: 'You own 600 games. You\'ve played 40.',
      tagline: 'One honest backlog across every store.',
      cta: 'Support BAKLOG',
      url: 'https://baklog.app/',
    });
    expect(stripe).toContain(`You've played ${HOUSE_LIB_BACKLOG_FAKE_STATS.played}`);
  });

  it('uses real library stats when games are loaded', () => {
    state.allGames = [
      { name: 'Alpha', store: 'steam', id: '1', playtime_minutes: 60 },
      { name: 'Beta', store: 'steam', id: '2', playtime_minutes: 0 },
      { name: 'Gamma', store: 'gog', id: '3', playtime_minutes: 0 },
    ];
    state.playedTitleNorms = new Set();
    expect(houseLibBacklogStatsTitle()).toBe("You own 3 games. You've played 1.");
    const stripe = houseStripeCardHtml({
      id: 'house-lib-backlog',
      kind: 'house',
      title: 'ignored',
      tagline: 'tag',
      cta: 'Go',
      url: 'https://baklog.app/',
    });
    expect(stripe).toContain("You've played 1");
    expect(stripe).not.toContain('600');
  });

  it('never renders dismiss on house banner or stripe', () => {
    const banner = houseDealBannerHtml(HOUSE_DEAL_ITEM, { accent: 'green' });
    expect(banner).toContain('sponsored-deal-banner--green');
    const stripe = houseStripeCardHtml({
      id: 'house-lib-backlog',
      kind: 'house',
      title: 'You own 600 games. You\'ve played 40.',
      tagline: 'One honest backlog across every store.',
      cta: 'Start free',
      url: 'https://baklog.app/',
      dismissible: true,
    });
    expect(banner).not.toContain('sponsored-dismiss');
    expect(stripe).not.toContain('sponsored-dismiss');
  });

  it('omits dismiss on permanent house promos (no dismissible flag)', () => {
    const banner = houseDealBannerHtml({
      id: 'house-permanent',
      kind: 'house',
      title: 'Permanent promo',
      tagline: 'No close affordance.',
      cta: 'Learn more',
      url: 'https://baklog.app/',
    });
    const stripe = houseStripeCardHtml({
      id: 'house-permanent',
      kind: 'house',
      title: 'Permanent promo',
      cta: 'Learn more',
      url: 'https://baklog.app/',
    });
    expect(banner).not.toContain('sponsored-dismiss');
    expect(stripe).not.toContain('sponsored-dismiss');
  });
});

describe('sponsoredDealSlotHtml', () => {
  it('renders the BAKLOG Pro house banner from wish-house', () => {
    wireWishHouse();
    const html = sponsoredDealSlotHtml();
    expect(html).toContain('sponsored-deal-house');
    expect(html).toContain('Upgrade to BAKLOG Pro');
    expect(html).toContain('data-sponsor-house="1"');
    expect(html).not.toContain('sponsored-dismiss');
  });

  it('returns empty string when dismissed', () => {
    wireWishHouse();
    dismissSponsoredDeal(HOUSE_DEAL_ITEM.id);
    expect(sponsoredDealSlotHtml()).toBe('');
  });

  it('returns empty string for Pro subscribers', () => {
    wireWishHouse();
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    expect(sponsoredDealSlotHtml()).toBe('');
    spy.mockRestore();
  });
});

describe('proPromoBannerHtml', () => {
  it('renders the Pro upsell banner for free users', () => {
    const html = proPromoBannerHtml(proPromoItem());
    expect(html).toContain('sponsored-deal-pro');
    expect(html).toContain('BAKLOG Pro');
    expect(html).toContain('Queued bulk refresh');
    expect(html).toContain('Support BAKLOG');
    expect(html).not.toContain('$5/mo');
    expect(html).toContain('buy.polar.sh/polar_cl_');
    expect(html).not.toContain('sponsored-dismiss');
  });

  it('returns empty string when no feed item is provided', () => {
    expect(proPromoBannerHtml(null)).toBe('');
    expect(proPromoBannerHtml(undefined)).toBe('');
  });

  it('returns empty string for Pro subscribers', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    expect(proPromoBannerHtml(proPromoItem())).toBe('');
    spy.mockRestore();
  });
});

describe('proPromoSlotHtml', () => {
  it('renders the hard-coded Pro upsell for free users', () => {
    const html = proPromoSlotHtml();
    expect(html).toContain('sponsored-deal-pro');
    expect(html).toContain('house-pro-promo');
    expect(html).toContain('data-sponsor-house="1"');
  });

  it('returns empty string for Pro subscribers', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    expect(proPromoSlotHtml()).toBe('');
    spy.mockRestore();
  });
});

describe('buildWishlistStatsHtml ad slot variants', () => {
  it('leaves the dashboard deal-rail 4th slot empty (Pro moves to dash-house)', () => {
    state.wishlistGames = [];
    const html = buildWishlistStatsHtml('dashboard');
    expect(html).not.toContain('sponsored-deal-pro');
    expect(html).not.toContain('Join the waitlist');
  });

  it('uses wish-deal-hero sponsor in the wishlist deal rail when assigned', () => {
    state.wishlistGames = [];
    __setSponsorsForTest(v2Doc(
      { hero: sponsor({ id: 'hero', title: 'Hero Deal', kind: 'sponsor' }) },
      { 'wish-deal-hero': ['hero'] },
    ));
    const html = buildWishlistStatsHtml('wishlist');
    expect(html).toContain('Hero Deal');
    expect(html).not.toContain('sponsored-deal-pro');
  });
});

describe('placementsForDismissRefresh', () => {
  it('returns only the dismissed item locations', () => {
    __setSponsorsForTest(v2Doc(
      { 'picks-ad': sponsor({ id: 'picks-ad' }), 'rail-ad': sponsor({ id: 'rail-ad', title: 'Rail' }) },
      { 'lib-pick': ['picks-ad'], 'wish-house': ['rail-ad'] },
    ));
    expect(placementsForDismissRefresh('picks-ad')).toEqual(['lib-pick']);
    expect(placementsForDismissRefresh('rail-ad')).toEqual(['wish-house']);
  });

  it('returns all locations when sponsor id is unknown', () => {
    __setSponsorsForTest(v2Doc({ known: sponsor({ id: 'known' }) }, { 'lib-pick': ['known'] }));
    expect(placementsForDismissRefresh('missing')).toEqual([...SPONSOR_PLACEMENTS]);
  });

  it('maps house banner id to wish-house when assigned', () => {
    wireWishHouse();
    expect(placementsForDismissRefresh(HOUSE_DEAL_ITEM.id)).toEqual(['wish-house']);
  });
});

describe('house banner telemetry', () => {
  it('does not record impressions for hard-coded house banners', () => {
    const spy = vi.spyOn(anonMetrics, 'noteSponsoredImpression');
    sponsoredDealSlotHtml();
    proPromoSlotHtml();
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });
});

describe('SPONSOR_PLACEMENTS', () => {
  it('includes dash-house for the dashboard Pro upsell slot', () => {
    expect(SPONSOR_PLACEMENTS).toContain('dash-house');
  });
});

describe('loadSponsoredDeals', () => {
  const localItem = { id: 'local-ad', title: 'Local Ad' };
  const remoteItem = { id: 'remote-ad', title: 'Remote Ad' };
  const bundledItem = { id: 'bundled-ad', title: 'Bundled Ad' };

  afterEach(() => {
    vi.restoreAllMocks();
    delete window.__BAKLOG_SPONSORS_ENDPOINT;
  });

  it('uses profile sponsors.json when it has items (skips remote)', async () => {
    vi.spyOn(apiClient, 'dataFetch').mockImplementation(async (url) => {
      if (String(url).startsWith('sponsors.json')) {
        return { ok: true, json: async () => ({ items: [localItem] }) };
      }
      return { ok: false, json: async () => ({ items: [] }) };
    });
    const fetchSpy = vi.spyOn(globalThis, 'fetch');

    await loadSponsoredDeals();

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(expect.arrayContaining(['local-ad']));
    expect(state.sponsoredDeals).toHaveLength(10);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('uses hosted feed when local is empty', async () => {
    vi.spyOn(apiClient, 'dataFetch').mockImplementation(async (url) => {
      if (String(url).startsWith('sponsors.json')) {
        return { ok: true, json: async () => ({ items: [] }) };
      }
      return { ok: false, json: async () => ({ items: [] }) };
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [remoteItem] }),
    });

    await loadSponsoredDeals();

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(expect.arrayContaining(['remote-ad']));
    expect(state.sponsoredDeals).toHaveLength(10);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      SPONSORS_HOSTED_URL,
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('falls back to bundled curated/sponsors.json when remote fails', async () => {
    vi.spyOn(apiClient, 'dataFetch').mockImplementation(async (url) => {
      if (String(url).startsWith('sponsors.json')) {
        return { ok: true, json: async () => ({ items: [] }) };
      }
      if (String(url).startsWith('curated/sponsors.json')) {
        return { ok: true, json: async () => ({ items: [bundledItem] }) };
      }
      return { ok: false, json: async () => ({ items: [] }) };
    });
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('offline'));

    await loadSponsoredDeals();

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(expect.arrayContaining(['bundled-ad']));
    expect(state.sponsoredDeals).toHaveLength(10);
  });

  it('respects window.__BAKLOG_SPONSORS_ENDPOINT override', async () => {
    window.__BAKLOG_SPONSORS_ENDPOINT = 'https://test.example/sponsors.json';
    vi.spyOn(apiClient, 'dataFetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    });
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ items: [remoteItem] }),
    });

    await loadSponsoredDeals();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      'https://test.example/sponsors.json',
      expect.any(Object),
    );
  });
});
