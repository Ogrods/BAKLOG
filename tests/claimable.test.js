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

describe('dismissClaim', () => {
  it('persists dismissal on personal state', () => {
    state.claimableFeed = { items: sampleItems };
    dismissClaim('gog-bar');
    expect(state.personal.__dismissedClaims['gog-bar']).toBeTypeOf('number');
    expect(getVisibleClaims(sampleItems).map(c => c.id)).toEqual(['epic-foo']);
  });
});
