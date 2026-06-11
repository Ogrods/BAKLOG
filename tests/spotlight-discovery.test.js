/** Spotlight discovery categories: unreviewed, unplayed, total mystery, supposedly perfect. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((arr) => arr),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 0),
  isStealDeal: vi.fn(() => false),
  cutBucketClass: vi.fn(() => 'cut-low'),
  parsePriceLike: vi.fn((v) => {
    if (v == null) return null;
    if (typeof v === 'number') return v;
    const m = String(v).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }),
}));

vi.mock('../js/creative-metrics.js', () => ({
  computeSpotlightSuperlatives: vi.fn(() => []),
}));

vi.mock('../js/sabermetrics.js', async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    topWarGame: vi.fn(() => null),
  };
});

function artGame(overrides = {}) {
  return {
    name: 'Test Game',
    store: 'steam',
    steam_appid: 100001,
    header_image: 'https://example.com/cover.jpg',
    steam_review_percent: 0,
    steam_review_count: 0,
    hltb_main_hours: null,
    playtime_minutes: 0,
    _personal: { status: 'backlog' },
    ...overrides,
  };
}

describe('spotlight discovery categories', () => {
  let pickSpotlightGames;
  let setStinkerChanceForTest;
  let setRandomPickChanceForTest;
  let setCatGameChanceForTest;
  let setScoreJitterForTest;
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
    state.prefs = {};
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
    } = await import('../js/dashboard-spotlight.js'));

    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(0);
    setScoreJitterForTest(0);
  });

  function eyebrowsFor(games) {
    return pickSpotlightGames(games).map((g) => g._spotlightReason?.eyebrow);
  }

  it('tags a blank-slate backlog game as Total mystery', () => {
    const g = artGame({ name: 'Unknown Quest' });
    expect(eyebrowsFor([g])).toContain('Total mystery');
  });

  it('tags unrated games with some metadata as Unreviewed', () => {
    const g = artGame({
      name: 'Rated Later',
      hltb_main_hours: 6,
      playtime_minutes: 30,
    });
    expect(eyebrowsFor([g])).toContain('Unreviewed');
    expect(eyebrowsFor([g])).not.toContain('Total mystery');
  });

  it('tags never-launched low-signal games as Unplayed', () => {
    const g = artGame({
      name: 'Shelf Sitter',
      steam_review_percent: 65,
      steam_review_count: 80,
      hltb_main_hours: 10,
      playtime_minutes: 0,
    });
    expect(eyebrowsFor([g])).toContain('Unplayed');
  });

  it('tags 100% on a thin sample as Supposedly perfect', () => {
    const g = artGame({
      name: 'Too Good',
      steam_review_percent: 100,
      steam_review_count: 12,
      hltb_main_hours: 20,
    });
    expect(eyebrowsFor([g])).toContain('Supposedly perfect');
    expect(eyebrowsFor([g])).not.toContain('Hidden gem');
  });
});
