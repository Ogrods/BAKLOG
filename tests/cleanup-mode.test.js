/**
 * Cleanup mode: shared criteria helper, filter integration, cross-store playtime.
 */

import { describe, expect, it } from 'vitest';
import { isCleanupCandidateFromParts, CLEANUP_MIN_AGE_MS } from '../js/state.js';
import { queryGames } from '../js/table-query.js';

const NOW = Date.parse('2026-06-01');
const OLD_RELEASE = '2019-01-01';
const RECENT_RELEASE = '2025-01-01';

const baseGame = {
  appid: 1,
  store: 'steam',
  id: 1,
  name: 'Test Game',
  playtime_minutes: 0,
  steam_review_percent: 50,
  release_date: OLD_RELEASE,
  hltb_main_hours: 10,
};

const emptyPrefs = {
  genreFilters: [],
  genreFilterMode: 'OR',
  coopFilterMode: 'off',
};

function ctx(overrides = {}) {
  return {
    view: 'library',
    prefs: { ...emptyPrefs, ...(overrides.prefs || {}) },
    params: {
      q: '',
      status: '',
      unplayed: false,
      earlyAccess: false,
      minRating: 0,
      maxHours: 200,
      ...(overrides.params || {}),
    },
    personal: overrides.personal || { 'steam:1': { status: 'backlog' } },
    hiddenKeys: overrides.hiddenKeys || new Set(),
    ownedNormNames: overrides.ownedNormNames || new Set(),
    itadByKey: overrides.itadByKey || {},
    cleanupModeActive: !!overrides.cleanupModeActive,
    sortKey: overrides.sortKey || 'name',
    sortDir: overrides.sortDir ?? 1,
    combinedPlaytime: overrides.combinedPlaytime || new Map(),
    playedTitleNorms: overrides.playedTitleNorms || new Set(),
  };
}

describe('isCleanupCandidateFromParts', () => {
  it('accepts a qualifying backlog game', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: false,
      rating: 50,
      releaseMs: Date.parse(OLD_RELEASE),
      now: NOW,
    })).toBe(true);
  });

  it('rejects unknown release date', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: false,
      rating: 50,
      releaseMs: 0,
      now: NOW,
    })).toBe(false);
  });

  it('rejects unrated games', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: false,
      rating: 0,
      releaseMs: Date.parse(OLD_RELEASE),
      now: NOW,
    })).toBe(false);
  });

  it('rejects rating at the 60% boundary', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: false,
      rating: 60,
      releaseMs: Date.parse(OLD_RELEASE),
      now: NOW,
    })).toBe(false);
  });

  it('rejects untagged (non-explicit backlog) games', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: false,
      played: false,
      rating: 50,
      releaseMs: Date.parse(OLD_RELEASE),
      now: NOW,
    })).toBe(false);
  });

  it('rejects played games', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: true,
      rating: 50,
      releaseMs: Date.parse(OLD_RELEASE),
      now: NOW,
    })).toBe(false);
  });

  it('rejects games younger than two years', () => {
    expect(isCleanupCandidateFromParts({
      explicitBacklog: true,
      played: false,
      rating: 50,
      releaseMs: NOW - CLEANUP_MIN_AGE_MS + 86400000,
      now: NOW,
    })).toBe(false);
  });
});

describe('queryGames cleanup mode', () => {
  it('shows a qualifying candidate when cleanup mode is on', () => {
    const source = [{ ...baseGame }];
    const out = queryGames({ source, ctx: ctx({ cleanupModeActive: true }) });
    expect(out).toHaveLength(1);
  });

  it('filters out played games', () => {
    const source = [{ ...baseGame, playtime_minutes: 30 }];
    const out = queryGames({ source, ctx: ctx({ cleanupModeActive: true }) });
    expect(out).toHaveLength(0);
  });

  it('filters out high-rated games', () => {
    const source = [{ ...baseGame, steam_review_percent: 85 }];
    const out = queryGames({ source, ctx: ctx({ cleanupModeActive: true }) });
    expect(out).toHaveLength(0);
  });

  it('filters out recent releases', () => {
    const source = [{ ...baseGame, release_date: RECENT_RELEASE }];
    const out = queryGames({ source, ctx: ctx({ cleanupModeActive: true }) });
    expect(out).toHaveLength(0);
  });

  it('filters out unrated games', () => {
    const source = [{ ...baseGame, steam_review_percent: null }];
    const out = queryGames({ source, ctx: ctx({ cleanupModeActive: true }) });
    expect(out).toHaveLength(0);
  });

  it('filters out untagged games without an explicit backlog entry', () => {
    const source = [{ ...baseGame }];
    const out = queryGames({
      source,
      ctx: ctx({ cleanupModeActive: true, personal: {} }),
    });
    expect(out).toHaveLength(0);
  });

  it('excludes a 0h row when a cross-store sibling has playtime', () => {
    const steamRow = { ...baseGame, id: 1, store: 'steam', name: 'Cross Title' };
    const psnRow = {
      ...baseGame,
      id: 2,
      store: 'psn',
      name: 'Cross Title',
      playtime_minutes: 120,
    };
    const out = queryGames({
      source: [steamRow, psnRow],
      ctx: ctx({
        cleanupModeActive: true,
        personal: {
          'steam:1': { status: 'backlog' },
          'psn:2': { status: 'backlog' },
        },
        playedTitleNorms: new Set(['cross title']),
      }),
    });
    expect(out).toHaveLength(0);
  });

  it('is compatible with the unplayed filter', () => {
    const source = [{ ...baseGame }];
    const out = queryGames({
      source,
      ctx: ctx({ cleanupModeActive: true, params: { unplayed: true } }),
    });
    expect(out).toHaveLength(1);
  });

  it('returns empty when status filter conflicts with backlog requirement', () => {
    const source = [{ ...baseGame }];
    const out = queryGames({
      source,
      ctx: ctx({ cleanupModeActive: true, params: { status: 'playing' } }),
    });
    expect(out).toHaveLength(0);
  });
});
