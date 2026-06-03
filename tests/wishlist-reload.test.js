/** reloadAllWishlistStoreFiles — bulk reload after ITAD FX / HLTB on wishlist. */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import {
  WISHLIST_FETCHER_JSON,
  WISHLIST_FETCHER_META_KEY,
} from '../js/fetcher-registry.js';

describe('reloadAllWishlistStoreFiles', () => {
  let state;
  let reloadAllWishlistStoreFiles;

  beforeEach(async () => {
    vi.resetModules();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url).split('?')[0];
        const file = path.replace(/^\//, '');
        const payload = {
          games: [{ id: `id-${file}`, name: `Game from ${file}`, store: 'wishlist' }],
        };
        return {
          ok: true,
          json: async () => payload,
        };
      }),
    );
    ({ state } = await import('../js/state.js'));
    ({ reloadAllWishlistStoreFiles } = await import('../js/library-load.js'));
    state.libraryMeta = {};
    state.wishlistGames = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('loads every wishlist catalog into libraryMeta and rebuilds wishlistGames', async () => {
    await reloadAllWishlistStoreFiles();

    for (const [fetcherKey, file] of Object.entries(WISHLIST_FETCHER_JSON)) {
      const metaKey = WISHLIST_FETCHER_META_KEY[fetcherKey];
      expect(state.libraryMeta[metaKey]?.games?.[0]?.name).toBe(`Game from ${file}`);
    }

    expect(state.wishlistGames.length).toBe(Object.keys(WISHLIST_FETCHER_JSON).length);
    expect(
      state.wishlistGames.some((g) => g.name === 'Game from games_wishlist.json'),
    ).toBe(true);
  });

  it('keeps cached meta when a fetch fails', async () => {
    state.libraryMeta.wishlist = {
      games: [{ id: 'cached', name: 'Cached Steam WL', appid: 1 }],
    };
    vi.mocked(fetch).mockImplementation(async (url) => {
      const path = String(url).split('?')[0];
      if (path.includes('games_wishlist.json')) {
        throw new Error('network');
      }
      const file = path.replace(/^\//, '');
      return {
        ok: true,
        json: async () => ({
          games: [{ id: `id-${file}`, name: `Game from ${file}` }],
        }),
      };
    });

    await reloadAllWishlistStoreFiles();

    expect(state.libraryMeta.wishlist.games[0].name).toBe('Cached Steam WL');
    expect(state.wishlistGames.some((g) => g.name === 'Cached Steam WL')).toBe(true);
  });
});
