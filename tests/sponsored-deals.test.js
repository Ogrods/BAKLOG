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
  loadSponsoredDeals,
  SPONSORS_HOSTED_URL,
  SPONSOR_PLACEMENTS,
  HOUSE_DEAL_ITEM,
} from '../js/sponsored-deals.js';
import { buildWishlistStatsHtml } from '../js/dashboard-cards.js';
import * as authGate from '../js/auth-gate.js';
import * as anonMetrics from '../js/anon-metrics.js';
import * as apiClient from '../js/api-client.js';
import { state } from '../js/state.js';

function sponsor(overrides = {}) {
  return {
    id: 'sp1',
    kind: 'sponsor',
    title: 'Cool Game',
    tagline: 'Now 50% off',
    cta: 'Grab it',
    url: 'https://example.com/aff',
    enabled: true,
    ...overrides,
  };
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
  state.sponsoredDeals = [];
  __resetDismissedSponsorsForTest();
});

afterEach(() => {
  state.sponsoredDeals = [];
  state.personal = {};
});

describe('getEligibleSponsoredDeal', () => {
  it('returns the highest-priority enabled slot', () => {
    state.sponsoredDeals = [
      sponsor({ id: 'low', priority: 5 }),
      sponsor({ id: 'high', priority: 1 }),
    ];
    expect(getEligibleSponsoredDeal().id).toBe('high');
  });

  it('skips disabled slots', () => {
    state.sponsoredDeals = [sponsor({ enabled: false })];
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('returns null for the paid (pro) entitlement', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    state.sponsoredDeals = [sponsor()];
    expect(getEligibleSponsoredDeal()).toBeNull();
    spy.mockRestore();
  });

  it('skips a slot for a game the user already owns', () => {
    state.sponsoredDeals = [sponsor({ match_title: 'Cool Game' })];
    state.ownedNormNames = new Set(['cool game']);
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('backfills with the next ad when the top slot is for an owned game', () => {
    state.sponsoredDeals = [
      sponsor({ id: 'owned', match_title: 'Cool Game', priority: 1 }),
      sponsor({ id: 'next', title: 'Next Game', priority: 2 }),
    ];
    state.ownedNormNames = new Set(['cool game']);
    expect(getEligibleSponsoredDeal().id).toBe('next');
  });

  it('honors the date window', () => {
    const future = new Date(Date.now() + 86400000).toISOString();
    const past = new Date(Date.now() - 86400000).toISOString();
    state.sponsoredDeals = [sponsor({ starts: future })];
    expect(getEligibleSponsoredDeal()).toBeNull();
    state.sponsoredDeals = [sponsor({ ends: past })];
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('excludes dismissed slots', () => {
    state.sponsoredDeals = [sponsor({ id: 'sp1' })];
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
  it('filters by placement', () => {
    state.sponsoredDeals = [
      sponsor({ id: 'rail', placements: 'deal-rail' }),
      sponsor({ id: 'spot', placements: 'spotlight', title: 'Spot Ad' }),
    ];
    expect(getEligibleSponsors('deal-rail').map(x => x.id)).toEqual(['rail']);
    expect(getEligibleSponsors('spotlight').map(x => x.id)).toEqual(['spot']);
  });

  it('defaults missing placements to deal-rail', () => {
    state.sponsoredDeals = [sponsor({ id: 'rail' })];
    expect(itemPlacements(state.sponsoredDeals[0])).toEqual(['deal-rail']);
    expect(getEligibleSponsors('picks')).toEqual([]);
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
  });
});

describe('sponsoredDealSlotHtml', () => {
  it('renders the hard-coded Back BAKLOG house banner', () => {
    const html = sponsoredDealSlotHtml();
    expect(html).toContain('sponsored-deal-house');
    expect(html).toContain('Back BAKLOG');
    expect(html).toContain('data-sponsor-house="1"');
  });

  it('returns empty string when dismissed', () => {
    dismissSponsoredDeal(HOUSE_DEAL_ITEM.id);
    expect(sponsoredDealSlotHtml()).toBe('');
  });

  it('returns empty string for Pro subscribers', () => {
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
  it('uses the Pro banner on the dashboard slot', () => {
    state.wishlistGames = [];
    const html = buildWishlistStatsHtml('dashboard');
    expect(html).toContain('sponsored-deal-pro');
    expect(html).toContain('Power-user conveniences');
    expect(html).not.toContain('Join the waitlist');
  });

  it('uses the hard-coded house banner on the wishlist slot', () => {
    state.wishlistGames = [];
    const html = buildWishlistStatsHtml('wishlist');
    expect(html).toContain('sponsored-deal-house');
    expect(html).toContain('Join the waitlist');
    expect(html).not.toContain('sponsored-deal-pro');
  });
});

describe('placementsForDismissRefresh', () => {
  it('returns only the dismissed item placements', () => {
    state.sponsoredDeals = [
      sponsor({ id: 'picks-ad', placements: 'picks' }),
      sponsor({ id: 'rail-ad', placements: 'deal-rail', title: 'Rail' }),
    ];
    expect(placementsForDismissRefresh('picks-ad')).toEqual(['picks']);
    expect(placementsForDismissRefresh('rail-ad')).toEqual(['deal-rail']);
  });

  it('returns all placements when sponsor id is unknown', () => {
    state.sponsoredDeals = [sponsor({ id: 'known' })];
    expect(placementsForDismissRefresh('missing')).toEqual([...SPONSOR_PLACEMENTS]);
  });

  it('maps hard-coded house banner id to deal-rail', () => {
    expect(placementsForDismissRefresh(HOUSE_DEAL_ITEM.id)).toEqual(['deal-rail']);
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
  it('includes dash-deal-rail for the dashboard Pro upsell slot', () => {
    expect(SPONSOR_PLACEMENTS).toContain('dash-deal-rail');
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

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(['local-ad']);
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

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(['remote-ad']);
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

    expect(state.sponsoredDeals.map(x => x.id)).toEqual(['bundled-ad']);
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
