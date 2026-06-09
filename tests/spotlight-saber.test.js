/** Spotlight sabermetric / creative superlative categories. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((arr) => arr),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn((g) => g._deal || null),
  dealScore: vi.fn(() => 10),
  cutBucketClass: vi.fn(() => ''),
  isStealDeal: vi.fn(() => false),
}));

describe('spotlight saber categories', () => {
  let pickSpotlightGames;
  let computeSpotlightSuperlatives;
  let buildLibrarySnapshot;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    state.personal = {};
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.prefs = {};
    win._dataVersion = (win._dataVersion || 0) + 1;

    let setStinkerChanceForTest;
    let setScoreJitterForTest;
    ({ pickSpotlightGames, setStinkerChanceForTest, setScoreJitterForTest } = await import('../js/dashboard-spotlight.js'));
    ({ computeSpotlightSuperlatives } = await import('../js/creative-metrics.js'));
    ({ buildLibrarySnapshot } = await import('../js/sabermetrics.js'));
    setStinkerChanceForTest(0);
    setScoreJitterForTest(0);
  });

  const artGame = (overrides = {}) => ({
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test Game',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    steam_review_count: overrides.steam_review_count ?? 500,
    library_image: 'x.jpg',
    header_image: 'x.jpg',
    playtime_minutes: overrides.playtime_minutes ?? 0,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  });

  it('surfaces Whale for priciest untouched backlog game', () => {
    const games = [
      artGame({ id: '1', name: 'Cheap', steam_review_percent: 70, _deal: { regular: 9.99, price: 4.99, cut: 50 } }),
      artGame({ id: '2', name: 'Whale Game', steam_review_percent: 68, _deal: { regular: 59.99, price: 29.99, cut: 50 } }),
      artGame({ id: '99', name: 'MVP Rival', steam_review_percent: 98, hltb_main_hours: 8 }),
      ...Array.from({ length: 4 }, (_, i) =>
        artGame({ id: String(10 + i), name: `Filler ${i}`, steam_review_percent: 72, _deal: { regular: 19.99, price: 9.99, cut: 0 } }),
      ),
    ];
    const pool = pickSpotlightGames(games);
    const whale = pool.find((g) => g._spotlightReason?.eyebrow === 'Whale');
    expect(whale).toBeTruthy();
    expect(whale.name).toBe('Whale Game');
    expect(whale._spotlightReason.metaParts.join(' ')).toMatch(/\$/);
    expect(whale._spotlightReason.isSaber).toBe(true);
  });

  it('surfaces Completionist for a 100% trophy game', () => {
    const games = [
      artGame({ id: '1', name: 'Platinum Hero', steam_review_percent: 92, trophy_progress: 100 }),
      ...Array.from({ length: 5 }, (_, i) =>
        artGame({ id: String(10 + i), steam_review_percent: 72, trophy_progress: 40 }),
      ),
    ];
    const snap = buildLibrarySnapshot(games);
    const picks = computeSpotlightSuperlatives(games, snap);
    const completionist = picks.find((p) => p.eyebrow === 'Completionist');
    expect(completionist).toBeTruthy();
    expect(completionist.key).toBe('steam:1');
    expect(completionist.metaParts.join(' ')).toMatch(/100%/);
  });

  it('surfaces Guilty pleasure for lowest-rated finished game', () => {
    const games = [
      artGame({ id: '1', name: 'Guilty', status: 'finished', steam_review_percent: 58, playtime_minutes: 120 }),
      artGame({ id: '2', name: 'Actually Good', status: 'finished', steam_review_percent: 92, playtime_minutes: 200 }),
      ...Array.from({ length: 4 }, (_, i) =>
        artGame({ id: String(10 + i), steam_review_percent: 80 }),
      ),
    ];
    const pool = pickSpotlightGames(games);
    const guilty = pool.find((g) => g._spotlightReason?.eyebrow === 'Guilty pleasure');
    expect(guilty).toBeTruthy();
    expect(guilty.name).toBe('Guilty');
    expect(guilty._spotlightReason.metaParts.join(' ')).toMatch(/finished anyway/);
  });

  it('computeSpotlightSuperlatives returns empty for tiny libraries', () => {
    const games = [artGame({ id: '1' })];
    const snap = buildLibrarySnapshot(games);
    expect(computeSpotlightSuperlatives(games, snap)).toEqual([]);
  });

  it('caps barrel entries in the spotlight pool', () => {
    const barrels = Array.from({ length: 35 }, (_, i) =>
      artGame({
        id: String(i),
        name: `Barrel ${i}`,
        steam_review_percent: 90,
        hltb_main_hours: 10,
        steam_review_count: 1000,
      }),
    );
    const filler = Array.from({ length: 35 }, (_, i) =>
      artGame({
        id: String(100 + i),
        name: `Solid ${i}`,
        steam_review_percent: 76,
        hltb_main_hours: 18,
        release_date: '2015-01-01',
        steam_review_count: 800,
      }),
    );
    const games = [...barrels, ...filler];
    const pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThan(10);
    const barrelCount = pool.filter((g) => g._spotlightReason?.isBarrel).length;
    expect(barrelCount).toBeGreaterThan(0);
    const targetSize = Math.min(games.length, Math.max(60, Math.round(games.length * 0.5)));
    const barrelQuota = Math.max(1, Math.round(targetSize * 0.04));
    expect(barrelCount).toBeLessThanOrEqual(barrelQuota);
    expect(barrelCount / pool.length).toBeLessThan(0.1);
  });

  it('does not crash when no deal or superlative data exists', () => {
    const games = Array.from({ length: 6 }, (_, i) =>
      artGame({ id: String(i), name: `Game ${i}`, steam_review_percent: 75 }),
    );
    expect(() => pickSpotlightGames(games)).not.toThrow();
    const pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThan(0);
  });
});
