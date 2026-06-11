/** Spotlight pool variety: family balance, jitter, quality floor, persistence. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';
import { ratingValue } from '../js/game-core.js';
import { familyForEyebrow, FAMILY } from '../js/stat-families.js';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((arr) => arr),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn((g) => g._deal || null),
  dealScore: vi.fn(() => 10),
  cutBucketClass: vi.fn(() => ''),
  isStealDeal: vi.fn(() => false),
  parsePriceLike: vi.fn((v) => {
    if (v == null) return null;
    if (typeof v === 'number') return v;
    const m = String(v).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }),
}));

const FRAMED_LOW_RATED_EYEBROWS = new Set([
  'Rare stinker',
  'Guilty pleasure',
  'Gathering dust',
  'Time capsule',
  'Whale',
  // Discovery fallbacks for low-signal backlog titles (spotlight-discovery).
  'Supposedly perfect',
  'Unreviewed',
  'Unplayed',
  'Total mystery',
]);

const NORMAL_MIN_RATING = 70;

describe('spotlight variety pool', () => {
  let pickSpotlightGames;
  let setStinkerChanceForTest;
  let setRandomPickChanceForTest;
  let setCatGameChanceForTest;
  let setScoreJitterForTest;
  let resetSpotlightRecentKeysForTest;
  let SPOTLIGHT_POOL_FRACTION;
  let RATING_FAMILY_CAP;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    localStorage.clear();

    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    state.personal = {};
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;

    ({
      pickSpotlightGames,
      setStinkerChanceForTest,
      setRandomPickChanceForTest,
      setCatGameChanceForTest,
      setScoreJitterForTest,
      resetSpotlightRecentKeysForTest,
      SPOTLIGHT_POOL_FRACTION,
      RATING_FAMILY_CAP,
    } = await import('../js/dashboard-spotlight.js'));

    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(0);
    setScoreJitterForTest(0);
    resetSpotlightRecentKeysForTest();
  });

  afterEach(() => {
    localStorage.clear();
  });

  const artGame = (overrides = {}) => ({
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test Game',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    steam_review_count: overrides.steam_review_count ?? 1000,
    library_image: 'x.jpg',
    header_image: 'x.jpg',
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    release_date: overrides.release_date ?? '2018-06-01',
    playtime_minutes: overrides.playtime_minutes ?? 0,
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  });

  it('caps RATING-family membership when other families have candidates', () => {
    const games = [
      ...Array.from({ length: 50 }, (_, i) =>
        artGame({
          id: String(i),
          name: `Highly Rated ${i}`,
          steam_review_percent: 92,
          hltb_main_hours: 6,
        }),
      ),
      ...Array.from({ length: 20 }, (_, i) =>
        artGame({
          id: String(100 + i),
          name: `Weekend ${i}`,
          steam_review_percent: 74,
          hltb_main_hours: 12,
          release_date: '2016-01-01',
        }),
      ),
      ...Array.from({ length: 10 }, (_, i) =>
        artGame({
          id: String(200 + i),
          name: `Co-op ${i}`,
          steam_review_percent: 78,
          coop_online: true,
        }),
      ),
    ];

    const pool = pickSpotlightGames(games);
    const target = Math.max(60, Math.round(games.length * SPOTLIGHT_POOL_FRACTION));
    const ratingCap = Math.max(1, Math.round(target * RATING_FAMILY_CAP));
    const ratingCount = pool.filter(
      (g) => familyForEyebrow(g._spotlightReason?.eyebrow) === FAMILY.RATING,
    ).length;

    expect(pool.length).toBeGreaterThan(20);
    expect(ratingCount).toBeLessThanOrEqual(ratingCap);
    expect(pool.some((g) => familyForEyebrow(g._spotlightReason?.eyebrow) === FAMILY.TIME)).toBe(true);
  });

  it('includes mid-tier qualified titles when the pool fraction is widened', () => {
    const games = [
      ...Array.from({ length: 30 }, (_, i) =>
        artGame({
          id: String(i),
          name: `Elite ${i}`,
          steam_review_percent: 94,
          hltb_main_hours: 5,
        }),
      ),
      ...Array.from({ length: 30 }, (_, i) =>
        artGame({
          id: String(100 + i),
          name: `Solid ${i}`,
          steam_review_percent: 76,
          hltb_main_hours: 14,
          release_date: '2014-03-01',
        }),
      ),
    ];

    const pool = pickSpotlightGames(games);
    const solidInPool = pool.filter((g) => (g.name || '').startsWith('Solid'));
    expect(solidInPool.length).toBeGreaterThan(0);
  });

  it('keeps a strict quality floor except framed special eyebrows', () => {
    const games = [
      artGame({ id: '1', name: 'Bad Unframed', steam_review_percent: 45 }),
      artGame({ id: '2', name: 'Also Bad', steam_review_percent: 52 }),
      ...Array.from({ length: 12 }, (_, i) =>
        artGame({ id: String(10 + i), steam_review_percent: 82 }),
      ),
    ];

    const pool = pickSpotlightGames(games);
    for (const g of pool) {
      const eyebrow = g._spotlightReason?.eyebrow;
      if (FRAMED_LOW_RATED_EYEBROWS.has(eyebrow) || g._spotlightReason?.isRandom) continue;
      expect(ratingValue(g)).toBeGreaterThanOrEqual(NORMAL_MIN_RATING);
    }
  });

  it('still surfaces framed saber specials under family balancing', () => {
    const games = [
      artGame({
        id: '1',
        name: 'Guilty',
        status: 'finished',
        steam_review_percent: 58,
        playtime_minutes: 120,
      }),
      artGame({
        id: '2',
        name: 'Whale Game',
        steam_review_percent: 68,
        _deal: { regular: 59.99, price: 29.99, cut: 50 },
      }),
      ...Array.from({ length: 8 }, (_, i) =>
        artGame({ id: String(10 + i), steam_review_percent: 84, _deal: { regular: 19.99 } }),
      ),
    ];

    const pool = pickSpotlightGames(games);
    expect(pool.find((g) => g._spotlightReason?.eyebrow === 'Guilty pleasure')).toBeTruthy();
    expect(pool.find((g) => g._spotlightReason?.eyebrow === 'Whale')).toBeTruthy();
  });

  it('score jitter can change pool membership when enabled', () => {
    const games = Array.from({ length: 40 }, (_, i) =>
      artGame({
        id: String(i),
        name: `Game ${i}`,
        steam_review_percent: 72 + (i % 18),
        hltb_main_hours: 6 + (i % 10),
      }),
    );

    setScoreJitterForTest(0);
    const stable = new Set(pickSpotlightGames(games).map((g) => `${g.store}:${g.id}`));

    setScoreJitterForTest(12);
    let sawDifference = false;
    for (let attempt = 0; attempt < 30; attempt++) {
      const jittered = new Set(pickSpotlightGames(games).map((g) => `${g.store}:${g.id}`));
      for (const key of jittered) {
        if (!stable.has(key)) {
          sawDifference = true;
          break;
        }
      }
      if (sawDifference) break;
    }
    expect(sawDifference).toBe(true);
  });
});

describe('spotlight recent keys persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetModules();
  });

  it('seeds no-repeat history from profile-scoped localStorage on module load', async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.localStorage.setItem('baklog-spotlight-recent', JSON.stringify(['steam:1', 'steam:2']));

    const { getSpotlightRecentKeysForTest } = await import('../js/dashboard-spotlight.js');
    expect(getSpotlightRecentKeysForTest()).toEqual(['steam:1', 'steam:2']);
  });

  it('writes recent keys to localStorage when a slide is recorded', async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.matchMedia = vi.fn(() => ({
      matches: false,
      media: '',
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    vi.useFakeTimers();
    const { state } = await import('../js/state.js');
    state.personal = {};
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();

    const {
      pickSpotlightGames,
      renderSpotlightHtml,
      startSpotlightRotation,
      stopSpotlightRotation,
      setStinkerChanceForTest,
      setRandomPickChanceForTest,
      setCatGameChanceForTest,
      setScoreJitterForTest,
      resetSpotlightRecentKeysForTest,
      SPOTLIGHT_INTERVAL_MS,
      SPOTLIGHT_FADE_MS,
    } = await import('../js/dashboard-spotlight.js');

    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(0);
    setScoreJitterForTest(0);
    resetSpotlightRecentKeysForTest();

    const games = Array.from({ length: 12 }, (_, i) => ({
      store: 'steam',
      id: String(i + 1),
      name: `Game ${i + 1}`,
      steam_review_percent: 80 + (i % 10),
      steam_review_count: 1000,
      library_image: 'x.jpg',
      header_image: 'x.jpg',
      release_date: '2015-01-01',
      hltb_main_hours: 12,
    }));
    for (const g of games) state.personal[`steam:${g.id}`] = { status: 'backlog' };

    const pool = pickSpotlightGames(games);
    const firstKey = `${pool[0].store}:${pool[0].id}`;
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    startSpotlightRotation(pool);

    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);

    const stored = JSON.parse(localStorage.getItem('baklog-spotlight-recent') || '[]');
    expect(stored.length).toBeGreaterThanOrEqual(2);
    expect(stored).toContain(firstKey);

    stopSpotlightRotation();
    vi.useRealTimers();
  });
});
