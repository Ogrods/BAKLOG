import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn((g) => {
    if (g._free) return { regular: 0, price: 0, cut: 0 };
    return g._deal || null;
  }),
  dealScore: vi.fn(() => 10),
}));

import { state } from '../js/state.js';
import { buildLibrarySnapshot } from '../js/sabermetrics.js';
import { computeCreativeMetrics } from '../js/creative-metrics.js';

function game(overrides = {}) {
  return {
    store: 'steam',
    id: overrides.id ?? '1',
    name: overrides.name ?? 'Test Game',
    steam_review_percent: overrides.steam_review_percent ?? 85,
    hltb_main_hours: overrides.hltb_main_hours ?? 10,
    playtime_minutes: overrides.playtime_minutes ?? 0,
    release_date: overrides.release_date ?? '2020-01-01',
    added_at: overrides.added_at ?? '2024-06-01',
    _personal: { status: overrides.status ?? 'backlog' },
    ...overrides,
  };
}

describe('creative-metrics', () => {
  beforeEach(() => {
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
  });

  it('returns empty diagnosis when library has fewer than 5 games', () => {
    const games = [game({ id: '1' }), game({ id: '2' })];
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.diagnosis).toBeNull();
  });

  it('computes PSN tenure and session grinder when snapshot has PSN data', () => {
    const games = Array.from({ length: 6 }, (_, i) =>
      game({
        id: String(i),
        store: i <= 1 ? 'psn' : 'steam',
        first_played: i === 0 ? '2018-01-01T00:00:00Z' : undefined,
        play_count: i === 1 ? 30 : undefined,
        playtime_minutes: i === 1 ? 5 * 60 : 0,
      }),
    );
    const snap = {
      ...buildLibrarySnapshot(games),
      oldestFirstPlayedMs: Date.parse('2018-01-01T00:00:00Z'),
      psnSessionTotal: 30,
    };
    const m = computeCreativeMetrics(games, snap);
    expect(m.psnTenureYears).not.toBeNull();
    expect(m.sessionHeavy?.name).toBe(games[1].name);
  });

  it('computes work-weeks from backlog hours', () => {
    const games = Array.from({ length: 6 }, (_, i) =>
      game({ id: String(i), status: 'backlog', hltb_main_hours: 40 }),
    );
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.workWeeksChip).toBe(Math.round(snap.backlogHrs / 40));
  });

  it('lists missing A–Z letters', () => {
    const games = [
      game({ id: '1', name: 'Alpha' }),
      game({ id: '2', name: 'Beta' }),
      game({ id: '3', name: 'Gamma' }),
      game({ id: '4', name: 'Delta' }),
      game({ id: '5', name: 'Echo' }),
    ];
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.azGaps).toContain('Z');
    expect(m.azGaps).not.toContain('A');
  });

  it('counts free never-launched backlog titles', () => {
    const games = [
      game({ id: '0', name: 'Freebie', status: 'backlog', _free: true }),
      ...Array.from({ length: 5 }, (_, i) =>
        game({
          id: String(i + 1),
          name: `Paid ${i}`,
          status: 'backlog',
          playtime_minutes: 0,
          _deal: { regular: 19.99, price: 9.99, cut: 50 },
        }),
      ),
    ];
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.freePile).toBe(1);
  });

  it('maps a diagnosis label when library is large and untouched', () => {
    const games = Array.from({ length: 8 }, (_, i) =>
      game({
        id: String(i),
        status: 'backlog',
        playtime_minutes: 0,
      }),
    );
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.diagnosis).toBeTruthy();
    expect(typeof m.diagnosis).toBe('string');
  });

  it('computes comfort genre from finished titles', () => {
    const games = [
      game({ id: '1', name: 'RPG One', status: 'finished', genres: ['RPG'] }),
      game({ id: '2', name: 'RPG Two', status: 'finished', genres: ['RPG'] }),
      game({ id: '3', name: 'FPS', status: 'backlog', genres: ['Shooter'] }),
      game({ id: '4', name: 'RPG Three', status: 'backlog', genres: ['RPG'] }),
      game({ id: '5', name: 'RPG Four', status: 'backlog', genres: ['RPG'] }),
    ];
    const snap = buildLibrarySnapshot(games);
    const m = computeCreativeMetrics(games, snap);
    expect(m.comfortGenre?.genre).toBe('RPG');
    expect(m.comfortGenre?.count).toBe(2);
  });
});
