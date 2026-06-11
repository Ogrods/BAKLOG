// Group dashboard stats by conceptual family and spread them so similar
// chips/insights never appear adjacent (marquee, spotlight rotation, insight ticker).

export const FAMILY = {
  COMPLETION: 'completion',
  TIME: 'time',
  RATING: 'rating',
  DEALS: 'deals',
  COUNTS: 'counts',
  SABER: 'saber',
  IDENTITY: 'identity',
  ACTIVITY: 'activity',
  COMPAT: 'compat',
  WILDCARD: 'wildcard',
};

const _unknown = new Map();
let _unknownSeq = 0;

/** Stable family id for labels not matched by any rule (each label is its own family). */
function uniqueFamily(label) {
  const key = String(label ?? '').trim() || '(empty)';
  if (!_unknown.has(key)) _unknown.set(key, Symbol(`stat:${key}`));
  return _unknown.get(key);
}

function matchesAny(text, patterns) {
  const t = String(text ?? '').toLowerCase();
  return patterns.some(p => (typeof p === 'string' ? t.includes(p) : p.test(t)));
}

/**
 * @param {string} label — marquee chip label
 * @returns {string|symbol}
 */
export function familyForLabel(label) {
  const l = String(label ?? '').trim();
  if (!l) return uniqueFamily(l);

  if (matchesAny(l, [
    'proton', 'deck-ready', 'borked on linux', 'deck ready',
    'silver or native', 'avg proton',
  ])) {
    return FAMILY.COMPAT;
  }

  if (matchesAny(l, [
    'trophy', 'achievement', 'gamerscore', 'platinum', '100%', '100 %',
    'completionist', 'mastered', 'one push from', 'closest to 100', 'closest platinum',
    'fully completed', 'avg achievement', 'platinums earned', 'platinum hunt', 'trophies earned',
    'avg trophy completion', 'gamerscore completion',
  ])) {
    return FAMILY.COMPLETION;
  }

  if (matchesAny(l, [
    'hltb', 'backlog main', 'marathon', 'epic', 'to clear', 'to beat',
    'work-week', 'work week', 'shelf time', 'shelf warmer', 'pace', 'hours finished',
    'completionist hours', 'completionist run', 'longest backlog', 'shortest backlog',
    'longest game beaten', 'non-stop', '2h/day', '4h/day', '8h/day', 'half-life',
    'your pace', 'gathering dust', 'time capsule', 'avg shelf',
  ])) {
    return FAMILY.TIME;
  }

  if (matchesAny(l, [
    'review', 'rated', 'mendoza', 'hidden gem', 'top-rated', 'top rated',
    'unplayed', 'league avg', 'luck-adjusted', 'luck adjusted', 'guilty pleasure',
    'critically', 'comfort genre', 'blind spot', 'metacritic',
    'metacritic 80+', 'biggest critic gap',
  ])) {
    return FAMILY.RATING;
  }

  if (matchesAny(l, [
    'sale', 'deal', 'discount', 'cut', 'steal', 'msrp', 'wishlist value', 'savings',
    'historical low', 'whale', 'cheap thrill', 'clutch pick', 'got away', 'patience pays',
    'dollar', 'price', 'free, never', 'itch spend', 'free itch', 'upcoming wishlist',
    'bought on sale', 'paid itch', 'avg owned steam', 'priority wishlist',
    'wishlist added this year', 'wishlist stores',
  ])) {
    return FAMILY.DEALS;
  }

  if (matchesAny(l, [
    'games owned', 'stores', 'wishlists tracked', 'itch games', 'in backlog',
    'completed', 'games touched', 'in progress', 'queued next', 'left unfinished',
    'completion (excl', 'ever touched', 'co-op ready', 'priority flagged',
    'unique developers', 'unique genres', 'games per store', 'free, never launched',
    'cleanup candidates', 'clutch picks', 'net adds', 'added in', 'installed locally',
    'multiplayer share', 'singleplayer backlog',
    'co-op tagged', 'partial controller', 'indie-tagged', 'early access backlog',
    'double-dip backlog', 'hltb low confidence', 'launcher installs', 'adult games',
  ])) {
    return FAMILY.COUNTS;
  }

  if (matchesAny(l, [
    'ops', 'obp', 'slg', 'iso', 'barrel rate', 'magic #', 'magic number',
    'bv+', 'genre+', 'store+', 'win shares', 'pythagorean', 'power-speed',
    'quick-win speed', 'finish streak', 'hoard rate', 'quality start',
    'completion avg', 'start rate', 'abandon rate', 'closer power', 'rookie finish',
    'veteran finish', 'below mendoza', 'critic gap', "people's champ", "critics' darling",
    'overrated index', 'perpetual beta', 'couch-ready', 'aging curve', 'day-one player',
    'extra innings', 'double dips', 'cost per finish', 'sunk cost',
    'will you die first',
  ])) {
    return FAMILY.SABER;
  }

  if (matchesAny(l, [
    'top genre', 'top decade', 'top developer', 'favorite developer', 'top publisher', 'top store',
    'biggest store', 'oldest in library', 'newest release', 'oldest unplayed',
    'newest add', 'missing a', 'missing a–z', 'taste era', 'finished vs backlog era',
    'one-hit dev', 'monogamy', 'playtime in', 'diagnosis', 'a-z', 'top tag',
    'ps5-native', 'ps4 holdouts', 'letter coverage',
  ])) {
    return FAMILY.IDENTITY;
  }

  if (matchesAny(l, [
    'most-played', 'most played', 'add velocity', 'newest add', 'added in',
    'net adds', 'finish streak', 'all-time played', 'avg time per played',
    'played in last', 'longest dormant', 'last seen this week',
  ])) {
    return FAMILY.ACTIVITY;
  }

  // kojima easter egg and other one-offs
  return uniqueFamily(l);
}

