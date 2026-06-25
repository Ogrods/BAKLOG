import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  addNintendoDroppedId,
  removeNintendoDroppedId,
  loadNintendoDroppedIds,
  NINTENDO_DROPPED_KEY,
  setGameHidden,
} from '../js/personal-storage.js';
import { gameKey } from '../js/game-core.js';

const nintendoGame = {
  store: 'nintendo',
  id: 'tx-100',
  nintendo_id: 'tx-100',
  name: 'Old eShop Title',
};

beforeEach(() => {
  state.personal = {};
  state.allGames = [nintendoGame];
  state.selectedKeys = new Set();
  window._dataVersion = 0;
});

describe('nintendo dropped ids', () => {
  it('addNintendoDroppedId persists to personal meta', () => {
    expect(loadNintendoDroppedIds().size).toBe(0);
    addNintendoDroppedId('tx-100');
    expect(state.personal[NINTENDO_DROPPED_KEY]).toEqual(['tx-100']);
    expect(loadNintendoDroppedIds().has('tx-100')).toBe(true);
  });

  it('removeNintendoDroppedId clears an id', () => {
    addNintendoDroppedId('tx-100');
    expect(removeNintendoDroppedId('tx-100')).toBe(true);
    expect(loadNintendoDroppedIds().size).toBe(0);
  });

  it('bulk remove wiring adds dropped id for Nintendo rows', () => {
    addNintendoDroppedId(nintendoGame.nintendo_id ?? nintendoGame.id, { silent: true });
    setGameHidden(nintendoGame, true, { silent: true });
    expect(loadNintendoDroppedIds().has('tx-100')).toBe(true);
    expect(state.personal[gameKey(nintendoGame)]?.hidden).toBe(true);
  });

  it('restore clears dropped id when unhiding Nintendo game', () => {
    addNintendoDroppedId('tx-100');
    setGameHidden(nintendoGame, true, { silent: true });
    removeNintendoDroppedId('tx-100', { silent: true });
    setGameHidden(nintendoGame, false, { silent: true });
    expect(loadNintendoDroppedIds().has('tx-100')).toBe(false);
  });
});
