import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import {
  setAuthStatusSnapshot,
  visibleItchGames,
  isItchTabAvailable,
  hasCachedItchLibrary,
} from '../js/connections-status.js';

describe('connections-status itch cache', () => {
  beforeEach(() => {
    state.itchGames = [];
    state.libraryMeta = state.libraryMeta || {};
    state.libraryMeta.itch = null;
    setAuthStatusSnapshot([
      { key: 'itch', status: 'disconnected' },
      { key: 'itch_local', status: 'disconnected' },
    ]);
  });

  it('keeps cached itch rows visible when disconnected', () => {
    state.itchGames = [{ store: 'itch', id: '1', name: 'Cached Game' }];
    expect(hasCachedItchLibrary()).toBe(true);
    expect(isItchTabAvailable()).toBe(true);
    expect(visibleItchGames()).toHaveLength(1);
  });

  it('hides itch tab when disconnected and no cached library', () => {
    expect(hasCachedItchLibrary()).toBe(false);
    expect(isItchTabAvailable()).toBe(false);
    expect(visibleItchGames()).toHaveLength(0);
  });
});
