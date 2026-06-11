/** Direct unit tests for gameSpotlightReason (spotlight eyebrow routing). */
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
  filterOutHidden: vi.fn((arr) => arr),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  cutBucketClass: vi.fn(() => 'cut-low'),
}));

vi.mock('../js/creative-metrics.js', () => ({
  computeSpotlightSuperlatives: vi.fn(() => []),
}));

vi.mock('../js/sabermetrics.js', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, topWarGame: vi.fn(() => null) };
});

function game(overrides = {}) {
  return {
    name: 'Test',
    store: 'steam',
    steam_appid: 42,
    header_image: 'https://example.com/c.jpg',
    steam_review_percent: 0,
    steam_review_count: 0,
    hltb_main_hours: null,
    playtime_minutes: 0,
    _personal: { status: 'backlog' },
    ...overrides,
  };
}

describe('gameSpotlightReason', () => {
  let gameSpotlightReason;

  beforeEach(async () => {
    vi.resetModules();
    ({ gameSpotlightReason } = await import('../js/dashboard-spotlight.js'));
  });

  it('routes 100% with zero reviews to Supposedly perfect', () => {
    const reason = gameSpotlightReason(game({
      steam_review_percent: 100,
      steam_review_count: 0,
      hltb_main_hours: 10,
    }));
    expect(reason?.eyebrow).toBe('Supposedly perfect');
  });

  it('routes sub-70 never-played titles to Unplayed', () => {
    const reason = gameSpotlightReason(game({
      steam_review_percent: 65,
      steam_review_count: 100,
      hltb_main_hours: 8,
      playtime_minutes: 0,
    }));
    expect(reason?.eyebrow).toBe('Unplayed');
  });
});
