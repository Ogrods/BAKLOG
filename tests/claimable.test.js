/**
 * Tests for js/claimable.js — free claimable feed filtering and diff.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  getVisibleClaims,
  diffClaims,
  isClaimOwned,
  stripClaimTitleDecorations,
  dismissClaim,
  claimAttributionHtml,
  claimSourceHtml,
  feedGeneratedAt,
  pickNewerFeed,
} from '../js/claimable.js';

function resetState() {
  state.personal = {};
  state.allGames = [];
  state.ownedNormNames = new Set();
  state.claimableFeed = null;
  state.claimableNow = [];
}

const sampleItems = [
  {
    id: 'epic-foo',
    store: 'epic',
    title: 'Foo Game',
    claim_url: 'https://store.epicgames.com/foo',
  },
  {
    id: 'gog-bar',
    store: 'gog',
    title: 'Bar Game',
    claim_url: 'https://www.gog.com/bar',
    ends_at: '2099-01-01T00:00:00Z',
  },
  {
    id: 'expired',
    store: 'steam',
    title: 'Old Freebie',
    claim_url: 'https://store.steampowered.com/app/1',
    ends_at: '2020-01-01T00:00:00Z',
  },
];

beforeEach(() => {
  resetState();
});

describe('pickNewerFeed', () => {
  it('prefers the feed with the newer generated_at', () => {
    const older = {
      generated_at: '2026-06-07T22:11:50.572130+00:00',
      items: [{ id: 'stale', store: 'epic', title: 'Stale', claim_url: 'https://example.com/a' }],
    };
    const newer = {
      generated_at: '2026-06-08T03:38:12.049819+00:00',
      items: [{ id: 'fresh', store: 'epic', title: 'Fresh', claim_url: 'https://example.com/b' }],
    };
    expect(pickNewerFeed(older, newer)?.items?.[0]?.id).toBe('fresh');
    expect(pickNewerFeed(newer, older)?.items?.[0]?.id).toBe('fresh');
  });

  it('falls back when only one feed has items', () => {
    const empty = { generated_at: '2099-01-01T00:00:00Z', items: [] };
    const only = {
      generated_at: '2026-06-01T00:00:00Z',
      items: [{ id: 'only', store: 'steam', title: 'Only', claim_url: 'https://example.com/c' }],
    };
    expect(pickNewerFeed(empty, only)?.items?.[0]?.id).toBe('only');
    expect(feedGeneratedAt({ fetched_at: '2026-06-02T00:00:00Z' })).toBe(Date.parse('2026-06-02T00:00:00Z'));
  });
});

describe('getVisibleClaims', () => {
  it('filters expired and dismissed items', () => {
    state.personal.__dismissedClaims = { 'epic-foo': Date.now() };
    const visible = getVisibleClaims(sampleItems);
    expect(visible.map(c => c.id)).toEqual(['gog-bar']);
  });

  it('hides owned steam appid matches', () => {
    state.allGames = [{ store: 'steam', appid: 570, id: 570, name: 'Dota 2' }];
    const items = [{
      id: 'steam-dota',
      store: 'steam',
      title: 'Dota 2',
      claim_url: 'https://store.steampowered.com/app/570',
      steam_appid: 570,
    }];
    expect(getVisibleClaims(items)).toHaveLength(0);
  });
});

describe('stripClaimTitleDecorations', () => {
  it('strips GamerPower giveaway suffixes', () => {
    expect(stripClaimTitleDecorations('Rogue Waters (Epic Games) Giveaway')).toBe('Rogue Waters');
  });

  it('strips ITAD store suffixes', () => {
    expect(stripClaimTitleDecorations('Rogue Waters free at EGS on Epic Game Store')).toBe('Rogue Waters');
    expect(stripClaimTitleDecorations('Remothered: Tormented Fathers on Steam')).toBe('Remothered: Tormented Fathers');
  });
});

describe('isClaimOwned', () => {
  it('matches normalized title against ownedNormNames', () => {
    state.ownedNormNames = new Set(['hollow knight']);
    expect(isClaimOwned({ title: 'Hollow Knight' })).toBe(true);
  });

  it('matches decorated giveaway titles against ownedNormNames', () => {
    state.ownedNormNames = new Set(['rogue waters']);
    expect(isClaimOwned({
      id: 'gamerpower-3667',
      store: 'epic',
      title: 'Rogue Waters (Epic Games) Giveaway',
    })).toBe(true);
    expect(isClaimOwned({
      id: 'itad-0c69ed1f1bd8',
      store: 'epic',
      title: 'Rogue Waters free at EGS on Epic Game Store',
    })).toBe(true);
  });

  it('hides decorated owned claims from visible feed', () => {
    state.ownedNormNames = new Set(['rogue waters']);
    const items = [{
      id: 'gamerpower-3667',
      store: 'epic',
      title: 'Rogue Waters (Epic Games) Giveaway',
      claim_url: 'https://www.gamerpower.com/open/rogue-waters-epic-games-giveaway',
      ends_at: '2099-01-01T00:00:00Z',
    }];
    expect(getVisibleClaims(items)).toHaveLength(0);
  });
});

describe('diffClaims', () => {
  it('counts only new visible claim ids', () => {
    const prev = new Set(['gog-bar', 'epic-foo']);
    const { newCount, visible } = diffClaims(prev, sampleItems);
    expect(visible.map(c => c.id)).toEqual(['gog-bar', 'epic-foo']);
    expect(newCount).toBe(0);
  });

  it('detects newly added claims', () => {
    const prev = new Set();
    const { newCount } = diffClaims(prev, sampleItems);
    expect(newCount).toBe(2);
  });
});

describe('claimAttributionHtml', () => {
  it('returns empty string when attribution is missing', () => {
    expect(claimAttributionHtml()).toBe('');
    expect(claimAttributionHtml([])).toBe('');
  });

  it('renders GamerPower credit with link', () => {
    const html = claimAttributionHtml(['GamerPower.com']);
    expect(html).toContain('claim-attribution');
    expect(html).toContain('Giveaway data via');
    expect(html).toContain('href="https://www.gamerpower.com/"');
    expect(html).toContain('GamerPower.com');
  });

  it('joins multiple attribution sources', () => {
    const html = claimAttributionHtml(['GamerPower.com', 'IsThereAnyDeal']);
    expect(html).toContain('GamerPower.com');
    expect(html).toContain('IsThereAnyDeal');
    expect(html).toContain(' · ');
  });
});

describe('claimSourceHtml', () => {
  it('returns empty string for missing or unknown source', () => {
    expect(claimSourceHtml()).toBe('');
    expect(claimSourceHtml('')).toBe('');
    expect(claimSourceHtml('mystery')).toBe('');
  });

  it('renders a plain "via <provider>" badge by default', () => {
    const html = claimSourceHtml('gamerpower');
    expect(html).toContain('claim-source');
    expect(html).toContain('via GamerPower');
    expect(html).not.toContain('<a ');
  });

  it('renders a linked badge when tag is "a"', () => {
    const html = claimSourceHtml('itad', { tag: 'a' });
    expect(html).toContain('IsThereAnyDeal');
    expect(html).toContain('href="https://isthereanydeal.com/"');
  });

  it('is case-insensitive on the source key', () => {
    expect(claimSourceHtml('EPIC')).toContain('via Epic');
  });
});

describe('dismissClaim', () => {
  it('persists dismissal on personal state', () => {
    state.claimableFeed = { items: sampleItems };
    dismissClaim('gog-bar');
    expect(state.personal.__dismissedClaims['gog-bar']).toBeTypeOf('number');
    expect(getVisibleClaims(sampleItems).map(c => c.id)).toEqual(['epic-foo']);
  });
});
