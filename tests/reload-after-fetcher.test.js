/** reloadAfterFetcher routing + enrich cache reload parity. */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
  ENRICH_FETCHER_KEYS,
  ENRICH_RELOAD_WISHLIST_KEYS,
  LIBRARY_STORE_JSON,
  WISHLIST_FETCHER_JSON,
} from '../js/fetcher-registry.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const LIBRARY_LOAD_SRC = readFileSync(
  join(__dirname, '..', 'js', 'library-load.js'),
  'utf8',
);

const ENRICH_CACHE_LOADERS = {
  hltb: 'loadHltbCache',
  steamReviews: 'loadSteamReviewCache',
  steamCovers: 'loadSteamCoversMeta',
  steamTags: 'loadSteamTagsMeta',
  protondb: 'loadProtondbCache',
};

function enrichBranchSource() {
  const m = LIBRARY_LOAD_SRC.match(
    /ENRICH_FETCHER_KEYS\.has\(key\)\)\s*\{([\s\S]*?)\} else if \(key === 'claims'\)/,
  );
  return m ? m[1] : '';
}

describe('reloadAfterFetcher source routing', () => {
  it('calls a cache loader for every enrich fetcher key', () => {
    const branch = enrichBranchSource();
    expect(branch.length).toBeGreaterThan(0);
    for (const key of ENRICH_FETCHER_KEYS) {
      const fn = ENRICH_CACHE_LOADERS[key];
      expect(fn, `missing loader map for ${key}`).toBeTruthy();
      expect(branch, `${key} should invoke ${fn}()`).toContain(`${fn}()`);
    }
  });

  it('always reloads library catalogs for enrich keys', () => {
    const branch = enrichBranchSource();
    expect(branch).toContain('reloadAllLibraryStoreFiles');
  });

  it('reloads wishlist catalogs only for enrich keys that mutate wishlist JSON', () => {
    const branch = enrichBranchSource();
    expect(branch).toContain('ENRICH_RELOAD_WISHLIST_KEYS.has(key)');
    for (const key of ENRICH_RELOAD_WISHLIST_KEYS) {
      expect(ENRICH_FETCHER_KEYS.has(key), `${key} in ENRICH_FETCHER_KEYS`).toBe(true);
    }
    const wishlistOnly = [...ENRICH_FETCHER_KEYS].filter((k) => !ENRICH_RELOAD_WISHLIST_KEYS.has(k));
    expect(wishlistOnly.sort()).toEqual(['protondb', 'steamReviews', 'steamTags'].sort());
  });

  it('refreshLibraryChromeAfterMerge does not double-paint summary/picks', () => {
    const fn = LIBRARY_LOAD_SRC.match(
      /async function refreshLibraryChromeAfterMerge\(\)\s*\{([\s\S]*?)^\}/m,
    );
    expect(fn, 'refreshLibraryChromeAfterMerge').toBeTruthy();
    const body = fn[1];
    expect(body).not.toMatch(/renderSummary\(\)[\s\S]*refreshFilterUI/);
    expect(body).not.toMatch(/renderPicks\(\)[\s\S]*refreshFilterUI/);
    expect(body).toContain('refreshFilterUI({ force: true })');
  });

  it('always ends in applyMergedLibrary for mapped branches', () => {
    expect(LIBRARY_LOAD_SRC).toContain('await applyMergedLibrary()');
    expect(LIBRARY_LOAD_SRC).toMatch(
      /reloadAfterFetcher\(key\)[\s\S]*await applyMergedLibrary\(\)/,
    );
  });
});

describe('manifest key coverage', () => {
  it('every library manifest key maps to LIBRARY_STORE_JSON', () => {
    const manifest = JSON.parse(
      readFileSync(join(__dirname, '..', 'fetchers', 'manifest.json'), 'utf8'),
    );
    const libKeys = manifest.fetchers.filter((f) => f.group === 'library').map((f) => f.key);
    for (const key of libKeys) {
      expect(LIBRARY_STORE_JSON[key], `library key ${key}`).toBeTruthy();
    }
  });

  it('every wishlist manifest key maps to WISHLIST_FETCHER_JSON', () => {
    const manifest = JSON.parse(
      readFileSync(join(__dirname, '..', 'fetchers', 'manifest.json'), 'utf8'),
    );
    const wlKeys = manifest.fetchers.filter((f) => f.group === 'wishlist').map((f) => f.key);
    for (const key of wlKeys) {
      expect(WISHLIST_FETCHER_JSON[key], `wishlist key ${key}`).toBeTruthy();
    }
  });
});
