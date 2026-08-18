import { describe, expect, it } from 'vitest';
import { itchCatalogPayload, syntheticItchGames } from './fixtures/synthetic-games.js';

describe('syntheticItchGames', () => {
  it('emits itch store rows, not steam-shaped catalog', () => {
    const games = syntheticItchGames(12);
    expect(games).toHaveLength(12);
    expect(games.every((g) => g.store === 'itch')).toBe(true);
    expect(games.every((g) => g.type === 'game')).toBe(true);
    expect(games.some((g) => g.store === 'steam')).toBe(false);
    const payload = itchCatalogPayload(12);
    expect(payload.game_count).toBe(12);
    expect(payload.games[0].store).toBe('itch');
  });
});
