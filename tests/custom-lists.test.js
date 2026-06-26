import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

describe('custom-lists', () => {
  let state;
  let mod;

  beforeEach(async () => {
    vi.resetModules();
    ({ state } = await import('../js/state.js'));
    state.prefs = {};
    state.allGames = [
      { store: 'steam', id: '1', name: 'Alpha' },
      { store: 'steam', id: '2', name: 'Beta' },
    ];
    state.wishlistGames = [];
    state.itchGames = [];
    mod = await import('../js/custom-lists.js');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('migrateCustomLists ensures three slots with defaults', () => {
    const lists = mod.migrateCustomLists({ customLists: [{ name: 'Co-op', keys: ['steam:1'] }] });
    expect(lists).toHaveLength(3);
    expect(lists[0].name).toBe('Co-op');
    expect(lists[0].keys).toEqual(['steam:1']);
    expect(lists[1].keys).toEqual([]);
    expect(lists[2].name).toBe('List 3');
  });

  it('addKeysToCustomList skips dupes and enforces cap', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    const cap = mod.CUSTOM_LIST_MAX_KEYS;
    const keys = Array.from({ length: cap + 2 }, (_, i) => `steam:${i}`);
    const { added, skippedFull } = mod.addKeysToCustomList(0, keys);
    expect(added).toBe(cap);
    expect(skippedFull).toBe(2);
    const again = mod.addKeysToCustomList(0, ['steam:1']);
    expect(again.added).toBe(0);
    expect(mod.getCustomLists()[0].keys).toHaveLength(cap);
  });

  it('moveCustomListKey reorders within list', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    state.prefs.customLists[0].keys = ['steam:1', 'steam:2'];
    mod.moveCustomListKey(0, 'steam:2', -1);
    expect(mod.getCustomLists()[0].keys).toEqual(['steam:2', 'steam:1']);
  });

  it('moveCustomListKeyToIndex moves key to absolute slot', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    state.prefs.customLists[0].keys = ['steam:1', 'steam:2', 'steam:3'];
    mod.moveCustomListKeyToIndex(0, 'steam:3', 0);
    expect(mod.getCustomLists()[0].keys).toEqual(['steam:3', 'steam:1', 'steam:2']);
    mod.moveCustomListKeyToIndex(0, 'steam:3', 2);
    expect(mod.getCustomLists()[0].keys).toEqual(['steam:1', 'steam:2', 'steam:3']);
  });

  it('resolveCustomListGames preserves order and skips orphans', () => {
    const games = mod.resolveCustomListGames({ keys: ['steam:2', 'missing:9', 'steam:1'] });
    expect(games.map(g => g.name)).toEqual(['Beta', 'Alpha']);
  });

  it('resolveCustomListGames still resolves library-noise-tagged catalog rows', () => {
    state.allGames.push({ store: 'epic', id: '9', name: 'YouTube', tags: ['noise'] });
    const games = mod.resolveCustomListGames({ keys: ['epic:9'] });
    expect(games).toHaveLength(1);
    expect(games[0].name).toBe('YouTube');
  });

  it('shouldShowCustomListTab when renamed or has resolvable game', () => {
    expect(mod.shouldShowCustomListTab({ name: 'List 1', keys: [] }, 0)).toBe(false);
    expect(mod.shouldShowCustomListTab({ name: 'RPG queue', keys: [] }, 0)).toBe(true);
    expect(mod.shouldShowCustomListTab({ name: 'List 1', keys: ['steam:1'] }, 0)).toBe(true);
    expect(mod.shouldShowCustomListTab({ name: 'List 1', keys: ['missing:1'] }, 0)).toBe(false);
  });

  it('pruneOrphanKeys strips missing catalog entries', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    state.prefs.customLists[0].keys = ['steam:1', 'gone:1'];
    const removed = mod.pruneOrphanKeys(0);
    expect(removed).toBe(1);
    expect(mod.getCustomLists()[0].keys).toEqual(['steam:1']);
  });

  it('parseCustomListTabId recognizes custom tabs', () => {
    expect(mod.parseCustomListTabId('customList0')).toBe(0);
    expect(mod.parseCustomListTabId('customList2')).toBe(2);
    expect(mod.parseCustomListTabId('topRated')).toBe(-1);
  });

  it('resolveLibraryPicksTab falls back when custom tab is hidden', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    state.prefs.customLists[0].keys = [];
    expect(mod.resolveLibraryPicksTab('customList0', 'topRated')).toBe('topRated');
    state.prefs.customLists[0].name = 'Queue';
    expect(mod.resolveLibraryPicksTab('customList0', 'topRated')).toBe('customList0');
    state.prefs.customLists[0].keys = ['steam:1'];
    state.prefs.customLists[0].name = 'List 1';
    expect(mod.resolveLibraryPicksTab('customList0', 'quickWins')).toBe('customList0');
  });

  it('getCustomLists normalizes partial server prefs', () => {
    state.prefs.customLists = [{ name: 'Solo', keys: ['steam:1'] }];
    const lists = mod.getCustomLists();
    expect(lists).toHaveLength(3);
    expect(lists[0].name).toBe('Solo');
    expect(lists[1].keys).toEqual([]);
  });

  it('removeKeysFromCustomList removes multiple keys', () => {
    state.prefs.customLists = mod.defaultCustomLists();
    state.prefs.customLists[0].keys = ['steam:1', 'steam:2'];
    expect(mod.removeKeysFromCustomList(0, ['steam:1', 'steam:2'])).toBe(2);
    expect(mod.getCustomLists()[0].keys).toEqual([]);
  });
});
