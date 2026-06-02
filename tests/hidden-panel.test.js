import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { listUserHiddenEntries, setPersonalByKey } from '../js/personal-storage.js';
import { PRE_HIDDEN_KEYS } from '../js/hidden-defaults.js';

beforeEach(() => {
  state.personal = {};
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  window._dataVersion = 0;
});

describe('listUserHiddenEntries orphan fallback', () => {
  it('returns orphan hidden keys with fallback name from PRE_HIDDEN_KEYS', () => {
    const { key, name, store } = PRE_HIDDEN_KEYS[0];
    setPersonalByKey(key, 'hidden', true, { silent: true });
    const list = listUserHiddenEntries();
    expect(list).toHaveLength(1);
    expect(list[0].key).toBe(key);
    expect(list[0].game).toBeNull();
    expect(list[0].fallbackName).toBe(name);
    expect(list[0].fallbackStore).toBe(store);
  });
});
