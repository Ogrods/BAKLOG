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
  sponsorToSpotlightGame,
  dismissSponsoredDeal,
} from '../js/sponsored-deals.js';
import * as authGate from '../js/auth-gate.js';
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

beforeEach(() => {
  state.prefs = { hideSponsoredDeals: false };
  state.personal = {};
  state.ownedNormNames = new Set();
  state.sponsoredDeals = [];
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

  it('returns null when the user opted out (free hide toggle)', () => {
    state.prefs.hideSponsoredDeals = true;
    state.sponsoredDeals = [sponsor()];
    expect(getEligibleSponsoredDeal()).toBeNull();
  });

  it('returns null for the paid (pro) entitlement even without the hide toggle', () => {
    const spy = vi.spyOn(authGate, 'isPro').mockReturnValue(true);
    state.prefs.hideSponsoredDeals = false;
    state.sponsoredDeals = [sponsor()];
    expect(getEligibleSponsoredDeal()).toBeNull();
    spy.mockRestore();
  });

  it('skips a slot for a game the user already owns', () => {
    state.sponsoredDeals = [sponsor({ match_title: 'Cool Game' })];
    state.ownedNormNames = new Set(['cool game']);
    expect(getEligibleSponsoredDeal()).toBeNull();
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

  it('renders a House disclosure for house promos', () => {
    const html = sponsoredDealCardHtml(sponsor({ kind: 'house' }));
    expect(html).toContain('>House<');
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
  it('returns empty string when nothing is eligible', () => {
    state.sponsoredDeals = [];
    expect(sponsoredDealSlotHtml()).toBe('');
  });

  it('returns markup when a slot is eligible', () => {
    state.sponsoredDeals = [sponsor()];
    expect(sponsoredDealSlotHtml()).toContain('sponsored-deal-card');
  });
});
