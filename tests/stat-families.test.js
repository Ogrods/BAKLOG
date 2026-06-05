import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((games) => games),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 0),
  isStealDeal: vi.fn(() => false),
  cutBucketClass: vi.fn(() => 'cut-low'),
  computeWishlistWoba: vi.fn(() => null),
  isCleanupCandidate: vi.fn(() => false),
}));

import { state } from '../js/state.js';
import {
  FAMILY,
  familyForLabel,
  familyForEyebrow,
  familyForInsight,
  spreadByFamily,
  hasNoAdjacentSameFamily,
} from '../js/stat-families.js';
import { buildMarqueeItems } from '../js/dashboard-insights.js';
import {
  pickSpotlightGames,
  setRandomPickChanceForTest,
  setSpotlightCurrentKey,
  setStinkerChanceForTest,
} from '../js/dashboard-spotlight.js';
import { invalidateLibrarySnapshot, getLibrarySnapshot } from '../js/sabermetrics.js';

function game(overrides = {}) {
  return {
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    steam_review_count: overrides.steam_review_count ?? 100,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    playtime_minutes: overrides.playtime_minutes ?? 0,
    genres: overrides.genres ?? ['Action'],
    header_image: overrides.header_image ?? 'https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg',
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  };
}

beforeEach(() => {
  state.prefs = { quickWinMaxHours: 15, librarySeenSeeded: true };
  state.wishlistGames = [];
  state.itchGames = [];
  state.libraryFirstSeenByKey = {};
  window._dataVersion = 0;
  invalidateLibrarySnapshot();
  // pickSpotlightGames rolls stinker / random-pick dice and may rotate the pool
  // for _spotlightCurrentKey — disable those so spacing tests are deterministic.
  setStinkerChanceForTest(0);
  setRandomPickChanceForTest(0);
  setSpotlightCurrentKey(null);
});

describe('family classifiers', () => {
  it('groups trophy completion labels together', () => {
    expect(familyForLabel('one push from 100%')).toBe(FAMILY.COMPLETION);
    expect(familyForLabel('platinum potential')).toBe(FAMILY.COMPLETION);
    expect(familyForLabel('one push from 100%')).toBe(familyForLabel('platinum potential'));
  });

  it('classifies spotlight completion eyebrows', () => {
    expect(familyForEyebrow('Almost mastered')).toBe(FAMILY.COMPLETION);
    expect(familyForEyebrow('Completionist')).toBe(FAMILY.COMPLETION);
  });
});

describe('spreadByFamily', () => {
  it('separates adjacent same-family items in a mixed list', () => {
    const items = [
      { id: 'a', f: FAMILY.COMPLETION },
      { id: 'b', f: FAMILY.COMPLETION },
      { id: 'c', f: FAMILY.TIME },
      { id: 'd', f: FAMILY.RATING },
      { id: 'e', f: FAMILY.COMPLETION },
    ];
    const out = spreadByFamily(items, it => it.f);
    expect(out).toHaveLength(5);
    expect(out.map(x => x.id).sort()).toEqual(['a', 'b', 'c', 'd', 'e'].sort());
    expect(hasNoAdjacentSameFamily(out, it => it.f)).toBe(true);
  });

  it('preserves all items when one family dominates', () => {
    const items = Array.from({ length: 6 }, (_, i) => ({
      id: String(i),
      f: FAMILY.COMPLETION,
    }));
    const out = spreadByFamily(items, it => it.f);
    expect(out).toHaveLength(6);
    // Unavoidable adjacency when only one family exists
    expect(out.map(x => x.id).sort()).toEqual(['0', '1', '2', '3', '4', '5']);
  });

  it('wrap avoids first/last collision when possible', () => {
    const items = [
      { id: '1', f: FAMILY.COMPLETION },
      { id: '2', f: FAMILY.TIME },
      { id: '3', f: FAMILY.RATING },
      { id: '4', f: FAMILY.COMPLETION },
    ];
    const out = spreadByFamily(items, it => it.f, { wrap: true });
    expect(hasNoAdjacentSameFamily(out, it => it.f, { wrap: true })).toBe(true);
  });
});

describe('buildMarqueeItems spacing', () => {
  it('does not place one push from 100% adjacent to platinum potential', () => {
    const games = Array.from({ length: 12 }, (_, i) =>
      game({
        id: String(i + 1),
        name: `Game ${i + 1}`,
        trophy_progress: i < 5 ? 95 : i < 8 ? 88 : 100,
        hltb_main_hours: i < 8 ? 8 : 20,
        status: i % 3 === 0 ? 'playing' : 'backlog',
        playtime_minutes: i % 3 === 0 ? 60 : 0,
      }),
    );
    const snap = getLibrarySnapshot(games);
    const items = buildMarqueeItems(games, snap);
    const labels = items.map(it => it.label);
    const pushIdx = labels.indexOf('one push from 100%');
    const platIdx = labels.indexOf('platinum potential');
    if (pushIdx >= 0 && platIdx >= 0) {
      expect(Math.abs(pushIdx - platIdx)).toBeGreaterThan(1);
    }
    expect(hasNoAdjacentSameFamily(items, it => it.family, { wrap: true })).toBe(true);
  });
});

describe('pickSpotlightGames spacing', () => {
  it('avoids adjacent same-family eyebrows in the pool when diverse', () => {
    const games = [
      game({ id: '1', name: 'A', trophy_progress: 85, status: 'playing', playtime_minutes: 120 }),
      game({ id: '2', name: 'B', steam_review_percent: 92, trophy_progress: 100, status: 'finished' }),
      game({ id: '3', name: 'C', steam_review_percent: 88, hltb_main_hours: 4, status: 'backlog' }),
      game({ id: '4', name: 'D', steam_review_percent: 91, hltb_main_hours: 6, status: 'next' }),
      game({ id: '5', name: 'E', steam_review_percent: 95, hltb_main_hours: 3, status: 'backlog' }),
      game({ id: '6', name: 'F', steam_review_percent: 90, hltb_main_hours: 50, status: 'backlog' }),
    ];
    const pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThanOrEqual(3);
    const families = pool.map(g => familyForEyebrow(g._spotlightReason?.eyebrow));
    const uniqueFamilies = new Set(families);
    // Diverse eyebrows → spreadByFamily should separate same-family neighbors.
    expect(uniqueFamilies.size).toBeGreaterThanOrEqual(2);
    expect(hasNoAdjacentSameFamily(pool, g => familyForEyebrow(g._spotlightReason?.eyebrow))).toBe(true);
  });
});
