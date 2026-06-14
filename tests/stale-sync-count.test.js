/**
 * Audit: the "Stale sync" summary chip count must match the number of rows the
 * staleOnly filter actually surfaces in the library table.
 *
 * Bug report: chip shows 17 but the filtered table only lists 11. Root cause
 * hypotheses:
 *   H1 — the chip counts state.allGames raw, including cross-store dedup
 *        duplicates that passesFilter() removes via hiddenKeys.
 *   H2 — the chip also counts user-hidden rows (personal.hidden) that
 *        passesFilter() drops.
 *
 * This test reconstructs that scenario and proves the divergence, then pins the
 * corrected count (stale rows on the same visible base the table renders from).
 */

import { describe, expect, it } from 'vitest';
import { queryGames, gameKey } from '../js/table-query.js';

const base = {
  store: 'steam',
  name: 'Game',
  playtime_minutes: 0,
  steam_review_percent: 80,
  hltb_main_hours: 10,
};

/** 11 plainly-visible stale rows. */
const visibleStale = Array.from({ length: 11 }, (_, i) => ({
  ...base, id: 100 + i, name: `Visible Stale ${i}`, stale: true,
}));

/** 4 stale rows that are cross-store duplicates → live in crossStoreHiddenKeys. */
const dupStale = Array.from({ length: 4 }, (_, i) => ({
  ...base, store: 'gog', id: 200 + i, name: `Dup Stale ${i}`, stale: true,
}));

/** 2 stale rows the user hid via the per-row hide toggle (personal.hidden). */
const hiddenStale = Array.from({ length: 2 }, (_, i) => ({
  ...base, id: 300 + i, name: `Hidden Stale ${i}`, stale: true,
}));

/** Fresh (non-stale) noise that must never count toward the chip. */
const freshGames = Array.from({ length: 5 }, (_, i) => ({
  ...base, id: 400 + i, name: `Fresh ${i}`,
}));

const allGames = [...visibleStale, ...dupStale, ...hiddenStale, ...freshGames];

const hiddenKeys = new Set(dupStale.map(gameKey));
const personal = Object.fromEntries(
  hiddenStale.map(g => [gameKey(g), { hidden: true }]),
);

function ctx(overrides = {}) {
  return {
    view: 'library',
    prefs: { genreFilters: [], genreFilterMode: 'OR', coopFilterMode: 'off' },
    params: {
      q: '', status: '', unplayed: false, earlyAccess: false,
      staleOnly: true, minRating: 0, maxHours: 200,
    },
    personal,
    hiddenKeys,
    ownedNormNames: new Set(),
    itadByKey: {},
    cleanupModeActive: false,
    sortKey: 'name',
    sortDir: 1,
    ...overrides,
  };
}

describe('stale-sync chip count vs. filtered table', () => {
  it('the naive chip formula overcounts (reproduces 17 vs 11)', () => {
    // js/filters-ui.js:837 — the buggy count.
    const naiveChipCount = allGames.filter(g => g.stale).length;
    expect(naiveChipCount).toBe(17);

    // What the staleOnly table filter actually surfaces.
    const filtered = queryGames({ source: allGames, ctx: ctx() });
    expect(filtered).toHaveLength(11);

    // The discrepancy the user saw.
    expect(naiveChipCount).not.toBe(filtered.length);
  });

  it('H1: cross-store duplicates inflate the chip count', () => {
    const filtered = queryGames({ source: allGames, ctx: ctx() });
    const surfacedDup = filtered.some(g => g.name.startsWith('Dup Stale'));
    expect(surfacedDup).toBe(false);
  });

  it('H2: user-hidden rows inflate the chip count', () => {
    const filtered = queryGames({ source: allGames, ctx: ctx() });
    const surfacedHidden = filtered.some(g => g.name.startsWith('Hidden Stale'));
    expect(surfacedHidden).toBe(false);
  });

  it('corrected count: stale rows on the visible base equals the filtered table', () => {
    // The fix: count stale on the same visible base the summary already builds
    // (state.allGames minus cross-store dupes minus personal-hidden).
    const visibleBase = allGames
      .filter(g => !hiddenKeys.has(gameKey(g)))
      .filter(g => personal[gameKey(g)]?.hidden !== true);
    const correctedChipCount = visibleBase.filter(g => g.stale).length;

    const filtered = queryGames({ source: allGames, ctx: ctx() });
    expect(correctedChipCount).toBe(filtered.length);
    expect(correctedChipCount).toBe(11);
  });
});
