/** Stale catalog reloads must not clobber a newer generation. */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import {
  WISHLIST_FETCHER_JSON,
  WISHLIST_FETCHER_META_KEY,
} from '../js/fetcher-registry.js';

describe('library load generation', () => {
  let state;
  let reloadAllWishlistStoreFiles;
  let _resetLoadGenerationForTests;
  let _beginLoadGenerationForTests;
  let _isStaleLoadForTests;

  beforeEach(async () => {
    vi.resetModules();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        const path = String(url).split('?')[0];
        const file = path.replace(/^\//, '');
        return {
          ok: true,
          json: async () => ({
            games: [{ id: `id-${file}`, name: `Game from ${file}` }],
          }),
        };
      }),
    );
    ({ state } = await import('../js/state.js'));
    ({
      reloadAllWishlistStoreFiles,
      _resetLoadGenerationForTests,
      _beginLoadGenerationForTests,
      _isStaleLoadForTests,
    } = await import('../js/library-load.js'));
    _resetLoadGenerationForTests();
    state.libraryMeta = {};
    state.wishlistGames = [];
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('marks older generations stale after a newer begin', () => {
    const older = _beginLoadGenerationForTests();
    const newer = _beginLoadGenerationForTests();
    expect(_isStaleLoadForTests(older)).toBe(true);
    expect(_isStaleLoadForTests(newer)).toBe(false);
  });

  it('stale loadGen skips meta writes in reloadAllWishlistStoreFiles', async () => {
    const stale = _beginLoadGenerationForTests();
    _beginLoadGenerationForTests();
    await reloadAllWishlistStoreFiles(stale);
    for (const metaKey of Object.values(WISHLIST_FETCHER_META_KEY)) {
      expect(state.libraryMeta[metaKey]).toBeUndefined();
    }
  });

  it('current loadGen applies wishlist preserve writes', async () => {
    const gen = _beginLoadGenerationForTests();
    await reloadAllWishlistStoreFiles(gen);
    for (const [fetcherKey, file] of Object.entries(WISHLIST_FETCHER_JSON)) {
      const metaKey = WISHLIST_FETCHER_META_KEY[fetcherKey];
      expect(state.libraryMeta[metaKey]?.games?.[0]?.name).toBe(`Game from ${file}`);
    }
  });
});
