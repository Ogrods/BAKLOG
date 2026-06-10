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
  getSpotlightHouseAds,
  setSpotlightHouseAdsForTest,
  itemPlacements,
  sponsorCoverUrl,
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
    title: 'Power-user conveniences',
    tagline: 'Nothing you use today moves behind paywall. The optional tier layers on bulk refresh, sync, and fewer distractions.',
    cta: "$5/mo — see what's planned",
    url: 'https://baklog.app/',
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
  __setSponsorsForTest({ version: 2, ads: {}, locations: {} });
});

afterEach(() => {
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

  it('returns up to three claim-cards', () => {
    __setSponsorsForTest(v2Doc(
      { a: sponsor({ id: 'a' }), b: sponsor({ id: 'b' }), c: sponsor({ id: 'c' }), d: sponsor({ id: 'd' }) },
      { 'claim-cards': ['a', 'b', 'c', 'd'] },
    ));
    expect(getAdsForLocation('claim-cards', { count: 3 }).map(x => x.id)).toEqual(['a', 'b', 'c']);
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
});

describe('getSpotlightHouseAds', () => {
  beforeEach(() => {
    setSpotlightHouseAdsForTest(true);
  });

  it('returns the 3 permanent Pro slides with the large-logo slide first', () => {
    const ads = getSpotlightHouseAds();
    expect(ads.map(a => a.id)).toEqual([
      'house-spotlight-pro-logo',
      'house-spotlight-pro-sync',
      'house-spotlight-pro-noads',
    ]);
    expect(ads[0].art_mode).toBe('logo');
  });

  it('falls back to defaults even when the feed omits them', () => {
    __setSponsorsForTest(v2Doc({ x: sponsor({ id: 'x', title: 'X' }) }, { 'lib-pick': ['x'] }));
    expect(getSpotlightHouseAds().map(a => a.id)).toEqual([
      'house-spotlight-pro-logo',
      'house-spotlight-pro-sync',
      'house-spotlight-pro-noads',
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
  it('renders a dismiss on closeable house banner and stripe (dismissible: true)', () => {
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
    expect(banner).toContain('sponsored-dismiss');
    expect(stripe).toContain('sponsored-dismiss');
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
  it('renders the Back BAKLOG house banner from wish-house', () => {
    wireWishHouse();
    const html = sponsoredDealSlotHtml();
    expect(html).toContain('sponsored-deal-house');
    expect(html).toContain('Back BAKLOG');
    expect(html).toContain('data-sponsor-house="1"');
    expect(html).toContain('sponsored-dismiss');
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
    expect(html).toContain('$5/mo');
    expect(html).toContain('https://baklog.app/');
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
    expect(state.sponsoredDeals).toHaveLength(8);
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
    expect(state.sponsoredDeals).toHaveLength(8);
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
    expect(state.sponsoredDeals).toHaveLength(8);
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
