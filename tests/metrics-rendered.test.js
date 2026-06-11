import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../js/personal-storage.js', () => ({
  getPersonal: vi.fn((g) => g._personal || { status: 'backlog' }),
}));

vi.mock('../js/deals.js', () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 0),
  isStealDeal: vi.fn(() => false),
  cutBucketClass: vi.fn(() => 'cut-low'),
  computeWishlistWoba: vi.fn(() => null),
  isCleanupCandidate: vi.fn(() => false),
  parsePriceLike: vi.fn((v) => {
    if (v == null) return null;
    if (typeof v === 'number') return v;
    const m = String(v).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }),
}));

import { state } from '../js/state.js';
import { buildMarqueeItems, buildMegaLibraryContext } from '../js/dashboard-insights.js';
import { getLibrarySnapshot, invalidateLibrarySnapshot } from '../js/sabermetrics.js';
import { METRIC_KEYS } from '../js/metric-tips.js';
import {
  computeAutoDisabled,
  noteMarqueeMetricKeys,
  noteInsightMetricKeys,
  commitRenderedMetrics,
  loadRenderedMetricKeys,
  snapshotNotedMetricKeys,
  restoreNotedMetricKeysFromArtifacts,
  isImplausibleDisabledBloat,
} from '../js/metrics-rendered.js';

describe('metrics-rendered computeAutoDisabled', () => {
  const catalog = ['games owned', 'stores', 'gamerscore earned', 'first PSN session'];

  it('moves every no-data metric to disabled', () => {
    const next = computeAutoDisabled(catalog, ['games owned', 'stores'], []);
    expect(next).toEqual(['gamerscore earned', 'first PSN session']);
  });

  it('preserves manual hides of data-having metrics', () => {
    const rendered = ['games owned', 'stores'];
    const next = computeAutoDisabled(catalog, rendered, ['stores'], rendered);
    expect(next.sort()).toEqual(['stores', 'gamerscore earned', 'first PSN session'].sort());
  });

  it('does not re-enable a no-data metric the user tried to keep used', () => {
    const next = computeAutoDisabled(catalog, ['games owned', 'stores'], []);
    expect(next).toContain('first PSN session');
  });

  it('does not duplicate keys when a manual hide also lacks data', () => {
    const next = computeAutoDisabled(catalog, ['games owned'], ['gamerscore earned']);
    expect(next).toEqual(['stores', 'gamerscore earned', 'first PSN session']);
    expect(new Set(next).size).toBe(next.length);
  });

  it('re-enables metrics after a sparse render pass auto-disabled them', () => {
    const sparse = ['finish streak', 'league avg rating'];
    const full = ['games owned', 'stores', 'finish streak', 'league avg rating'];
    const bloatedDisabled = catalog.filter((k) => !sparse.includes(k));
    const next = computeAutoDisabled(catalog, full, bloatedDisabled, sparse);
    expect(next).not.toContain('games owned');
    expect(next).not.toContain('stores');
    expect(next).toEqual(['gamerscore earned', 'first PSN session']);
  });
});

describe('commitRenderedMetrics marquee recovery', () => {
  function game(overrides = {}) {
    return {
      store: 'steam',
      id: overrides.id ?? String(Math.random()),
      name: overrides.name ?? 'Test Game',
      steam_review_percent: overrides.steam_review_percent ?? 85,
      steam_review_count: overrides.steam_review_count ?? 500,
      hltb_main_hours: overrides.hltb_main_hours ?? 10,
      playtime_minutes: overrides.playtime_minutes ?? 0,
      genres: overrides.genres ?? ['Action'],
      last_played: overrides.last_played,
      _personal: { status: overrides.status ?? 'backlog' },
      ...overrides,
    };
  }

  function makeLibrary(n = 200) {
    const statuses = ['backlog', 'finished', 'playing', 'next', 'unfinished'];
    return Array.from({ length: n }, (_, i) => game({
      id: String(i),
      name: `Game ${i}`,
      status: statuses[i % statuses.length],
      playtime_minutes: i % 3 === 0 ? 120 + i : 0,
      last_played: i % 5 === 0 ? '2026-06-01' : '2024-01-01',
    }));
  }

  beforeEach(() => {
    state.prefs = { quickWinMaxHours: 15, metricsDisabled: [] };
    state.wishlistGames = [];
    state.itchGames = [];
    window._dataVersion = 0;
    invalidateLibrarySnapshot();
    localStorage.clear();
  });

  it('does not permanently collapse marquee after a sparse rendered commit', () => {
    const games = makeLibrary(200);
    const snap = getLibrarySnapshot(games);
    const ctx = buildMegaLibraryContext(games);

    noteMarqueeMetricKeys(['finish streak', 'league avg rating']);
    commitRenderedMetrics();

    const broken = buildMarqueeItems(games, snap, ctx);
    expect(broken.length).toBeLessThan(10);

    buildMarqueeItems(games, snap, ctx);
    commitRenderedMetrics();

    expect(loadRenderedMetricKeys()).toContain('games owned');
    expect(state.prefs.metricsDisabled).not.toContain('games owned');

    const healed = buildMarqueeItems(games, snap, ctx);
    expect(healed.length).toBeGreaterThan(20);
  });
});

