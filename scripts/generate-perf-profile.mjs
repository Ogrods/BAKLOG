#!/usr/bin/env node
/**
 * Generate tests/fixtures/perf-profile/ for Playwright perf audits.
 * Run: node scripts/generate-perf-profile.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  itchCatalogPayload,
  steamCatalogPayload,
  syntheticWishlistGames,
} from '../tests/fixtures/synthetic-games.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const fixtureRoot = path.join(root, 'tests', 'fixtures', 'perf-profile');
const perfDir = path.join(fixtureRoot, 'perf');

const SIZES = [
  { name: 'empty', count: 0 },
  { name: '100', count: 100 },
  { name: '500', count: 500 },
  { name: '2000', count: 2000 },
];

function writeJson(rel, data) {
  const p = path.join(fixtureRoot, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
}

fs.mkdirSync(path.join(perfDir, 'data'), { recursive: true });
fs.mkdirSync(path.join(perfDir, 'cache', 'auth'), { recursive: true });

writeJson('index.json', {
  active: 'perf',
  profiles: [
    { id: 'perf', label: 'Perf benchmark', created_at: '2026-06-25T00:00:00.000Z' },
  ],
});

writeJson('perf/data/personal.json', { personal: {} });
writeJson('perf/free_claims.json', { items: [], attribution: { sources: [] } });

for (const { name, count } of SIZES) {
  writeJson(`perf/games_steam-${name}.json`, steamCatalogPayload(count));
}

// Default active catalog: 500 rows (balance for local + CI e2e).
writeJson('perf/games_steam.json', steamCatalogPayload(500));
writeJson('perf/games_wishlist.json', {
  game_count: 20,
  games: syntheticWishlistGames(20),
});
writeJson('perf/games_itch.json', itchCatalogPayload(12));

// Empty stubs for other stores merge path expects.
for (const store of [
  'gog', 'psn', 'epic', 'amazon', 'nintendo', 'xbox', 'battlenet', 'ubisoft', 'humble', 'ea',
]) {
  writeJson(`perf/games_${store}.json`, { game_count: 0, games: [] });
}

console.log(`Wrote perf profile fixture under ${path.relative(root, fixtureRoot)}`);
