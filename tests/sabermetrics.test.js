import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
}));

import { state } from '../js/state.js';
import {
  adultGameCount,
  buildLibrarySnapshot,
  getLibrarySnapshot,
  invalidateLibrarySnapshot,
  agingCurveBuckets,
  completionAverage,
  backlogOps,
  backlogValuePlus,
  isBarrel,
  isLeveragePick,
  formatRate,
  lengthTier,
  luckAdjustedRating,
  magicNumber,
  pythagoreanCompletion,
  hotColdStreak,
  criticPlayerGap,
  peoplesChamp,
  extraInningsAvg,
  backlogMortality,
  couchReadyRate,
  perpetualBetaCount,
  protonReadyShare,
  protonCount,
  protonTrendingUp,
  protonDeckReadyBacklog,
  psnPlatinumsEarned,
  psnPlatinumHunt,
  psnTrophiesEarned,
  ps5NativeShare,
  ps4Holdouts,
  topTag,
  multiplayerTagShare,
  singleplayerBacklogCount,
  freeItchCount,
  itchSpendTotal,
  installedLocalCount,
  recentlyPlayedCount,
  longestDormant,
  avgMetacritic,
  metacriticClubCount,
  oldestWishlist,
  upcomingWishlistCount,
  protonSilverNativeShare,
  protonLowConfidenceCount,
  avgProtonScore,
  boughtOnSaleCount,
  paidItchCount,
  avgOwnedSteamPrice,
  priorityWishlistCount,
  wishlistAddedThisYear,
  wishlistStoreCount,
  lastSeenThisWeek,
  launcherInstallCount,
  hltbLowConfidenceCount,
  coopTaggedOnlyCount,
  partialControllerCount,
  indieTaggedShare,
  avgTrophyCompletion,
  gamerscoreCompletionShare,
  metacritic80UnplayedCount,
  biggestCriticGapGame,
  earlyAccessBacklogCount,
  doubleDipBacklogCount,
  letterCoverageShare,
} from '../js/sabermetrics.js';

function game(overrides = {}) {
  return {
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test Game',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    steam_review_count: overrides.steam_review_count ?? 100,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    playtime_minutes: overrides.playtime_minutes ?? 0,
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  };
}

