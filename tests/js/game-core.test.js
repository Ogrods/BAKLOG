import { describe, expect, it } from 'vitest';
import { gameKey, normalizeGame } from '../../js/game-core.js';

describe('game-core', () => {
  it('builds stable keys', () => {
    const g = normalizeGame({ appid: 570, name: 'Dota 2' });
    expect(g.store).toBe('steam');
    expect(gameKey(g)).toBe('steam:570');
  });
});
