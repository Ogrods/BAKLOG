/**
 * Realistic steam-shaped game rows for perf micro-benchmarks and profile fixtures.
 */

const GENRES = ['Action', 'RPG', 'Strategy', 'Indie', 'Adventure', 'Simulation'];
const TAGS = ['Singleplayer', 'Multiplayer', 'Co-op', 'Story Rich', 'Open World'];

/**
 * @param {number} count
 * @param {{ prefix?: string, startId?: number }} [opts]
 */
export function syntheticSteamGames(count, opts = {}) {
  const prefix = opts.prefix || 'Perf Game';
  const startId = opts.startId ?? 1000;
  const games = [];
  for (let i = 0; i < count; i++) {
    const id = startId + i;
    games.push({
      store: 'steam',
      id: String(id),
      appid: id,
      name: `${prefix} ${String.fromCharCode(65 + (i % 26))}${i}`,
      status: i % 7 === 0 ? 'completed' : i % 5 === 0 ? 'playing' : 'unplayed',
      hltb_main: (i % 40) + 1,
      steam_review_percent: 60 + (i % 40),
      release_date: `20${10 + (i % 15)}-${String((i % 12) + 1).padStart(2, '0')}-15`,
      genres: [GENRES[i % GENRES.length], GENRES[(i + 2) % GENRES.length]],
      tags: [TAGS[i % TAGS.length]],
      playtime_forever: i * 3,
    });
  }
  return games;
}

/**
 * @param {number} count
 */
export function steamCatalogPayload(count) {
  const games = syntheticSteamGames(count);
  return {
    game_count: games.length,
    fresh_count: games.length,
    games,
  };
}

/**
 * Minimal wishlist rows referencing steam targets.
 * @param {number} count
 */
export function syntheticWishlistGames(count) {
  const games = [];
  for (let i = 0; i < count; i++) {
    games.push({
      store: 'wishlist',
      id: `wl-${i}`,
      name: `Wishlist Target ${i}`,
      wishlist_store: 'steam',
      store_target: 'steam',
      tracking_status: 'active',
    });
  }
  return games;
}

/**
 * Minimal itch.io catalog rows so perf/responsive audits open the itch view
 * (cached catalog makes isItchTabAvailable true without Connect).
 * @param {number} count
 */
export function syntheticItchGames(count) {
  const games = [];
  for (let i = 0; i < count; i++) {
    games.push({
      store: 'itch',
      id: 9000 + i,
      itch_id: 9000 + i,
      name: `Itch Jam ${i}`,
      type: 'game',
      playtime_minutes: 0,
      publisher: 'Perf Fixture',
    });
  }
  return games;
}

/**
 * @param {number} count
 */
export function itchCatalogPayload(count) {
  const games = syntheticItchGames(count);
  return {
    game_count: games.length,
    games,
  };
}