describe('sabermetrics', () => {
  it('lengthTier buckets HLTB hours', () => {
    expect(lengthTier(game({ hltb_main_hours: 3 }))).toBe('quick');
    expect(lengthTier(game({ hltb_main_hours: 10 }))).toBe('short');
    expect(lengthTier(game({ hltb_main_hours: 30 }))).toBe('long');
    expect(lengthTier(game({ hltb_main_hours: 80 }))).toBe('epic');
  });

  it('completionAverage is finished / (finished + unfinished)', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1' }),
      game({ status: 'finished', id: '2' }),
      game({ status: 'unfinished', id: '3' }),
    ]);
    expect(completionAverage(snap)).toBeCloseTo(2 / 3, 2);
  });

  it('backlogOps combines OBP and SLG', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1', hltb_main_hours: 5, playtime_minutes: 60 }),
      game({ status: 'backlog', id: '2', playtime_minutes: 0 }),
    ]);
    const ops = backlogOps(snap);
    expect(ops).toBeGreaterThan(0);
    expect(ops).toBeLessThanOrEqual(2);
  });

  it('isBarrel requires 85%+ and <=12h', () => {
    expect(isBarrel(game({ steam_review_percent: 90, hltb_main_hours: 8 }))).toBe(true);
    expect(isBarrel(game({ steam_review_percent: 90, hltb_main_hours: 20 }))).toBe(false);
  });

  it('luckAdjustedRating regresses low review counts toward rBar', () => {
    const snap = buildLibrarySnapshot([
      game({ steam_review_percent: 70, id: '1' }),
      game({ steam_review_percent: 70, id: '2' }),
    ]);
    const adj = luckAdjustedRating(game({ steam_review_percent: 99, steam_review_count: 5 }), snap.rBar);
    expect(adj).toBeLessThan(99);
    expect(adj).toBeGreaterThan(snap.rBar - 1);
  });

  it('formatRate renders batting-style average', () => {
    expect(formatRate(0.333)).toBe('.333');
  });

  it('buildLibrarySnapshot tracks nonSkip and completionRate', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1' }),
      game({ status: 'skip', id: '2' }),
      game({ status: 'backlog', id: '3' }),
    ]);
    expect(snap.nonSkip).toBe(2);
    expect(snap.completionRate).toBeCloseTo(0.5, 2);
  });

  it('getLibrarySnapshot reuses cache for same version and length', () => {
    invalidateLibrarySnapshot();
    window._dataVersion = 1;
    const games = [game({ id: 'a' }), game({ id: 'b' })];
    const a = getLibrarySnapshot(games);
    const b = getLibrarySnapshot(games);
    expect(a).toBe(b);
  });

  it('magicNumber counts finishes needed for 50% of non-skip', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1' }),
      game({ status: 'finished', id: '2' }),
      game({ status: 'backlog', id: '3' }),
      game({ status: 'skip', id: '4' }),
    ]);
    expect(magicNumber(snap, 0.5)).toBe(0);
    const snap2 = buildLibrarySnapshot([
      game({ status: 'backlog', id: '1' }),
      game({ status: 'backlog', id: '2' }),
    ]);
    expect(magicNumber(snap2, 0.5)).toBe(1);
  });

  it('pythagoreanCompletion compares hours-based expected to completionRate', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1', playtime_minutes: 600, hltb_main_hours: 10 }),
      game({ status: 'backlog', id: '2', hltb_main_hours: 20 }),
    ]);
    const p = pythagoreanCompletion(snap);
    expect(p).not.toBeNull();
    expect(p.expected).toBeGreaterThan(0);
    expect(p.actual).toBe(snap.completionRate);
  });

  it('hotColdStreak returns cold with no finishes', () => {
    const snap = buildLibrarySnapshot([game({ status: 'backlog', id: '1' })]);
    expect(hotColdStreak(snap)).toBe('cold');
  });

  it('agingCurveBuckets uses libraryFirstSeen when present', () => {
    const now = Date.now();
    state.libraryFirstSeenByKey = { 'steam:1': now - 10 * 86400000 };
    const snap = buildLibrarySnapshot([
      game({ status: 'finished', id: '1' }),
    ]);
    const buckets = agingCurveBuckets(snap);
    expect(buckets.find(b => b.label === '<30d')?.total).toBe(1);
  });

  it('backlogValuePlus indexes above 100 for strong short titles', () => {
    const snap = buildLibrarySnapshot([
      game({ steam_review_percent: 70, id: '1' }),
      game({ steam_review_percent: 70, id: '2' }),
    ]);
    const bv = backlogValuePlus(
      game({ steam_review_percent: 95, hltb_main_hours: 5, id: 'x' }),
      snap,
    );
    expect(bv).toBeGreaterThan(100);
  });

  it('criticPlayerGap is Steam % minus Metacritic', () => {
    expect(criticPlayerGap(game({ steam_review_percent: 92, metacritic_score: 80 }))).toBe(12);
    expect(criticPlayerGap(game({ steam_review_percent: 70 }))).toBeNull();
  });

  it('peoplesChamp picks largest positive critic gap', () => {
    const games = [
      game({ id: '1', name: 'A', steam_review_percent: 90, metacritic_score: 70 }),
      game({ id: '2', name: 'B', steam_review_percent: 85, metacritic_score: 80 }),
    ];
    const champ = peoplesChamp(games);
    expect(champ?.g.name).toBe('A');
    expect(champ?.gap).toBe(20);
  });

  it('extraInningsAvg averages completionist minus main HLTB', () => {
    const snap = buildLibrarySnapshot([
      game({ hltb_main_hours: 10, hltb_completionist_hours: 25, id: '1' }),
      game({ hltb_main_hours: 20, hltb_completionist_hours: 30, id: '2' }),
    ]);
    expect(extraInningsAvg(snap)).toBe(12.5);
  });

  it('backlogMortality flags backlog winning when finish-by age is high', () => {
    const snap = buildLibrarySnapshot([
      game({ status: 'backlog', id: '1', hltb_main_hours: 40000 }),
    ]);
    const m = backlogMortality(snap);
    expect(m?.verdict).toBe('backlog');
    expect(m?.finishByAge).toBeGreaterThan(80);
  });

  it('couchReadyRate counts full controller support', () => {
    const snap = buildLibrarySnapshot([
      game({ controller_support: 'full', id: '1' }),
      game({ controller_support: 'partial', id: '2' }),
      game({ id: '3' }),
    ]);
    expect(couchReadyRate(snap)).toBeCloseTo(1 / 3, 2);
  });

  it('perpetualBetaCount counts early-access titles', () => {
    const snap = buildLibrarySnapshot([
      game({ early_access: true, id: '1' }),
      game({ id: '2' }),
    ]);
    expect(perpetualBetaCount(snap)).toBe(1);
  });

  describe('untapped metadata helpers', () => {
    it('protonReadyShare counts platinum and gold', () => {
      const games = [
        game({ protondb_tier: 'platinum', id: '1' }),
        game({ protondb_tier: 'gold', id: '2' }),
        game({ protondb_tier: 'borked', id: '3' }),
      ];
      expect(protonReadyShare(games)).toBeCloseTo(2 / 3, 2);
      expect(protonCount(games, 'platinum')).toBe(1);
      expect(protonTrendingUp([
        game({ protondb_tier: 'silver', protondb_trending_tier: 'gold', id: '1' }),
      ])).toBe(1);
    });

    it('psn platinum and trophy helpers', () => {
      const games = [
        game({ store: 'psn', id: '1', psn_platinum_earned: true, psn_trophies_earned: 10 }),
        game({ store: 'psn', id: '2', psn_has_platinum: true, psn_platinum_earned: false }),
      ];
      expect(psnPlatinumsEarned(games)).toBe(1);
      expect(psnPlatinumHunt(games)).toBe(1);
      expect(psnTrophiesEarned(games)).toBe(10);
    });

    it('ps5NativeShare and ps4Holdouts', () => {
      const games = [
        game({ store: 'psn', id: '1', psn_platforms: ['PS5'] }),
        game({ store: 'psn', id: '2', psn_platforms: ['PS4'] }),
      ];
      expect(ps5NativeShare(games)).toBe(0.5);
      expect(ps4Holdouts(games)).toBe(1);
    });

    it('tag helpers', () => {
      const games = [
        game({ tags: ['Singleplayer', 'Action'], id: '1', status: 'backlog' }),
        game({ tags: ['Multi-player', 'Action'], id: '2', status: 'backlog' }),
        game({ tags: ['Multi-player'], id: '3', status: 'finished' }),
      ];
      expect(topTag(games)?.tag).toBe('Action');
      expect(multiplayerTagShare(games)).toBeCloseTo(2 / 3, 2);
      expect(singleplayerBacklogCount(games)).toBe(1);
    });

    it('itch and install helpers', () => {
      const games = [
        game({ store: 'itch', id: '1', min_price: 0 }),
        game({ store: 'itch', id: '2', min_price: 5 }),
        game({ source: 'local', id: '3' }),
      ];
      expect(freeItchCount(games)).toBe(1);
      expect(itchSpendTotal(games)).toBe(5);
      expect(installedLocalCount(games)).toBe(1);
    });

    it('recency and metacritic helpers', () => {
      const recent = new Date(Date.now() - 5 * 86400000).toISOString();
      const old = new Date(Date.now() - 400 * 86400000).toISOString();
      const games = [
        game({ last_played: recent, playtime_minutes: 60, id: '1' }),
        game({ last_played: old, playtime_minutes: 120, name: 'Dusty', id: '2' }),
        game({ metacritic_score: 92, id: '3' }),
        game({ metacritic_score: 70, id: '4' }),
      ];
      expect(recentlyPlayedCount(games)).toBe(1);
      expect(longestDormant(games)?.g.name).toBe('Dusty');
      expect(avgMetacritic(games)).toBe(81);
      expect(metacriticClubCount(games)).toBe(1);
    });

    it('wishlist helpers prefer wishlist_added', () => {
      const wl = [
        { name: 'New', wishlist_added: Math.floor(Date.now() / 1000) - 86400 },
        { name: 'Old', wishlist_added: Math.floor(Date.now() / 1000) - 86400 * 100 },
        { name: 'Soon', release_coming_soon: true },
      ];
      expect(oldestWishlist(wl)?.g.name).toBe('Old');
      expect(upcomingWishlistCount(wl)).toBe(1);
    });

    it('protonDeckReadyBacklog counts backlog platinum/gold only', () => {
      const games = [
        game({ protondb_tier: 'gold', id: '1', status: 'backlog' }),
        game({ protondb_tier: 'platinum', id: '2', status: 'finished' }),
      ];
      expect(protonDeckReadyBacklog(games)).toBe(1);
    });

    it('batch-2 proton and pricing helpers', () => {
      const games = [
        game({ protondb_tier: 'silver', protondb_score: 0.8, id: '1' }),
        game({ protondb_tier: 'gold', protondb_score: 0.9, protondb_confidence: 'inadequate', id: '2' }),
        game({ store: 'steam', discount_percent: 50, price_amount: 19.99, id: '3' }),
        game({ store: 'itch', min_price: 5, id: '4' }),
      ];
      expect(protonSilverNativeShare(games)).toBe(0.5);
      expect(protonLowConfidenceCount(games)).toBe(1);
      expect(avgProtonScore(games)).toBe(0.85);
      expect(boughtOnSaleCount(games)).toBe(1);
      expect(paidItchCount(games)).toBe(1);
      expect(avgOwnedSteamPrice(games)).toBe(19.99);
    });

    it('batch-2 wishlist, tags, and identity helpers', () => {
      const yearStart = Date.UTC(new Date().getFullYear(), 0, 1);
      const wl = [
        { name: 'A', wishlist_priority: 1, wishlist_store: 'steam', wishlist_added: Math.floor(yearStart / 1000) + 86400 },
        { name: 'B', wishlist_store: 'gog' },
      ];
      expect(priorityWishlistCount(wl)).toBe(1);
      expect(wishlistAddedThisYear(wl)).toBe(1);
      expect(wishlistStoreCount(wl)).toBe(2);

      const games = [
        game({ name: 'Co-op Game', tags: ['Co-op'], id: '1' }),
        game({ name: 'Indie Hit', tags: ['Indie', 'Action'], controller_support: 'partial', early_access: true, id: '2' }),
        game({ name: 'Alpha', id: '3' }),
        game({ name: 'Beta', id: '4' }),
      ];
      expect(coopTaggedOnlyCount(games)).toBe(1);
      expect(partialControllerCount(games)).toBe(1);
      expect(indieTaggedShare(games)).toBeCloseTo(0.5);
      expect(earlyAccessBacklogCount(games)).toBe(1);
      expect(letterCoverageShare(games)).toBeCloseTo(4 / 26);

      const adult = [
        game({ name: 'Lewd Quest', genres: ['Sexual Content', 'RPG'], id: 'a1' }),
        game({ name: 'NSFW Tag', tags: ['NSFW'], id: 'a2' }),
        game({ name: 'Wholesome', genres: ['Puzzle'], tags: ['Casual'], id: 'a3' }),
      ];
      expect(adultGameCount(adult)).toBe(2);
      expect(adultGameCount([game({ name: 'Clean', id: 'c1' })])).toBeNull();
    });

    it('batch-2 platform and critic gap helpers', () => {
      const games = [
        game({ store: 'psn', psn_trophies_earned: 50, psn_trophies_total: 100, id: '1' }),
        game({ store: 'xbox', xbox_gamerscore_current: 500, xbox_gamerscore_total: 1000, id: '2' }),
        game({ metacritic_score: 85, playtime_minutes: 0, steam_review_percent: 60, id: '3' }),
        game({ metacritic_score: 70, steam_review_percent: 90, playtime_minutes: 0, id: '4' }),
      ];
      expect(avgTrophyCompletion(games)).toBe(0.5);
      expect(gamerscoreCompletionShare(games)).toBe(0.5);
      expect(metacritic80UnplayedCount(games)).toBe(1);
      expect(biggestCriticGapGame(games)?.g.id).toBe('3');

      const recent = new Date(Date.now() - 2 * 86400000).toISOString();
      expect(lastSeenThisWeek([game({ last_seen: recent, id: '5' })])).toBe(1);
      expect(launcherInstallCount([game({ source: 'launcher', id: '6' })])).toBe(1);
      expect(hltbLowConfidenceCount([game({ hltb_main_hours: 10, hltb_match_confidence: 0.5, id: '7' })])).toBe(1);
    });
  });
});
