/**
 * Co-op feature overrides for non-Steam libraries.
 *
 * Steam infers `coop_online` / `coop_local` from store category descriptions
 * inside `fetch_games.py`. Every other store (Epic, PSN, Xbox, etc.) ships
 * with both flags false because we don't have a reliable co-op-tag source for
 * them. This registry lets us hand-mark known multiplayer/co-op titles so the
 * "online co-op" filter, dashboard co-op spotlight, and row pills work
 * consistently across stores.
 *
 * Matching is by normalized name (case + punctuation + edition tokens stripped
 * via normalizeNameForDedup), so a single entry covers every platform copy of
 * a game (e.g. Fortnite on PSN + Xbox + Epic).
 *
 * Steam entries are intentionally left alone — fetch_games.py is authoritative
 * for Steam co-op flags.
 */

export const COOP_NAME_OVERRIDES = [
  { name: "Fortnite",                         coop_online: true },
  { name: "Rocket League",                    coop_online: true },
  { name: "Ghost of Tsushima",                coop_online: true },
  { name: "Ghost of Tsushima Director's Cut", coop_online: true },
  { name: "Ghost of Yotei",                   coop_online: true },
];
