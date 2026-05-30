/** Shared game identity and cover helpers (main thread + table-query worker). */

export function gameStore(g) {
  return g.store || 'steam';
}

export function gameId(g) {
  return g.id ?? g.appid ?? g.gog_id ?? g.psn_id ?? g.epic_catalog_id ?? g.amazon_id
    ?? g.nintendo_id ?? g.itch_id ?? g.xbox_title_id ?? g.battlenet_id ?? g.ubisoft_id;
}

export function normalizeGame(g) {
  if (g.store && g.id != null) return g;
  const store = gameStore(g);
  const id = gameId(g);
  return { ...g, store, id };
}

export function gameKey(g) {
  return `${gameStore(g)}:${gameId(g)}`;
}

export function coverFallbackFor(g) {
  const ng = normalizeGame(g);
  if (ng.header_image) return ng.header_image;
  if (ng.store === 'steam') return `https://cdn.akamai.steamstatic.com/steam/apps/${ng.id}/header.jpg`;
  return '';
}
