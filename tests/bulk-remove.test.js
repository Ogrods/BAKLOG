import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  addManualGame,
  loadManualGames,
  removeManualGame,
  setPersonal,
} from '../js/personal-storage.js';
import { gameKey } from '../js/game-core.js';

const manual = { store: 'steam', id: 'manual-x', name: 'Custom Game', manual: true, playtime_minutes: 0 };

beforeEach(() => {
  state.personal = {};
  localStorage.clear();
  window._dataVersion = 0;
});

describe('bulkRemove custom row cleanup', () => {
  it('deletes manual game and its personal entry (same pattern as bulkRemove)', () => {
    addManualGame(manual);
    setPersonal(manual, 'status', 'next', { silent: true });
    setPersonal(manual, 'notes', 'test note', { silent: true });
    const key = gameKey(manual);
    removeManualGame(manual.store, manual.id);
    delete state.personal[key];
    expect(loadManualGames()).toHaveLength(0);
    expect(state.personal[key]).toBeUndefined();
  });
});
