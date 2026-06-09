// One-time seed: the 2026-06-08 untapped-metadata batch starts in Unused (hidden)
// until the maintainer moves them to Used. Auto-sync preserves manual hides.

const BATCH_SEEDED_BASE = 'baklog-metrics-untapped-batch-seeded';
const ACTIVE_PROFILE_LS = 'baklog-active-profile';

/** @type {readonly string[]} */
export const UNTAPPED_BATCH_METRIC_KEYS = Object.freeze([
  'Deck-ready %',
  'Proton platinum',
  'borked on Linux',
  'Proton trending up',
  'Deck-ready backlog',
  'platinums earned',
  'platinum hunt',
  'trophies earned',
  'PS5-native %',
  'PS4 holdouts',
  'top tag',
  'multiplayer share',
  'singleplayer backlog',
  'free itch games',
  'itch spend',
  'installed locally',
  'played in last 30d',
  'Longest dormant',
  'Avg Metacritic',
  'Metacritic 90+ club',
  'upcoming wishlist',
]);

function profileSuffix(profileId) {
  let pid = profileId;
  if (pid == null) {
    try {
      pid = localStorage.getItem(ACTIVE_PROFILE_LS) || 'default';
    } catch {
      pid = 'default';
    }
  }
  return pid && pid !== 'default' ? `:${pid}` : '';
}

/** @param {string} [profileId] */
export function untappedBatchMarkerKey(profileId) {
  return `${BATCH_SEEDED_BASE}${profileSuffix(profileId)}`;
}

/**
 * @param {Storage} storage
 * @param {string} [profileId]
 */
export function hasSeededUntappedBatch(storage = localStorage, profileId) {
  try {
    return storage.getItem(untappedBatchMarkerKey(profileId)) === '1';
  } catch {
    return false;
  }
}

/**
 * Merge the untapped batch into disabled once per profile.
 * @param {string[]} disabled
 * @param {Storage} [storage]
 * @param {string} [profileId]
 * @returns {string[]}
 */
export function mergeUntappedBatchSeed(disabled, storage = localStorage, profileId) {
  if (hasSeededUntappedBatch(storage, profileId)) return disabled;
  try {
    storage.setItem(untappedBatchMarkerKey(profileId), '1');
  } catch {
    return disabled;
  }
  return [...new Set([...disabled, ...UNTAPPED_BATCH_METRIC_KEYS])];
}
