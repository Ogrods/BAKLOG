import { describe, it, expect, beforeEach, vi } from 'vitest';

let state;
let countHiddenLibraryNoiseGames;
let setGameHidden;
let tagNoiseRow;

const game = { store: 'epic', id: 1, name: 'YouTube', tags: [] };
const real = { store: 'steam', id: 2, name: 'Hades', tags: [] };

beforeEach(async () => {
  vi.resetModules();
  ({ state } = await import('../js/state.js'));
  ({ countHiddenLibraryNoiseGames, setGameHidden } = await import('../js/personal-storage.js'));
  ({ tagNoiseRow } = await import('../js/library-noise.js'));
  state.personal = {};
  state.allGames = [game, real];
});

describe('countHiddenLibraryNoiseGames', () => {
  it('counts hidden library noise rows only', () => {
    tagNoiseRow(game);
    setGameHidden(game, true, { silent: true });
    setGameHidden(real, true, { silent: true });
    expect(countHiddenLibraryNoiseGames(state.allGames)).toBe(1);
  });
});