/**
 * @param {string} eyebrow — spotlight category label (canonical)
 * @returns {string|symbol}
 */
export function familyForEyebrow(eyebrow) {
  const e = String(eyebrow ?? '').trim();
  if (!e) return uniqueFamily(e);

  if (matchesAny(e, [
    'almost mastered', 'completionist', 'one push', 'so close', 'nearly done',
    'maxed out', '100% club', 'platinum', 'pick back up', 'resume',
  ])) {
    return FAMILY.COMPLETION;
  }

  if (matchesAny(e, [
    'long haul', 'weekend-sized', 'weekender', 'fast finish', 'quick win',
    'top-rated quick', 'elite short', 'time capsule', 'gathering dust',
    'shelf warmer', 'ancient add', 'still sealed',
  ])) {
    return FAMILY.TIME;
  }

  if (matchesAny(e, [
    'critically acclaimed', 'highly rated', 'hidden gem', 'solid pick',
    'worth a look', 'top-rated', 'well reviewed', 'guilty pleasure',
    'rare stinker', 'stinker', 'critic darling', 'critics agree',
    'metacritic favorite',
  ])) {
    return FAMILY.RATING;
  }

  if (matchesAny(e, ['deck ready', 'deck verified', 'runs on deck', 'linux-ready'])) {
    return FAMILY.COMPAT;
  }

  if (matchesAny(e, ['aged classic', 'old but gold', 'retro pick', 'still kicking'])) {
    return FAMILY.IDENTITY;
  }

  if (matchesAny(e, [
    'on sale', 'clutch deal', 'steal pick', 'deal alert', 'whale', 'cheap thrill',
    'bargain', 'budget',
  ])) {
    return FAMILY.DEALS;
  }

  if (matchesAny(e, ['recently added', 'just landed', 'new arrival', 'fresh'])) {
    return FAMILY.ACTIVITY;
  }

  if (matchesAny(e, ['replay', 'encore', 'rerun', 'revisit', 'return to', 'up next', 'on deck'])) {
    return FAMILY.ACTIVITY;
  }

  if (matchesAny(e, ['co-op', 'couch', 'local co-op', 'squad'])) {
    return FAMILY.IDENTITY;
  }

  if (matchesAny(e, ['barrel', 'new release', 'brand new', 'fresh release'])) {
    return FAMILY.SABER;
  }

  if (matchesAny(e, ['random pick', 'dealer', 'wild card', 'wildcard', 'lucky dip', 'cat game', 'here, kitty', 'meow', 'cat content'])) {
    return FAMILY.WILDCARD;
  }

  // Discovery fallbacks (low/no-signal backlog picks).
  if (matchesAny(e, ['supposedly perfect', 'unreviewed'])) {
    return FAMILY.RATING;
  }
  if (matchesAny(e, ['unplayed'])) {
    return FAMILY.ACTIVITY;
  }
  if (matchesAny(e, ['total mystery', 'complete unknown', 'blank slate', 'no data'])) {
    return FAMILY.IDENTITY;
  }

  return familyForLabel(e);
}

