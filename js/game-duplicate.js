import { state } from './state.js';
import { normalizeNameForDedup, scoreEntry, gameKey, wishlistEntryStore } from './game-core.js';
import { getPersonal } from './personal-storage.js';

/**
 * Best existing catalog row whose title matches (normalized), for add-game duplicate warning.
 * @param {string} title
 * @param {'library'|'wishlist'|'itch'} targetView
 * @param {{ includeHidden?: boolean }} [options]
 */
export function findDuplicateMatch(title, targetView, options = {}) {
  const norm = normalizeNameForDedup(title);
  if (!norm) return null;
  let source;
  if (targetView === 'wishlist') source = state.wishlistGames;
  else if (targetView === 'itch') source = state.itchGames;
  else source = state.allGames;
  let best = null;
  let bestScore = -1;
  for (const g of source) {
    if (normalizeNameForDedup(g.name) !== norm) continue;
    if (!options.includeHidden && getPersonal(g).hidden) continue;
    const score = scoreEntry(g);
    if (score > bestScore) {
      bestScore = score;
      best = g;
    }
  }
  return best;
}

export function duplicateMatchLabel(g, targetView) {
  if (!g) return '';
  if (targetView === 'wishlist') {
    const store = wishlistEntryStore(g);
    return `${g.name} (${store})`;
  }
  return `${g.name} (${g.store || 'unknown'})`;
}

export function duplicateMatchKey(g) {
  return g ? gameKey(g) : null;
}
