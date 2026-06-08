/** computeRecentAdditions — dashboard recents card data. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

describe('computeRecentAdditions', () => {
  let computeRecentAdditions;
  let state;
  let gameKey;

  beforeEach(async () => {
    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    ({ computeRecentAdditions } = await import('../js/dashboard-spotlight.js'));
    ({ gameKey } = await import('../js/game-core.js'));
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
  });

  const game = (id, name = id) => ({
    store: 'steam',
    id,
    name,
    library_image: 'x.jpg',
  });

  it('returns empty when library has not been seeded', () => {
    state.prefs.librarySeenSeeded = false;
    state.libraryFirstSeenByKey = { 'steam:1': Date.now() };
    expect(computeRecentAdditions([game('1')])).toEqual([]);
  });

  it('orders by _addedAt descending and caps at 10', () => {
    const games = [];
    const now = Date.now();
    for (let i = 0; i < 12; i++) {
      const g = game(String(i), `Game ${i}`);
      state.libraryFirstSeenByKey[gameKey(g)] = now - i * 1000;
      games.push(g);
    }
    const result = computeRecentAdditions(games, 10);
    expect(result).toHaveLength(10);
    expect(result[0].name).toBe('Game 0');
    expect(result[9].name).toBe('Game 9');
    for (const g of result) {
      expect(g._addedAt).toBeGreaterThan(0);
    }
    expect(result[0]._addedAt).toBeGreaterThan(result[1]._addedAt);
  });

  it('backfills from baseline library when fewer than cap have timestamps', () => {
    const now = Date.now();
    const games = [];
    for (let i = 0; i < 12; i++) {
      const g = game(String(i), `Game ${i}`);
      state.libraryFirstSeenByKey[gameKey(g)] = i < 2 ? now - i * 1000 : 0;
      games.push(g);
    }
    const result = computeRecentAdditions(games, 10);
    expect(result).toHaveLength(10);
    expect(result[0].id).toBe('0');
    expect(result[1].id).toBe('1');
    expect(result.filter(g => g._addedAt > 0)).toHaveLength(2);
    expect(result.filter(g => g._addedAt === 0)).toHaveLength(8);
  });
});