/** Leading phrase before colon in insight HTML, or keyword scan of full string. */
export function familyForInsight(html) {
  const raw = String(html ?? '');
  const plain = raw.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  const colon = plain.indexOf(':');
  const lead = colon >= 0 ? plain.slice(0, colon).trim() : plain.slice(0, 48);

  if (matchesAny(lead, ['biggest backlog', 'avg hltb', 'longest unplayed', 'finish backlog by age', 'shelf warmer', 'backlog =', 'work-week', 'to clear at'])) {
    return FAMILY.TIME;
  }
  if (matchesAny(lead, ['closest to 100', 'finish rate', 'pythagorean'])) {
    return lead.toLowerCase().includes('pythagorean') ? FAMILY.SABER : FAMILY.COMPLETION;
  }
  if (matchesAny(plain, ['mendoza', 'ops', 'pythagorean', 'diagnosis', 'critic gap', 'will you die first', "people's champ", 'double dips', 'extra innings'])) {
    if (matchesAny(plain, ['mendoza', 'pythagorean', 'ops', 'diagnosis', 'critic gap', 'will you die first', "people's champ", 'double dips', 'extra innings'])) return FAMILY.SABER;
  }
  if (matchesAny(lead, ['average review', 'hidden gems', 'quick wins', 'avg metacritic'])) {
    return FAMILY.RATING;
  }
  if (matchesAny(lead, ['longest dormant'])) {
    return FAMILY.ACTIVITY;
  }
  if (matchesAny(lead, ['top deal', 'whale', 'guilty pleasure', 'one that got away', 'clutch pick'])) {
    return FAMILY.DEALS;
  }
  if (matchesAny(lead, ['most played', 'newest add', 'hours per game', 'added '])) {
    return FAMILY.ACTIVITY;
  }
  if (matchesAny(lead, ['one-hit dev', 'backlog diagnosis'])) {
    return FAMILY.IDENTITY;
  }

  return familyForLabel(lead);
}

function sameFamily(a, b) {
  return a === b || (typeof a === 'symbol' && typeof b === 'symbol' && a === b);
}

/**
 * Reorder items so no two adjacent entries share a family when possible.
 * Groups preserve intra-family order; emits round-robin across families.
 * @template T
 * @param {T[]} items
 * @param {(item: T) => string|symbol} getFamily
 * @param {{ wrap?: boolean }} [opts] — if true, rotate so first/last differ (looping UIs)
 * @returns {T[]}
 */
export function spreadByFamily(items, getFamily, opts = {}) {
  if (!items?.length) return items ? [...items] : [];

  const buckets = new Map();
  const bucketKeys = [];
  for (const item of items) {
    const key = getFamily(item);
    if (!buckets.has(key)) {
      buckets.set(key, []);
      bucketKeys.push(key);
    }
    buckets.get(key).push(item);
  }

  const out = [];
  const total = items.length;
  while (out.length < total) {
    const prevFam = out.length ? getFamily(out[out.length - 1]) : null;
    const eligible = bucketKeys.filter((key) => {
      const bucket = buckets.get(key);
      return bucket.length && !sameFamily(getFamily(bucket[0]), prevFam);
    });
    let pickKey = eligible.length
      ? eligible.reduce((best, key) =>
          buckets.get(key).length > buckets.get(best).length ? key : best, eligible[0])
      : bucketKeys.find((key) => buckets.get(key).length);
    out.push(buckets.get(pickKey).shift());
  }

  if (opts.wrap && out.length > 1 && sameFamily(getFamily(out[0]), getFamily(out[out.length - 1]))) {
    for (let rot = 1; rot < out.length; rot++) {
      const candidate = out.slice(rot).concat(out.slice(0, rot));
      if (
        !sameFamily(getFamily(candidate[0]), getFamily(candidate[candidate.length - 1])) &&
        hasNoAdjacentSameFamily(candidate, getFamily, { wrap: true })
      ) {
        return candidate;
      }
    }
  }

  return out;
}

/** Test helper: true when no adjacent pair shares a family. */
export function hasNoAdjacentSameFamily(items, getFamily, { wrap = false } = {}) {
  if (items.length < 2) return true;
  for (let i = 1; i < items.length; i++) {
    if (sameFamily(getFamily(items[i]), getFamily(items[i - 1]))) return false;
  }
  if (wrap && sameFamily(getFamily(items[0]), getFamily(items[items.length - 1]))) return false;
  return true;
}
