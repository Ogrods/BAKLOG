/**
 * Tests for js/claimable.js — free claimable feed filtering and diff.
 */

import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  getVisibleClaims,
  getHiddenClaims,
  getOwnedClaims,
  diffClaims,
  saveClaimsSnapshot,
  loadClaimsSnapshotKeys,
  isClaimOwned,
  stripClaimTitleDecorations,
  dismissClaim,
  restoreClaim,
  claimAttributionHtml,
  claimSourceHtml,
  feedGeneratedAt,
  pickNewerFeed,
  sanitizeBlurb,
  handleClaimableClick,
  loadClaimableNow,
  claimCoverFallback,
} from '../js/claimable.js';
import { buildOwnedNormNames } from '../js/deals.js';

function resetState() {
  state.personal = {};
  state.allGames = [];
  state.ownedNormNames = new Set();
  state.ownedSteamAppids = new Set();
  state.crossStoreHiddenKeys = new Set();
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

  it('prefers fresher fetched_at over stale generated_at on profile feeds', () => {
    const profile = {
      generated_at: '2026-06-08T09:07:44.166264+00:00',
      fetched_at: '2026-06-08T17:39:06.835602+00:00',
      items: [{ id: 'profile', store: 'epic', title: 'Profile', claim_url: 'https://example.com/p' }],
    };
    const bundled = {
      generated_at: '2026-06-08T17:31:14.766880+00:00',
      items: [{ id: 'bundled', store: 'epic', title: 'Bundled', claim_url: 'https://example.com/b' }],
    };
    expect(pickNewerFeed(profile, bundled)?.items?.[0]?.id).toBe('profile');
    expect(feedGeneratedAt(profile)).toBe(Date.parse(profile.fetched_at));
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
    buildOwnedNormNames();
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

  it('does not re-fire when the same game returns under a churned feed id', () => {
    // Acknowledge the current feed, then regenerate the same games under new
    // ids (the documented epic-*→gamerpower-* churn after dedup/enrich).
    saveClaimsSnapshot(sampleItems);
    const prevKeys = loadClaimsSnapshotKeys();
    const churned = sampleItems.map(c => ({ ...c, id: `gamerpower-${c.id}` }));
    const { newCount } = diffClaims(prevKeys, churned);
    expect(newCount).toBe(0);
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
    expect(html).toContain('>ITAD<');
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

describe('getOwnedClaims', () => {
  it('excludes expired games even when owned', () => {
    state.allGames = [{ store: 'steam', appid: 1, title: 'Old Freebie' }];
    state.ownedNormNames = new Set(['old freebie']);
    expect(getOwnedClaims(sampleItems).map(c => c.id)).toEqual([]);
  });

  it('includes owned games with a future end date', () => {
    state.allGames = [{ store: 'steam', appid: 99, title: 'Bar Game' }];
    state.ownedNormNames = new Set(['bar game']);
    expect(getOwnedClaims(sampleItems).map(c => c.id)).toEqual(['gog-bar']);
  });
});

describe('getHiddenClaims', () => {
  it('returns only dismissed, non-owned, non-expired claims', () => {
    state.personal.__dismissedClaims = { 'epic-foo': Date.now(), 'gog-bar': Date.now() };
    const hidden = getHiddenClaims(sampleItems);
    expect(hidden.map(c => c.id)).toEqual(['gog-bar', 'epic-foo']);
  });

  it('excludes expired and non-dismissed claims', () => {
    state.personal.__dismissedClaims = { expired: Date.now(), 'epic-foo': Date.now() };
    const hidden = getHiddenClaims(sampleItems);
    expect(hidden.map(c => c.id)).toEqual(['epic-foo']);
  });

  it('excludes owned claims even when dismissed', () => {
    state.personal.__dismissedClaims = { 'epic-foo': Date.now() };
    state.ownedNormNames = new Set(['foo game']);
    expect(getHiddenClaims(sampleItems)).toHaveLength(0);
  });
});

describe('restoreClaim', () => {
  it('removes dismissal and returns claim to visible list', () => {
    state.claimableFeed = { items: sampleItems };
    state.personal.__dismissedClaims = { 'gog-bar': Date.now() };
    restoreClaim('gog-bar');
    expect(state.personal.__dismissedClaims['gog-bar']).toBeUndefined();
    expect(getVisibleClaims(sampleItems).map(c => c.id)).toEqual(['gog-bar', 'epic-foo']);
    expect(getHiddenClaims(sampleItems).map(c => c.id)).toEqual([]);
  });
});

describe('dismissals survive feed id churn', () => {
  const churnFeed = (id, url) => ({ id, store: 'epic', title: 'Foo Game', claim_url: url });

  it('keeps a cleared claim hidden when its feed id changes between reloads', () => {
    state.claimableFeed = { items: [churnFeed('epic-foo', 'https://example.com/foo')] };
    state.claimableNow = state.claimableFeed.items;
    dismissClaim('epic-foo');
    // Same game returns under a different source id (e.g. epic source dropped,
    // gamerpower remains) after a feed regeneration.
    const regenerated = [churnFeed('gamerpower-foo', 'https://example.com/foo2')];
    expect(getVisibleClaims(regenerated).map(c => c.id)).toEqual([]);
    expect(getHiddenClaims(regenerated).map(c => c.id)).toEqual(['gamerpower-foo']);
  });

  it('keeps a cleared claim hidden after cross-store enrichment adds a steam appid', () => {
    // Cleared while the feed had no appid (keyed by title), then the pipeline
    // enriches the same game with a steam_appid (key would flip to appid:…).
    const noAppid = { id: 'gamerpower-foo', store: 'epic', title: 'Foo Game', claim_url: 'https://example.com/foo' };
    state.claimableFeed = { items: [noAppid] };
    state.claimableNow = state.claimableFeed.items;
    dismissClaim('gamerpower-foo');
    const enriched = [{ ...noAppid, id: 'epic-foo', steam_appid: 12345 }];
    expect(getVisibleClaims(enriched).map(c => c.id)).toEqual([]);
    expect(getHiddenClaims(enriched).map(c => c.id)).toEqual(['epic-foo']);
  });

  it('keeps a cleared claim hidden after a steam appid is dropped from the feed', () => {
    const withAppid = { id: 'epic-foo', store: 'epic', title: 'Foo Game', claim_url: 'https://example.com/foo', steam_appid: 12345 };
    state.claimableFeed = { items: [withAppid] };
    state.claimableNow = state.claimableFeed.items;
    dismissClaim('epic-foo');
    const noAppid = [{ id: 'gamerpower-foo', store: 'epic', title: 'Foo Game', claim_url: 'https://example.com/foo' }];
    expect(getVisibleClaims(noAppid).map(c => c.id)).toEqual([]);
    expect(getHiddenClaims(noAppid).map(c => c.id)).toEqual(['gamerpower-foo']);
  });

  it('restore via the new feed id un-hides the game', () => {
    state.claimableFeed = { items: [churnFeed('epic-foo', 'https://example.com/foo')] };
    state.claimableNow = state.claimableFeed.items;
    dismissClaim('epic-foo');
    const regenerated = [churnFeed('gamerpower-foo', 'https://example.com/foo2')];
    state.claimableFeed = { items: regenerated };
    state.claimableNow = regenerated;
    restoreClaim('gamerpower-foo');
    expect(getVisibleClaims(regenerated).map(c => c.id)).toEqual(['gamerpower-foo']);
    expect(getHiddenClaims(regenerated).map(c => c.id)).toEqual([]);
  });
});

describe('dismissed claims survive an empty/failed feed load', () => {
  it('does not wipe dismissals when every claim source fails at boot', async () => {
    const realFetch = globalThis.fetch;
    state.personal.__dismissedClaims = {
      'gamerpower-1604': 1,
      'itad-de23882e1f39': 2,
    };
    // Simulate a boot where the feed is unavailable (transient failure /
    // mid-regeneration). Let debug-log POSTs through to the ingest server.
    globalThis.fetch = (url, init) => {
      if (String(url).includes('/ingest/')) return realFetch(url, init);
      return Promise.reject(new Error('network down'));
    };
    try {
      await loadClaimableNow();
    } finally {
      globalThis.fetch = realFetch;
    }
    expect(Object.keys(state.personal.__dismissedClaims).sort())
      .toEqual(['gamerpower-1604', 'itad-de23882e1f39']);
  });
});

describe('sanitizeBlurb', () => {
  it('strips html tags and decodes entities', () => {
    expect(sanitizeBlurb('<a href="x">Hello</a> &amp; more')).toBe('Hello & more');
  });

  it('removes ITAD giveaway boilerplate', () => {
    expect(sanitizeBlurb('Great game expires on Jan 1 | go to giveaway')).toBe('Great game');
  });

  it('does not leave executable markup', () => {
    const out = sanitizeBlurb('<img src=x onerror=alert(1)>hi there');
    expect(out).not.toContain('<');
    expect(out).toContain('hi there');
  });

  it('strips leftover bare giveaway urls', () => {
    expect(sanitizeBlurb('Claim it now https://itad.example/giveaway/abc done'))
      .toBe('Claim it now done');
  });

  it('returns empty for falsy input', () => {
    expect(sanitizeBlurb('')).toBe('');
    expect(sanitizeBlurb(null)).toBe('');
  });
});

describe('handleClaimableClick URL safety', () => {
  it('opens only safe http(s) claim urls via window.open', () => {
    const opened = [];
    const orig = window.open;
    window.open = (url) => { opened.push(url); return null; };
    try {
      state.claimableFeed = {
        items: [
          { id: 'safe', store: 'epic', title: 'Safe', claim_url: 'https://example.com/safe' },
          { id: 'evil', store: 'epic', title: 'Evil', claim_url: 'javascript:alert(1)' },
        ],
      };
      state.claimableNow = state.claimableFeed.items;
      const mkEvent = (id) => {
        const btn = document.createElement('button');
        btn.setAttribute('data-claim-go', id);
        document.body.appendChild(btn);
        return { target: btn };
      };
      handleClaimableClick(mkEvent('safe'));
      handleClaimableClick(mkEvent('evil'));
    } finally {
      window.open = orig;
    }
    expect(opened).toEqual(['https://example.com/safe']);
  });
});

describe('claimCoverFallback', () => {
  it('returns modern shared Steam header URL when steam_appid is set', () => {
    expect(claimCoverFallback({ steam_appid: 973000 })).toBe(
      'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/973000/header.jpg',
    );
  });

  it('returns empty string when steam_appid is missing', () => {
    expect(claimCoverFallback({ title: 'No appid' })).toBe('');
    expect(claimCoverFallback({ steam_appid: '' })).toBe('');
  });
});
