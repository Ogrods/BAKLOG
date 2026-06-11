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

  const game = (id, name = id, extra = {}) => ({
    store: 'steam',
    id,
    name,
    library_image: 'x.jpg',
    ...extra,
  });

  it('returns empty when library has no games', () => {
    expect(computeRecentAdditions([])).toEqual([]);
  });

  it('orders tracked additions by _addedAt descending and caps at 10', () => {
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

  it('backfills to cap when fewer than cap tracked additions exist', () => {
    const now = Date.now();
    const games = [];
    for (let i = 0; i < 12; i++) {
      const g = game(String(i), `Game ${i}`, { last_played: 1700000000 + i });
      state.libraryFirstSeenByKey[gameKey(g)] = i < 2 ? now - i * 1000 : 0;
      games.push(g);
    }
    const result = computeRecentAdditions(games, 10);
    expect(result).toHaveLength(10);
    expect(result[0].id).toBe('0');
    expect(result[1].id).toBe('1');
    expect(result[0]._addedAt).toBeGreaterThan(0);
    expect(result[1]._addedAt).toBeGreaterThan(0);
    // Backfilled rows ordered by last_played have no true add date.
    expect(result[2]._addedAt).toBeNull();
    expect(result[9]._addedAt).toBeNull();
  });

  it('fills from baseline library using proxy order when all first-seen are 0', () => {
    const games = [
      game('a', 'Alpha', { release_date: '2020-01-01' }),
      game('b', 'Bravo', { last_played: 1700000100 }),
      game('c', 'Charlie', { added_at: '2024-06-01T12:00:00.000Z' }),
      game('d', 'Delta', { release_date: '2023-06-01' }),
    ];
    for (const g of games) {
      state.libraryFirstSeenByKey[gameKey(g)] = 0;
    }
    const result = computeRecentAdditions(games, 10);
    expect(result.map(g => g.id)).toEqual(['c', 'b', 'd', 'a']);
    expect(result[0]._addedAt).toBe(Date.parse('2024-06-01T12:00:00.000Z'));
    expect(result[1]._addedAt).toBeNull();
    expect(result[2]._addedAt).toBeNull();
    expect(result[3]._addedAt).toBeNull();
  });

  it('backfills using ISO last_played dates, not only epoch seconds', () => {
    // The spotlight last_played parser used to ignore ISO strings (Number(ISO)
    // is NaN), so an ISO-dated row sorted as "no signal". The shared parser
    // now handles both, so the recently-played ISO row leads the backfill.
    const games = [
      game('a', 'Alpha', { release_date: '2010-01-01' }),
      game('b', 'Bravo', { last_played: new Date('2024-06-01T00:00:00.000Z').toISOString() }),
    ];
    for (const g of games) state.libraryFirstSeenByKey[gameKey(g)] = 0;
    const result = computeRecentAdditions(games, 10);
    expect(result.map(g => g.id)).toEqual(['b', 'a']);
  });

  it('prefers tracked first-seen over backfill proxies', () => {
    const tracked = game('t', 'Tracked', { last_played: 1 });
    const manual = game('m', 'Manual', { added_at: '2025-01-01T00:00:00.000Z' });
    state.libraryFirstSeenByKey[gameKey(tracked)] = Date.now();
    state.libraryFirstSeenByKey[gameKey(manual)] = 0;
    const result = computeRecentAdditions([manual, tracked], 10);
    expect(result[0].id).toBe('t');
    expect(result[1].id).toBe('m');
  });
});
