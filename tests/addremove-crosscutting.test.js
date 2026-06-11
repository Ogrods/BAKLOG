/**
 * Cross-cutting reactions to add/remove (re-audit bucket 3).
 *
 * Covers: cross-store dedup interacting with user-hidden filtering, the
 * "X of Y" row-count denominators, LibrarySnapshot cache invalidation on
 * _dataVersion bumps, and the dashboard spotlight/marquee data source.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { hydrateIndexDocument } from './a11y/hydrate-index.js';
import { state } from '../js/state.js';
import { queryGames } from '../js/table-query.js';
import {
  recomputeCrossStoreHidden,
  gameKey,
} from '../js/game-core.js';
import { setGameHidden, addManualGame, removeManualGame, setPersonal } from '../js/personal-storage.js';
import { refreshAfterManualChange } from '../js/library-load.js';
import { formatRowCountText } from '../js/table-ui.js';
import {
  getLibrarySnapshot,
  librarySnapshotCacheKey,
  invalidateLibrarySnapshot,
} from '../js/sabermetrics.js';
import { dashboardLibraryGames } from '../js/dashboard-shared.js';
import { buildMarqueeItems } from '../js/dashboard-insights.js';

const fortniteSteam = { store: 'steam', id: 1, name: 'Fortnite', playtime_minutes: 0, header_image: 'h' };
const fortniteEpic = { store: 'epic', id: 'abc', name: 'Fortnite', playtime_minutes: 0, header_image: 'h' };
const solo = { store: 'gog', id: 9, name: 'Solo Title', playtime_minutes: 0, header_image: 'h' };

function ctx(personal, view = 'library', hiddenKeys = new Set()) {
  return {
    view,
    prefs: { genreFilters: [], genreFilterMode: 'OR', coopFilterMode: 'off' },
    params: { q: '', status: '', unplayed: false, earlyAccess: false, minRating: 0, maxHours: 200 },
    personal,
    hiddenKeys,
    ownedNormNames: new Set(),
    itadByKey: {},
    cleanupModeActive: false,
    sortKey: 'name',
    sortDir: 1,
  };
}

beforeEach(() => {
  // refreshAfterManualChange fires applyMergedLibrary, which paints chips; give
  // it the real container DOM so those renders don't throw on null elements.
  // Fake timers + the dashboard view keep the debounced (Chart.js) render from
  // firing during assertions.
  vi.useFakeTimers();
  hydrateIndexDocument();
  state.activeView = 'dashboard';
  state.personal = {};
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  state.crossStoreHiddenKeys = new Set();
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.sessionPrefs = { ...(state.sessionPrefs || {}), crossStoreDedup: true, itchHideNonGames: false };
  window._dataVersion = 0;
  localStorage.clear();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe('cross-store dedup + hidden filtering', () => {
  it('dedup hides one copy; hiding the visible copy removes the whole title', () => {
    state.allGames = [fortniteSteam, fortniteEpic];
    recomputeCrossStoreHidden();
    expect(state.crossStoreHiddenKeys.size).toBe(1);

    const visible = queryGames({ source: state.allGames, ctx: ctx(state.personal, 'library', state.crossStoreHiddenKeys) });
    expect(visible).toHaveLength(1);

    // Hiding the surviving representative mirrors across both store copies.
    setGameHidden(visible[0], true, { silent: true });
    const after = queryGames({ source: state.allGames, ctx: ctx(state.personal, 'library', state.crossStoreHiddenKeys) });
    expect(after).toHaveLength(0);
  });
});

describe('row-count denominators', () => {
  it('library "of Y" reacts to manual add, user-hide, and manual delete', () => {
    state.allGames = [solo];
    recomputeCrossStoreHidden();
    expect(formatRowCountText('library', [solo])).toBe('Showing 1 of 1 games');

    // Manual add bumps the denominator.
    const manual = { store: 'steam', id: 'manual-x', name: 'Added', manual: true, playtime_minutes: 0 };
    addManualGame(manual);
    refreshAfterManualChange();
    recomputeCrossStoreHidden();
    const withManual = state.allGames;
    expect(formatRowCountText('library', withManual)).toBe(`Showing 2 of 2 games`);

    // User-hiding a pulled row drops the denominator.
    setGameHidden(solo, true, { silent: true });
    expect(formatRowCountText('library', [manual])).toBe('Showing 1 of 1 games');

    // Deleting the manual row drops it back out of the catalog.
    removeManualGame('steam', 'manual-x');
    refreshAfterManualChange();
    recomputeCrossStoreHidden();
    expect(formatRowCountText('library', [])).toBe('Showing 0 of 0 games');
  });
});

describe('manual count toggle', () => {
  it('count-off removes a manual item from the "of Y" denominator and dashboard total; toggling back restores it', () => {
    state.allGames = [solo];
    recomputeCrossStoreHidden();
    expect(formatRowCountText('library', [solo])).toBe('Showing 1 of 1 games');
    expect(dashboardLibraryGames()).toHaveLength(1);

    const manual = { store: 'steam', id: 'manual-c', name: 'Counted', manual: true, playtime_minutes: 0 };
    addManualGame(manual);
    refreshAfterManualChange();
    recomputeCrossStoreHidden();
    const withManual = state.allGames;
    const manualRow = withManual.find(g => g.id === 'manual-c');
    expect(manualRow).toBeTruthy();
    expect(formatRowCountText('library', withManual)).toBe('Showing 2 of 2 games');
    expect(dashboardLibraryGames()).toHaveLength(2);

    // Toggle the manual item out of the headline count (Count checkbox off).
    setPersonal(manualRow, 'exclude_from_count', true, { silent: true });
    expect(formatRowCountText('library', withManual)).toBe('Showing 1 of 1 games');
    const counted = dashboardLibraryGames();
    expect(counted).toHaveLength(1);
    expect(counted.some(g => gameKey(g) === gameKey(manualRow))).toBe(false);

    // Toggling back restores it to both the denominator and the dashboard total.
    setPersonal(manualRow, 'exclude_from_count', false, { silent: true });
    expect(formatRowCountText('library', withManual)).toBe('Showing 2 of 2 games');
    expect(dashboardLibraryGames()).toHaveLength(2);
  });

  it('count-off only affects manual rows, never fetched store games', () => {
    state.allGames = [solo];
    recomputeCrossStoreHidden();
    // Fetched rows never carry exclude_from_count, so the count helper is a no-op.
    setPersonal(solo, 'exclude_from_count', true, { silent: true });
    setPersonal(solo, 'exclude_from_count', false, { silent: true });
    expect(formatRowCountText('library', [solo])).toBe('Showing 1 of 1 games');
  });
});

describe('LibrarySnapshot invalidation', () => {
  it('memoizes per _dataVersion and recomputes on bump or explicit invalidation', () => {
    const games = [solo];
    window._dataVersion = 0;
    const s1 = getLibrarySnapshot(games);
    expect(getLibrarySnapshot(games)).toBe(s1);
    expect(librarySnapshotCacheKey(games)).toBe('0:1');

    window._dataVersion = 1;
    const s2 = getLibrarySnapshot(games);
    expect(s2).not.toBe(s1);
    expect(librarySnapshotCacheKey(games)).toBe('1:1');

    invalidateLibrarySnapshot();
    expect(getLibrarySnapshot(games)).not.toBe(s2);
  });
});

describe('spotlight / marquee data source', () => {
  it('dashboardLibraryGames excludes deduped and user-hidden rows', () => {
    state.allGames = [fortniteSteam, fortniteEpic, solo];
    recomputeCrossStoreHidden();
    // 1 of the fortnite copies is deduped out → 2 visible.
    expect(dashboardLibraryGames()).toHaveLength(2);

    setGameHidden(solo, true, { silent: true });
    const games = dashboardLibraryGames();
    expect(games.some(g => gameKey(g) === gameKey(solo))).toBe(false);
  });

  it('marquee "games owned" reflects the supplied library size', () => {
    state.allGames = [solo];
    const games = dashboardLibraryGames();
    const items = buildMarqueeItems(games, getLibrarySnapshot(games));
    const owned = items.find(i => i.label === 'games owned');
    expect(owned).toBeTruthy();
    expect(owned.valueHtml).toContain(String(games.length));
  });
});
