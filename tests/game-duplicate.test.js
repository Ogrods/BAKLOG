import { describe, expect, it, beforeEach } from 'vitest';
import { state } from '../js/state.js';
import { findDuplicateMatch, duplicateMatchKey } from '../js/game-duplicate.js';
import { gameKey } from '../js/game-core.js';
import { setGameHidden } from '../js/personal-storage.js';

beforeEach(() => {
  state.personal = {};
  state.allGames = [
    { store: 'steam', id: 1, name: 'Hades', playtime_minutes: 100, steam_review_percent: 98 },
    { store: 'gog', id: 'hades-gog', name: 'Hades II', playtime_minutes: 0 },
  ];
  state.wishlistGames = [
    { store: 'wishlist', id: 'wish-2', name: 'Hades', wishlist_store: 'steam', manual: true },
  ];
  state.itchGames = [
    { store: 'itch', id: 'itch-1', name: 'Celeste Clone', playtime_minutes: 0 },
  ];
});

describe('findDuplicateMatch', () => {
  it('finds a library title by normalized name', () => {
    const m = findDuplicateMatch('Hades', 'library');
    expect(m).toBeTruthy();
    expect(m.store).toBe('steam');
  });

  it('prefers higher scoreEntry when multiple stores match', () => {
    state.allGames.push({ store: 'epic', id: 'x', name: 'Hades', playtime_minutes: 0 });
    const m = findDuplicateMatch('Hades', 'library');
    expect(gameKey(m)).toBe('steam:1');
  });

  it('matches wishlist catalog separately', () => {
    const m = findDuplicateMatch('Hades', 'wishlist');
    expect(m).toBeTruthy();
    expect(m.store).toBe('wishlist');
  });

  it('returns null when no title match', () => {
    expect(findDuplicateMatch('Stardew Valley', 'library')).toBeNull();
  });

  it('excludes hidden matches by default', () => {
    setGameHidden(state.allGames[0], true, { silent: true });
    expect(findDuplicateMatch('Hades', 'library')).toBeNull();
  });

  it('includes hidden matches when includeHidden is true', () => {
    setGameHidden(state.allGames[0], true, { silent: true });
    const m = findDuplicateMatch('Hades', 'library', { includeHidden: true });
    expect(m).toBeTruthy();
    expect(gameKey(m)).toBe('steam:1');
  });

  it('matches itch catalog when targetView is itch', () => {
    const m = findDuplicateMatch('Celeste Clone', 'itch');
    expect(m).toBeTruthy();
    expect(m.store).toBe('itch');
  });
});

describe('duplicateMatchKey', () => {
  it('returns gameKey for a match', () => {
    const m = findDuplicateMatch('Hades', 'library');
    expect(duplicateMatchKey(m)).toBe('steam:1');
  });
});