describe('marquee cache re-poison guard', () => {
  function game(overrides = {}) {
    return {
      store: 'steam',
      id: overrides.id ?? String(Math.random()),
      name: overrides.name ?? 'Test Game',
      steam_review_percent: overrides.steam_review_percent ?? 85,
      steam_review_count: overrides.steam_review_count ?? 500,
      hltb_main_hours: overrides.hltb_main_hours ?? 10,
      playtime_minutes: overrides.playtime_minutes ?? 0,
      genres: overrides.genres ?? ['Action'],
      last_played: overrides.last_played,
      _personal: { status: overrides.status ?? 'backlog' },
      ...overrides,
    };
  }

  function makeLibrary(n = 200) {
    const statuses = ['backlog', 'finished', 'playing', 'next', 'unfinished'];
    return Array.from({ length: n }, (_, i) => game({
      id: String(i),
      name: `Game ${i}`,
      status: statuses[i % statuses.length],
      playtime_minutes: i % 3 === 0 ? 120 + i : 0,
      last_played: i % 5 === 0 ? '2026-06-01' : '2024-01-01',
    }));
  }

  beforeEach(() => {
    state.prefs = { quickWinMaxHours: 15, metricsDisabled: [] };
    state.wishlistGames = [];
    state.itchGames = [];
    window._dataVersion = 0;
    invalidateLibrarySnapshot();
    localStorage.clear();
  });

  it('restoreNotedMetricKeysFromArtifacts uses cached pre-filter keys, not filtered chips', () => {
    const games = makeLibrary(200);
    const snap = getLibrarySnapshot(games);
    const ctx = buildMegaLibraryContext(games);

    buildMarqueeItems(games, snap, ctx);
    const { marqueeMetricKeys, insightMetricKeys } = snapshotNotedMetricKeys();
    expect(marqueeMetricKeys.length).toBeGreaterThan(15);

    noteMarqueeMetricKeys(['finish streak', 'league avg rating']);
    restoreNotedMetricKeysFromArtifacts({
      marqueeItems: [{ label: 'hot finish streak' }, { label: '83% league avg rating' }],
      marqueeMetricKeys,
      insightMetricKeys,
    });

    commitRenderedMetrics();
    const rendered = loadRenderedMetricKeys();
    expect(rendered.length).toBeGreaterThan(15);
    expect(rendered).toContain('games owned');
  });

  it('isImplausibleDisabledBloat detects bloated disabled with tiny rendered union', () => {
    const bloated = METRIC_KEYS.slice(0, Math.ceil(METRIC_KEYS.length * 0.85));
    expect(isImplausibleDisabledBloat(bloated, ['finish streak', 'league avg rating'])).toBe(true);
    expect(isImplausibleDisabledBloat(bloated, Array.from({ length: 20 }, (_, i) => `metric-${i}`))).toBe(false);
    expect(isImplausibleDisabledBloat(['games owned'], ['finish streak'])).toBe(false);
  });

  it('does not re-bloat metricsDisabled after cache-hit restore on second render pass', () => {
    const games = makeLibrary(200);
    const snap = getLibrarySnapshot(games);
    const ctx = buildMegaLibraryContext(games);

    buildMarqueeItems(games, snap, ctx);
    const cached = snapshotNotedMetricKeys();
    // Simulate persisted corruption: almost the whole catalog disabled, including data-having keys.
    state.prefs.metricsDisabled = METRIC_KEYS.filter((k) => k !== 'finish streak' && k !== 'league avg rating');
    expect(state.prefs.metricsDisabled).toContain('games owned');

    noteMarqueeMetricKeys(['finish streak', 'league avg rating']);
    noteInsightMetricKeys([]);
    commitRenderedMetrics();
    expect(state.prefs.metricsDisabled).toContain('games owned');

    restoreNotedMetricKeysFromArtifacts({
      marqueeItems: [{ label: 'hot finish streak' }, { label: '83% league avg rating' }],
      marqueeMetricKeys: cached.marqueeMetricKeys,
      insightMetricKeys: cached.insightMetricKeys,
    });
    commitRenderedMetrics();

    expect(state.prefs.metricsDisabled).not.toContain('games owned');
    expect(loadRenderedMetricKeys().length).toBeGreaterThan(15);

    const healed = buildMarqueeItems(games, snap, ctx);
    expect(healed.length).toBeGreaterThan(20);
  });
});
