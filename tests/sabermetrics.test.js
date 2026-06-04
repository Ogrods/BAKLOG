import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
}));

import { state } from '../js/state.js';
import {
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
});
