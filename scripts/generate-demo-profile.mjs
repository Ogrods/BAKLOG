#!/usr/bin/env node
/**
 * Generate a fictional demo library used for README + social screenshots.
 * Titles and cover art are invented (same sample universe as the landing demo),
 * so captures never ship a real user's library.
 *
 * Writes into an isolated BAKLOG_DATA_DIR root, never the live profiles/ dir:
 *   node scripts/generate-demo-profile.mjs [--data-dir <path>]
 * Then: pwsh scripts/capture-screenshots.ps1
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const argIdx = process.argv.indexOf('--data-dir');
const dataDir = path.resolve(
  argIdx > -1 && process.argv[argIdx + 1]
    ? process.argv[argIdx + 1]
    : path.join(os.tmpdir(), 'baklog-demo-data'),
);
const profileRoot = path.join(dataDir, 'profiles', 'demo');

// Fictional headliners paired with the sample cover art already in the repo.
const HEADLINERS = [
  { name: 'Ironveil', cover: '/assets/game-covers/ironveil-cover.png', genres: ['RPG', 'Adventure'], hltb: 46 },
  { name: 'Hollowmaw', cover: '/assets/game-covers/hollowmaw-cover.png', genres: ['Action', 'Metroidvania'], hltb: 22 },
  { name: 'Apex Velocity', cover: '/assets/game-covers/apex-velocity-cover.png', genres: ['Racing', 'Sports'], hltb: 12 },
  { name: 'Ashlight Saga', cover: '/assets/game-covers/ashlight-saga-cover.png', genres: ['RPG', 'Strategy'], hltb: 68 },
  { name: 'Skybreaker Squadron', cover: '/assets/game-covers/skybreaker-squadron-cover.png', genres: ['Action', 'Simulation'], hltb: 18 },
  { name: 'Gridiron Kings', cover: '/assets/game-covers/gridiron-kings-cover.png', genres: ['Sports', 'Simulation'], hltb: 30 },
  { name: 'Zephyr Edge', cover: '/assets/ads-sample/cover-zephyr-edge.webp', genres: ['Action', 'Indie'], hltb: 9 },
  { name: 'Encore', cover: '/assets/ads-sample/cover-encore.webp', genres: ['Rhythm', 'Indie'], hltb: 6 },
  { name: 'Emberfall', cover: '/assets/ads-sample/hero-emberfall.webp', genres: ['Adventure', 'Open World'], hltb: 52 },
  { name: 'Dawnbanner', cover: '/assets/ads-sample/hero-dawnbanner.webp', genres: ['Strategy', 'RPG'], hltb: 40 },
  { name: 'Rustbloom', cover: '/assets/ads-sample/hero-rustbloom.webp', genres: ['Survival', 'Indie'], hltb: 27 },
  { name: 'Tidewright', cover: '/assets/ads-sample/hero-tidewright.webp', genres: ['Puzzle', 'Adventure'], hltb: 11 },
];

// Two-word filler titles: plausible on screen, obviously not a real catalog,
// and numerous enough that cross-store dedup never collapses the library.
const TITLE_HEADS = [
  'Ashen', 'Ember', 'Iron', 'Hollow', 'Neon', 'Storm', 'Tide', 'Vault',
  'Cinder', 'Gilded', 'Frost', 'Rust', 'Solar', 'Umbra', 'Verdant', 'Zephyr',
  'Copper', 'Lumen', 'Onyx', 'Pale', 'Quartz', 'Salt', 'Thorn', 'Wake',
];
const TITLE_TAILS = [
  'Vale', 'Reach', 'Signal', 'Circuit', 'Drift', 'Requiem', 'Bastion', 'Harbor',
  'Kings', 'Legacy', 'Crown', 'Descent', 'Horizon', 'Engine', 'Covenant', 'Ridge',
  'Spire', 'Voyage', 'Quarry', 'Anthem', 'Foundry', 'Hollow', 'Ledger', 'Mire',
];
const EDITIONS = ['', ' II', ' III', ': Afterlight', ': Ashfall', ': Remastered', ' Redux', ': Tidal Cut'];
// Steam review buckets the status chart reads (js/dashboard-charts.js).
const REVIEW_DESCS = [
  'Overwhelmingly Positive', 'Very Positive', 'Very Positive',
  'Mostly Positive', 'Mostly Positive', 'Mixed', 'Mostly Negative',
];
const GENRES = ['Action', 'RPG', 'Strategy', 'Indie', 'Adventure', 'Simulation', 'Puzzle', 'Racing'];
const TAGS = ['Singleplayer', 'Multiplayer', 'Co-op', 'Story Rich', 'Open World', 'Roguelike'];
const STATUSES = ['backlog', 'backlog', 'backlog', 'next', 'playing', 'finished', 'skip'];

// Store mix mirrors a plausible multi-store collector: Steam heavy, long tail.
const STORE_MIX = [
  { store: 'steam', file: 'games_steam.json', count: 268 },
  { store: 'gog', file: 'games_gog.json', count: 61 },
  { store: 'epic', file: 'games_epic.json', count: 48 },
  { store: 'amazon', file: 'games_amazon.json', count: 34 },
  { store: 'itch', file: 'games_itch.json', count: 26 },
  { store: 'xbox', file: 'games_xbox.json', count: 19 },
  { store: 'humble', file: 'games_humble.json', count: 14 },
  { store: 'battlenet', file: 'games_battlenet.json', count: 7 },
  { store: 'ubisoft', file: 'games_ubisoft.json', count: 6 },
  { store: 'ea', file: 'games_ea.json', count: 5 },
  { store: 'psn', file: 'games_psn.json', count: 9 },
  { store: 'nintendo', file: 'games_nintendo.json', count: 8 },
];

// Deterministic pseudo-random so re-runs produce the same screenshots.
let seed = 20260801;
function rnd() {
  seed = (seed * 1103515245 + 12345) & 0x7fffffff;
  return seed / 0x7fffffff;
}
function pick(list) {
  return list[Math.floor(rnd() * list.length)];
}
function int(min, max) {
  return min + Math.floor(rnd() * (max - min + 1));
}

function writeJson(rel, data) {
  const file = path.join(profileRoot, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
}

function isoDaysAgo(days) {
  return new Date(Date.now() - days * 86400000).toISOString();
}

let nextId = 41000;
const personal = {};
const allRows = [];

// Every row gets art from the sample pool so grid tiles never fall back to
// initials placeholders in a screenshot.
const COVER_POOL = HEADLINERS.map((h) => h.cover);
const usedTitles = new Set();
function fillerTitle() {
  for (let attempt = 0; attempt < 400; attempt += 1) {
    const name = `${pick(TITLE_HEADS)} ${pick(TITLE_TAILS)}${pick(EDITIONS)}`;
    if (!usedTitles.has(name)) {
      usedTitles.add(name);
      return name;
    }
  }
  return `${pick(TITLE_HEADS)} ${pick(TITLE_TAILS)} ${usedTitles.size}`;
}

function buildGame(store, index) {
  const id = String((nextId += 1));
  const headliner = index < HEADLINERS.length ? HEADLINERS[index] : null;
  const name = headliner ? headliner.name : fillerTitle();
  const status = headliner && index < 4 ? 'playing' : pick(STATUSES);
  const played = status === 'finished' ? int(400, 5400) : status === 'playing' ? int(60, 900) : pick([0, 0, int(15, 240)]);
  const cover = headliner ? headliner.cover : COVER_POOL[allRows.length % COVER_POOL.length];
  const row = {
    store,
    id,
    appid: store === 'steam' ? Number(id) : undefined,
    name,
    library_image: cover,
    header_image: cover,
    playtime_minutes: played,
    steam_review_percent: int(58, 97),
    steam_review_desc: pick(REVIEW_DESCS),
    steam_review_count: int(180, 42000),
    hltb_main_hours: headliner ? headliner.hltb : int(4, 70),
    release_date: `20${String(int(11, 25)).padStart(2, '0')}-${String(int(1, 12)).padStart(2, '0')}-${String(int(1, 28)).padStart(2, '0')}`,
    genres: headliner ? headliner.genres : [pick(GENRES), pick(GENRES)],
    tags: [pick(TAGS), pick(TAGS)],
    added_at: isoDaysAgo(int(3, 1600)),
  };
  for (const key of Object.keys(row)) if (row[key] === undefined) delete row[key];
  personal[`${store}:${id}`] = { status, updated_at: isoDaysAgo(int(1, 300)) };
  allRows.push(row);
  return row;
}

fs.rmSync(profileRoot, { recursive: true, force: true });
fs.mkdirSync(path.join(profileRoot, 'cache', 'auth'), { recursive: true });

let headlinerCursor = 0;
for (const { store, file, count } of STORE_MIX) {
  const games = [];
  for (let i = 0; i < count; i += 1) {
    // Spread the art-backed headliners across the first few stores.
    const idx = store === 'steam' && headlinerCursor < HEADLINERS.length ? headlinerCursor++ : HEADLINERS.length + i;
    games.push(buildGame(store, idx));
  }
  writeJson(file, { game_count: games.length, fresh_count: games.length, games });
}

// Wishlist + prices so the wishlist shot shows real numbers, not blanks.
const wishlist = [];
const byKey = {};
for (let i = 0; i < 22; i += 1) {
  const headliner = HEADLINERS[i % HEADLINERS.length];
  const id = `wl-${i + 1}`;
  const full = int(15, 70);
  const cut = pick([0, 20, 33, 40, 50, 60, 75, 80]);
  const price = Number((full * (1 - cut / 100)).toFixed(2));
  wishlist.push({
    store: 'wishlist',
    id,
    name: `${headliner.name}${i < HEADLINERS.length ? '' : pick(EDITIONS)}`,
    wishlist_store: pick(['steam', 'gog', 'epic']),
    store_target: 'steam',
    tracking_status: 'active',
    library_image: headliner.cover,
    header_image: headliner.cover,
    steam_review_percent: int(64, 96),
    hltb_main_hours: headliner.hltb,
    wishlist_added: isoDaysAgo(int(10, 900)),
    price_amount: price,
  });
  byKey[`wishlist:${id}`] = {
    price,
    regular: full,
    cut,
    currency: 'USD',
    shop: pick(['Steam', 'GOG', 'Fanatical', 'Humble Store']),
    is_historical_low: cut >= 60,
    is_historical_low_year: cut >= 50,
    updated_at: isoDaysAgo(1),
  };
}
writeJson('games_wishlist.json', { game_count: wishlist.length, games: wishlist });

// A few owned-library deals so the deals view is not empty either.
for (const row of allRows.slice(0, 40)) {
  const full = int(10, 60);
  const cut = pick([25, 33, 50, 66, 75]);
  byKey[`${row.store}:${row.id}`] = {
    price: Number((full * (1 - cut / 100)).toFixed(2)),
    regular: full,
    cut,
    currency: 'USD',
    shop: pick(['Steam', 'GOG', 'Fanatical']),
    is_historical_low: cut >= 66,
    is_historical_low_year: cut >= 50,
    updated_at: isoDaysAgo(1),
  };
}
writeJson('itad_prices.json', { updated_at: isoDaysAgo(1), by_key: byKey });

// Auto-fetch must stay off: a capture server that refreshes would overwrite
// these fictional catalogs with whatever this machine can reach locally
// (itch_local needs no sign-in), leaking a real library into the screenshots.
writeJson('data/personal.json', {
  personal,
  prefs: {
    activeView: 'dashboard',
    autoFetchOnConnect: false,
    autoFetchStale24h: false,
    checkUpdatesOnBoot: false,
    itadAutoRefreshDisabled: true,
    claimsAutoRefreshDisabled: true,
  },
});
writeJson('free_claims.json', { items: [], attribution: { sources: [] } });

// Expected row counts, checked before each capture so a contaminated catalog
// fails the run instead of shipping in a screenshot.
const expected = {};
for (const { file } of STORE_MIX) {
  expected[file] = JSON.parse(fs.readFileSync(path.join(profileRoot, file), 'utf8')).game_count;
}
expected['games_wishlist.json'] = wishlist.length;
fs.writeFileSync(
  path.join(dataDir, 'demo-manifest.json'),
  `${JSON.stringify({ expected, sample_titles: HEADLINERS.map((h) => h.name) }, null, 2)}\n`,
  'utf8',
);

// Isolated index: demo is the only profile in this data root, so the capture
// server boots straight into it without touching the real profile menu.
const indexPath = path.join(dataDir, 'profiles', 'index.json');
fs.mkdirSync(path.dirname(indexPath), { recursive: true });
fs.writeFileSync(
  indexPath,
  `${JSON.stringify(
    {
      active: 'demo',
      profiles: [{ id: 'demo', label: 'Demo (screenshots)', created_at: new Date().toISOString() }],
    },
    null,
    2,
  )}\n`,
  'utf8',
);

console.log(`Wrote demo profile: ${allRows.length} games, ${wishlist.length} wishlist rows`);
console.log(`Data root: ${dataDir}`);

