// Tooltip copy for dashboard marquee chips and rotating insights.
// Sabermetrics entries include the calculation; regular metrics are plain-language.

/** Review % = store rating; Mendoza = median backlog review % (replacement level). */
const WAR_FORMULA_EXPLAIN =
  'Review % = store rating (e.g. Steam positive %). Mendoza line = median review % of your backlog — replacement-level. WAR = (review % − Mendoza) ÷ 10 + length/deal bonuses.';

/** @type {Record<string, string>} */
export const METRIC_TIPS = {
  // Library counts
  'games owned': 'Total games in your merged library across all connected stores.',
  stores: 'Number of distinct storefronts represented in your library.',
  'wishlists tracked': 'Count of separate wishlist sources being tracked.',
  'itch games': 'itch.io titles classified as games (not tools or assets).',
  'in backlog': 'Games marked backlog: owned but not started, playing, or finished.',
  completed: 'Games you marked finished.',
  'games touched': 'Games with any recorded playtime.',
  'in progress': 'Games marked playing.',
  'queued next': 'Games marked next in your queue.',
  'left unfinished': 'Games you started but marked unfinished.',
  'completion (excl. skip)': 'Finished ÷ non-skipped games. Skipped titles are excluded from the denominator.',
  'ever touched': 'Share of the library with any playtime (touched ÷ total).',
  'all-time played': 'Sum of playtime across all games, in hours.',
  'avg time per played game': 'Total hours played divided by number of games touched.',
  'most-played': 'Title with the highest combined playtime in your library.',

  // HLTB / backlog shape
  'avg backlog main': 'Average HowLongToBeat main-story hours across backlog titles.',
  'median backlog main': 'Median HLTB main hours across backlog titles.',
  'longest backlog': 'Backlog game with the highest HLTB main estimate.',
  'shortest backlog': 'Shortest HLTB main among backlog games with a known estimate.',
  'under 2h to beat': 'Backlog games with HLTB main ≤ 2 hours.',
  'under 5h to beat': 'Backlog games with HLTB main ≤ 5 hours.',
  '50h+ marathons': 'Backlog games with HLTB main ≥ 50 hours.',
  '100h+ epics': 'Backlog games with HLTB main ≥ 100 hours.',
  'to clear at 2h/day': 'Backlog HLTB hours ÷ (2 hours × 365 days).',
  'to clear at 4h/day': 'Backlog HLTB hours ÷ (4 hours × 365 days).',
  'non-stop at 8h/day': 'Backlog HLTB hours ÷ 8 hours per day.',

  // Ratings
  'avg review score': 'Mean Steam (or store) review % across rated games.',
  'avg backlog review': 'Mean review % among backlog games that have a rating.',
  'of library rated': 'Share of library with a review score on record.',
  'median review score': 'Median review % across rated games.',
  'league avg rating': 'Library mean rating (rBar): average of all rated games; 100 = league average for Genre+/Store+.',
  '90%+ unplayed': 'Backlog games rated 90%+ with enough reviews, still unplayed.',
  '80%+ unplayed': 'Backlog games rated 80%+ with enough reviews, still unplayed.',
  'top-rated unplayed': 'Highest-rated backlog title with enough reviews.',

  // Trophies / Xbox
  'avg achievement completion': 'Mean trophy/achievement completion % where tracked.',
  'fully completed (100%)': 'Games with 100% trophy progress.',
  'one push from 100%': 'Games between 90% and 100% trophy completion.',
  'closest to 100%': 'Tracked game nearest to full trophy completion.',
  'gamerscore earned': 'Total Xbox gamerscore earned across scored titles.',
  'of available gamerscore': 'Earned gamerscore ÷ total available gamerscore.',
  'trophy efficiency': 'Average trophy completion % across games with trophy data.',
  'gamerscore efficiency': 'Total earned Xbox gamerscore ÷ total available.',
  'platinum potential': 'Tracked games 80–99% complete that are short (≤12h) - an easy run to 100%.',
  'closest platinum': 'Among platinum-potential titles, the one nearest full completion.',

  // Sabermetrics - slash line & rates
  'completion AVG': 'Batting-style completion average: finished ÷ (finished + unfinished).',
  'backlog OPS': 'On-base plus slugging: start rate (OBP) + length-weighted finish rate (SLG).',
  'start rate (OBP)': 'On-base %: share of owned games ever played (touched ÷ total).',
  'abandon rate (K%)': 'Strikeout rate: unfinished ÷ touched (started but not finished).',
  'closer power (ISO)': 'Isolated power: SLG − AVG; extra finish power beyond raw completion rate.',
  'slugging (SLG)': 'Length-weighted finish rate: sum of length bases on finished games ÷ (finished + unfinished). Quick=1, short=2, long=3, epic=4 bases.',
  'barrel rate': 'Share of library that is barrel-quality: ≥85% rated and ≤12h HLTB.',
  'magic # to 50%': 'Finishes still needed to reach 50% of non-skipped library: ceil(nonSkip × 50%) − finished.',
  'backlog pace (median HLTB)': 'Median HLTB main hours across backlog - typical commitment per pick.',
  'hoard rate (never touched)': 'Share of library with zero playtime (never launched).',
  'quality start rate': 'Share of played games where playtime ≥ 40% of HLTB main (a real session).',
  'top WAR': `Highest WAR among backlog/next/playing. ${WAR_FORMULA_EXPLAIN}`,
  'cleanup candidates': 'Games flagged as cleanup candidates (low rating, no playtime, etc.).',
  'clutch picks': 'Backlog games that are leverage picks: ≥80% rated, on sale, ≤15h.',
  'finish streak': 'Hot/warm/cold from recent finishes: hot = 3+ recent, cold = none or stale.',
  'power-speed #': 'Harmonic mean of long-game finishes (power) and quick high-rated finishes (speed).',
  'vs pythagorean': 'Actual completion rate minus hours-based expectation: played²/(played²+remaining²).',
  'quick-win speed index': 'Count of backlog games ≥75% rated with HLTB ≤ your quick-win max hours.',

  // Sabermetrics - value & park factors
  'BV+ leader': 'Highest backlog BV+: rating per time invested, indexed so 100 = library average.',
  'avg BV+ (100 = avg)': 'Mean BV+ across rated backlog games; 100 = league-average value per hour.',
  'Genre+': 'Genre park factor: genre avg rating ÷ library mean (rBar) × 100. 100 = average.',
  'weakest Genre+': 'Genre with the lowest Genre+ index vs library average.',
  'Store+': 'Store park factor: store avg rating ÷ rBar × 100. 100 = average.',
  'win shares leader': 'Genre with the most finished games (win shares by genre).',
  'rookie finish rate (<30d)': 'Finish % for games first seen in the library under 30 days ago.',
  'veteran finish rate (1y+)': 'Finish % for games in library 1 year or more.',
  'luck-adjusted': 'Rating regressed toward library mean when review count is low (small sample).',

  // Deals / wishlist
  'steal-tier deals': 'Wishlist deals classified as steal-tier by deal score.',
  'on sale now': 'Wishlist items with an active discount.',
  'top deal': 'Wishlist item with the highest deal score right now.',
  'avg discount': 'Mean discount % across on-sale wishlist items.',
  'steepest cut': 'Largest single discount % on your wishlist.',
  'wishlist value': 'Sum of regular (MSRP) prices for wishlist items with price data.',
  'savings if bought now': 'Wishlist MSRP total minus current sale prices.',

  // Releases / metadata
  'oldest in library': 'Owned game with the earliest release year in your catalog.',
  'newest release owned': 'Owned game with the latest release year.',
  'top decade': 'Decade with the most owned releases.',
  'oldest unplayed': 'Oldest release-year backlog game still unplayed.',
  'newest add': 'Most recently added game by added_at date.',
  'top developer': 'Developer with the most owned titles.',
  'top publisher': 'Publisher with the most owned titles.',
  'unique developers': 'Count of distinct developers in the library.',
  'top genre': 'Genre tag appearing on the most games.',
  'unique genres': 'Count of distinct genre tags.',
  'cat games': 'Games with "cat" anywhere in the title (substring match).',
  'biggest store': 'Storefront with the most owned games.',
  'games per store avg': 'Total games ÷ number of stores.',
  'longest game beaten': 'Finished game with the highest HLTB main.',
  'total hours finished': 'Sum of HLTB main hours for finished games.',
  'completionist hours total': 'Sum of HLTB completionist hours where known.',
  'avg completionist run': 'Mean HLTB completionist hours where known.',
  'co-op ready': 'Games with online or local co-op flags.',
  'priority flagged': 'Games with a personal priority flag set.',
  'first PSN session': 'Owned title with the earliest PSN first_played date in your library.',
  'most PSN sessions': 'PSN title with the highest play_count (launch sessions).',
  'PSN sessions total': 'Sum of PSN play_count across your library.',
  'PSN library tenure': 'Years since your earliest recorded PSN first_played date.',
  'session grinder': 'High session count relative to hours played (short repeat launches).',

  // New-data sabermetrics (Metacritic, acquired_at, early access, controller, HLTB depth, Game Pass, cross-store)
  'critic gap (avg)': 'Mean |Steam review % − Metacritic| across games with both scores.',
  "people's champ": 'Owned title with the biggest positive critic gap (players rate higher than critics).',
  "critics' darling": 'Highest Metacritic score among owned games you have never launched.',
  'overrated index': 'Owned title where critics scored highest vs players (biggest negative gap).',
  'perpetual beta': 'Early-access titles still in your library.',
  'couch-ready %': 'Share of library with full controller support (Steam enrichment).',
  'aging curve': 'Average days from acquired_at to first recorded play session.',
  'day-one player': 'Games you launched within 24 hours of acquiring.',
  'extra innings': 'Average HLTB completionist − main gap (optional content beyond the main story).',
  "subscriber's dividend": 'Titles playable via Xbox Game Pass or EA Play (game_pass flag).',
  'double dips': 'Same game owned on two or more storefronts (cross-store dedup).',
  'cost per finish': 'Total library MSRP (priced rows) ÷ games marked finished.',
  'sunk cost': 'Sum of MSRP for owned games with zero playtime.',
  'will you die first?': 'If backlog clear-by age (2h/day pace) exceeds life expectancy, the backlog wins.',

  // ProtonDB / Steam Deck (ProtonDB data ODbL)
  'Deck-ready %': 'Share of ProtonDB-rated games that run great on Linux/Steam Deck (platinum or gold tier).',
  'Proton platinum': 'Games ProtonDB rates platinum — run flawlessly on Linux/Deck out of the box.',
  'borked on Linux': "Games ProtonDB rates borked — currently won't run on Linux/Steam Deck.",
  'Proton trending up': 'Games whose recent ProtonDB reports trend better than their overall tier.',
  'Deck-ready backlog': 'Backlog games you can comfortably play on Steam Deck now (Proton platinum or gold).',

  // PSN platinum & platform
  'platinums earned': "PlayStation platinum trophies you've earned across your library.",
  'platinum hunt': "Owned PSN games with a platinum trophy you haven't earned yet.",
  'trophies earned': 'Total PlayStation trophies earned across your PSN library.',
  'PS5-native %': 'Share of your PlayStation library that runs natively on PS5.',
  'PS4 holdouts': 'PSN titles that are PS4-only — no native PS5 version in your library.',

  // Steam tags
  'top tag': 'The Steam community tag that appears on the most games in your library.',
  'multiplayer share': 'Share of tagged games tagged multiplayer, co-op, PvP, or online.',
  'singleplayer backlog': 'Backlog games tagged single-player — solo experiences waiting.',

  // itch / install / recency
  'free itch games': 'itch.io titles in your library with zero minimum price.',
  'itch spend': 'Total minimum price of paid itch.io games you own.',
  'installed locally': 'Games detected as installed locally on this machine (launcher scan).',
  'played in last 30d': "Games you've launched in the past 30 days.",
  'Longest dormant': "The game you once played but haven't touched for the longest stretch.",
  'upcoming wishlist': "Wishlist items that haven't released yet (coming soon).",

  // Metacritic expansion
  'Avg Metacritic': 'Average Metacritic critic score across games that have one.',
  'Metacritic 90+ club': 'Owned games with a Metacritic critic score of 90 or above.',
  'Metacritic 80+ unplayed': 'Owned games with Metacritic ≥ 80 and zero playtime.',
  'biggest critic gap': 'Owned title with the largest gap between Steam review % and Metacritic score.',

  // ProtonDB batch 2
  'silver or native %': 'Share of ProtonDB-rated games at silver or native tier (good Linux/Deck compatibility).',
  'Proton low confidence': 'ProtonDB-rated games where confidence is inadequate — thin report data.',
  'avg Proton score': 'Mean ProtonDB score across rated games in your library.',

  // Pricing batch 2
  'bought on sale': 'Steam games in your library purchased with a discount (discount_percent > 0).',
  'paid itch games': 'itch.io titles you own with a non-zero minimum price.',
  'avg owned Steam price': 'Average purchase/list price across priced Steam games you own.',

  // Wishlist batch 2
  'priority wishlist': 'Wishlist items with a non-zero priority rank.',
  'wishlist added this year': 'Wishlist items added since January 1 of the current year.',
  'wishlist stores': 'Distinct storefronts represented on your wishlist.',

  // Play / install batch 2
  'last seen this week': 'Games launched or seen locally in the past 7 days.',
  'launcher installs': 'Games detected as installed via the local launcher scan.',
  'HLTB low confidence': 'Games with an HLTB match but sub-perfect match confidence.',

  // Tags / platform batch 2
  'co-op tagged only': 'Games tagged co-op/multiplayer but without coop_online or coop_local flags.',
  'partial controller': 'Games with partial (not full) controller support.',
  'indie-tagged %': 'Share of tagged games that carry the Indie community tag.',

  // PSN / Xbox batch 2
  'avg trophy completion': 'Mean trophy completion % across PSN games with trophy totals.',
  'gamerscore completion %': 'Your earned Xbox gamerscore ÷ total available across Xbox library.',

  // Identity batch 2
  'early access backlog': 'Backlog games still marked early access on their store.',
  'double-dip backlog': 'Backlog titles you own on two or more storefronts.',
  'letter coverage %': 'Share of A–Z title initials present in your library (26 = full alphabet).',

  // Creative metrics (marquee)
  'comfort genre': 'Genre with the most finished games - where you actually deliver.',
  'blind spot genre': 'Genre with many owned titles but few or no finishes.',
  'to clear at your pace': 'Backlog hours ÷ your recent finish pace (creative half-life estimate).',
  'avg shelf time': 'Average days games sat on the shelf before first play or finish.',
  'MSRP sitting unplayed': 'Sum of regular prices for owned unplayed games with price data (subset only).',
  'total MSRP value': 'Sum of regular (MSRP) prices across every library row that has price data in your display currency. Rows without a comparable price are skipped.',
  'priced library rows': 'How many library rows have a comparable MSRP in your display currency - the priced subset that feeds the total MSRP value.',
  'avg MSRP per game': 'Average regular price across library rows that have price data (total MSRP value ÷ priced library rows).',
  'cheapest thrill': 'Lowest-priced highly rated game you have not played.',
  'free, never launched': 'Owned free games with zero playtime.',
  'add velocity': 'Average new games added per month recently.',
  'finished vs backlog era': 'Compares finish rate for older vs newer release eras.',
  'missing A–Z letters': 'Letters missing from the A–Z of game title initials in your library.',
  'backlog in work-weeks': 'Backlog HLTB hours expressed in 40-hour work-weeks.',
  'at historical low now': 'Wishlist items currently at an all-time or yearly low.',
  'oldest wishlist': 'Wishlist item waiting the longest (by wishlist_added or added_at date).',
  'gay character: you, the player.': 'Rare MGSV codec easter egg — you are the gay character.',

  // Dynamic marquee labels (prefix-matched at runtime)
  'below Mendoza': 'Backlog games whose store review % is below the Mendoza line (median backlog review %).',
  'added in': 'Games added to the library during this calendar year.',
  'net adds in': 'Adds minus finishes this year (net library growth).',
  'playtime in': 'Share of all playtime spent in this one game (monogamy).',

  // Insight-only concepts (leading text before colon)
  'Biggest backlog': 'Genre with the most backlog HLTB hours stacked up.',
  'Most played': 'Game with the highest combined playtime.',
  'Avg HLTB main': 'Average main-story HLTB hours across backlog games.',
  'Longest unplayed': 'Longest HLTB backlog game you have never played.',
  'Top deal': 'Wishlist item with the best deal score right now.',
  'Average review': 'Mean review % across all rated library games.',
  'Newest add': 'Most recently added game by date.',
  'Hours per game': 'Total hours played ÷ number of games in library.',
  'Quick wins ready': 'Backlog games ≥75% rated with HLTB ≤ quick-win max hours.',
  'Hidden gems': '90%+ rated, enough reviews, zero playtime.',
  'Clutch pick': 'Best leverage pick: strong rating, on sale, short HLTB.',
  'Mendoza line':
    'Mendoza line = median store review % across your backlog — replacement-level. WAR scores how far above or below this baseline each pick sits.',
  'Closest to 100%': 'Tracked game nearest full trophy completion.',
  'Finish rate': 'Completion average: finished ÷ (finished + unfinished), shown as .XXX.',
  'Top WAR pick': `Your highest-WAR active pick (backlog/next/playing). ${WAR_FORMULA_EXPLAIN}`,
  Pythagorean: 'Hours-based expected completion vs actual finish rate; over/underperforming label.',
  'Backlog diagnosis': 'Creative snapshot of backlog health (collector, finisher, hoarder, etc.).',
  'Shelf warmer': 'Owned game sitting longest without meaningful progress.',
  'Added': 'Oldest untouched backlog game by when it first appeared in your library (time capsule).',
  Whale: 'Highest MSRP owned title in the priced subset.',
  'Guilty pleasure': 'Low-rated game you still own (or play).',
  'One-hit dev': 'Developer with many owned games but zero finishes.',
  'One that got away': 'Wishlist deal you may have missed.',
  'Backlog =': 'Backlog HLTB hours expressed in standard work-weeks.',
  "People's champ": 'Owned title with the biggest positive critic gap (players > critics).',
  'Extra innings': 'Average completionist − main HLTB hours across games with both estimates.',
  'Double dips': 'Count of titles you own on two or more storefronts.',
  'Will you die first?': 'Backlog clear-by age at 2h/day vs a playful life expectancy — who wins?',
  'Critic gap': 'Mean |Steam review % − Metacritic| across rated library rows.',
};

/** Canonical metric ids for the admin Metrics tab and dashboard disable filter. */
export const METRIC_KEYS = Object.freeze(Object.keys(METRIC_TIPS));

/**
 * Tooltip copy for the rotating hero spotlight eyebrows. Keyed by the exact
 * eyebrow string set in js/dashboard-spotlight.js so cryptic / baseball terms
 * (Barrel, Completionist, Whale, etc.) explain themselves on hover.
 * @type {Record<string, string>}
 */
export const EYEBROW_TIPS = {
  'Recently added': 'One of the newest games to appear in your library.',
  Replay: 'A finished game worth revisiting - well-reviewed, with enough ratings. Surfaces rarely.',
  'Almost mastered': 'In progress with 80–99% of achievements/trophies earned - one push from done.',
  'Pick back up': 'In progress with 20–80% achievement completion - momentum left on the table.',
  'Return to': 'Started (30+ min) and well-rated - worth jumping back into.',
  'Up next': 'Marked next in your play queue.',
  'Clutch deal': 'Leverage pick: 80%+ rated, on sale, and ≤15h to beat - high value right now.',
  Barrel: 'Elite-rated (85%+) and short (≤12h) - a high-quality pick you can clear quickly.',
  'On sale now': 'A wishlist game (not yet owned) with an active discount.',
  'New release': 'Released within the last year and rated 70%+.',
  'Co-op campaign': 'Has online co-op and is well-rated (72%+) - grab a friend.',
  'Couch co-op': 'Supports local / same-couch co-op and is rated 70%+.',
  'Long haul': '40h+ epic rated 80%+ with enough reviews - a big commitment that pays off.',
  'Top-rated quick pick': '88%+ rated and ≤8h to beat - top shelf without the time sink.',
  'Critically acclaimed': '90%+ rated with enough reviews - among the best you own.',
  'Quick win': '78%+ rated and ≤5h to beat - clear it in an evening.',
  'Highly rated': '82%+ rated with enough reviews to trust the score.',
  'Hidden gem': '80%+ rated but with few reviews - under-the-radar pick.',
  'Solid pick': '75%+ rated with enough reviews - a dependable choice.',
  'Weekend-sized': '8–15h to beat and rated 72%+ - fits in a weekend.',
  'Fast finish': '≤4h to beat - knock it out fast.',
  'Worth a look': 'Rated 70%+ - a reasonable option from the backlog.',
  // Saber / creative superlatives
  'MVP pick': `Highest WAR among active picks. ${WAR_FORMULA_EXPLAIN}`,
  Completionist: 'Earned every trophy/achievement - 100% complete.',
  Whale: 'The priciest game (by MSRP) you own but have never launched.',
  'Gathering dust': 'The game that has sat unplayed on your shelf the longest.',
  'Time capsule': 'The oldest untouched backlog game by when it first appeared in your library.',
  'Cheap thrill': 'The cheapest highly rated (75%+) game you have not played yet.',
  'Guilty pleasure': 'The lowest-rated game you finished anyway.',
  'Rare stinker': 'Rare easter egg: the single lowest-rated game in your whole catalog.',
  'Random pick': 'Dealer\u2019s choice: one title pulled at random from your library.',
  'Cat game': 'A game with "cat" in the title. A rare treat for cat people.',
};

/**
 * Display variants per canonical spotlight eyebrow (index 0 = canonical wording).
 * Rendered via eyebrowVariant() so rotation feels varied while tooltips stay canonical.
 * @type {Record<string, string[]>}
 */
export const EYEBROW_VARIANTS = {
  'Recently added': ['Recently added', 'Just landed', 'New arrival', 'Fresh drop'],
  Replay: ['Replay', 'Encore', 'Rerun', 'Revisit'],
  'Almost mastered': ['Almost mastered', 'So close', 'Nearly done', 'One push'],
  'Pick back up': ['Pick back up', 'Resume', 'Unpause', 'Jump back in'],
  'Return to': ['Return to', 'Revisit', 'Circle back', 'Jump back in'],
  'Up next': ['Up next', 'On deck', 'Next up', 'Queued'],
  'Clutch deal': ['Clutch deal', 'Steal pick', 'Deal alert', 'On the clock'],
  Barrel: ['Barrel', 'Squared up', 'Easy crush', 'No-doubter'],
  'On sale now': ['On sale now', 'On sale', 'Discounted', 'Price drop'],
  'New release': ['New release', 'Just out', 'Fresh release', 'Brand new'],
  'Co-op campaign': ['Co-op campaign', 'Co-op run', 'Online co-op', 'Squad up'],
  'Couch co-op': ['Couch co-op', 'Local co-op', 'Same couch', 'Couch play'],
  'Long haul': ['Long haul', 'Big commitment', 'Time sink', 'Epic'],
  'Top-rated quick pick': ['Top-rated quick pick', 'Elite short', 'Quick gem', 'Short great'],
  'Critically acclaimed': ['Critically acclaimed', 'Acclaimed', 'Top reviewed', 'Award-tier'],
  'Quick win': ['Quick win', 'Easy clear', 'Fast clear', 'One night'],
  'Highly rated': ['Highly rated', 'Well reviewed', 'Crowd favorite', 'Fan favorite'],
  'Hidden gem': ['Hidden gem', 'Sleeper', 'Overlooked', 'Under radar'],
  'Solid pick': ['Solid pick', 'Safe bet', 'Dependable', 'Reliable'],
  'Weekend-sized': ['Weekend-sized', 'Weekender', 'Two-day', 'Weekend fit'],
  'Fast finish': ['Fast finish', 'One sitting', 'Knock-out', 'Speedy'],
  'Worth a look': ['Worth a look', 'Maybe this', 'Why not', 'A look'],
  'MVP pick': ['MVP pick', 'Top WAR', 'MVP', 'All-star'],
  Completionist: ['Completionist', 'Maxed out', '100% club', 'Platinum'],
  Whale: ['Whale', 'Big spender', 'Priciest', 'Money sink'],
  'Gathering dust': ['Gathering dust', 'Collecting dust', 'Shelf warmer', 'Untouched'],
  'Time capsule': ['Time capsule', 'Ancient add', 'Old timer', 'Still sealed'],
  'Cheap thrill': ['Cheap thrill', 'Bargain pick', 'Budget gem', 'Budget buy'],
  'Guilty pleasure': ['Guilty pleasure', 'Guilty fave', 'No regrets', 'Trashy fun'],
  'Rare stinker': ['Rare stinker', 'Certified stinker', 'Bottom tier', 'The worst'],
  'Random pick': ['Random pick', 'Dealer\u2019s choice', 'Wild card', 'Lucky dip'],
  'Cat game': ['Cat game', 'Here, kitty', 'Meow', 'Cat content'],
};

/** @param {string} s */
function hashSeed(s) {
  let h = 0;
  const str = String(s ?? '');
  for (let i = 0; i < str.length; i++) {
    h = ((h << 5) - h + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * Deterministic display label for a spotlight eyebrow (canonical identity unchanged).
 * @param {string} canonical
 * @param {string} seed - typically gameKey(g)
 * @returns {string}
 */
export function eyebrowVariant(canonical, seed) {
  if (!canonical) return '';
  const variants = EYEBROW_VARIANTS[canonical];
  if (!variants?.length) return canonical;
  if (!seed) return variants[0];
  return variants[hashSeed(`${canonical}\0${seed}`) % variants.length];
}

/**
 * @param {string} eyebrow - spotlight eyebrow text (canonical)
 * @returns {string}
 */
export function eyebrowTip(eyebrow) {
  if (!eyebrow) return '';
  return EYEBROW_TIPS[eyebrow] || '';
}

const PREFIX_TIPS = [
  { prefix: 'below Mendoza', key: 'below Mendoza' },
  { prefix: 'added in', key: 'added in' },
  { prefix: 'net adds in', key: 'net adds in' },
  { prefix: 'playtime in', key: 'playtime in' },
];

function normalizeLabel(label) {
  if (!label) return '';
  let s = String(label).trim();
  s = s.replace(/\s*\([^)]*\)\s*$/, '').trim();
  s = s.replace(/\s+\d{4}\s*$/, '').trim();
  return s;
}

/** Case-insensitive label → canonical METRIC_TIPS key. */
const METRIC_KEY_LOWER = Object.fromEntries(
  METRIC_KEYS.map((k) => [k.toLowerCase(), k]),
);

/**
 * Resolve a display label to its canonical METRIC_TIPS key, or '' if unknown.
 * @param {string} label
 * @returns {string}
 */
export function metricKeyForLabel(label) {
  if (!label) return '';
  if (METRIC_TIPS[label]) return label;
  const norm = normalizeLabel(label);
  if (METRIC_TIPS[norm]) return norm;
  const lower = label.toLowerCase();
  if (METRIC_KEY_LOWER[lower]) return METRIC_KEY_LOWER[lower];
  const normLower = norm.toLowerCase();
  if (METRIC_KEY_LOWER[normLower]) return METRIC_KEY_LOWER[normLower];
  for (const { prefix, key } of PREFIX_TIPS) {
    if (label.startsWith(prefix) || norm.startsWith(prefix)) return key;
  }
  if (label === 'hot' || label === 'warm' || label === 'cold') {
    return 'finish streak';
  }
  return '';
}

function tipFromMap(label) {
  const key = metricKeyForLabel(label);
  return key ? METRIC_TIPS[key] : '';
}

/**
 * @param {string} label - marquee chip label
 * @returns {string}
 */
export function marqueeTip(label) {
  if (!label) return '';
  const fromMap = tipFromMap(label);
  if (fromMap) return fromMap;
  return '';
}

function stripHtml(html) {
  return String(html ?? '')
    .replace(/<[^>]+>/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Resolve insight ticker HTML to its canonical METRIC_TIPS key, or '' if unknown.
 * @param {string} html
 * @returns {string}
 */
export function metricKeyForInsight(html) {
  const text = stripHtml(html);
  if (!text) return '';
  const colon = text.indexOf(':');
  const concept = colon >= 0 ? text.slice(0, colon).trim() : text;
  const fromMap = metricKeyForLabel(concept) || metricKeyForLabel(text);
  if (fromMap) return fromMap;
  if (text.includes('yrs to clear at your pace') || text.includes('to clear at your pace')) {
    return metricKeyForLabel('to clear at your pace');
  }
  if (text.includes('work-weeks') || text.startsWith('Backlog =')) {
    return metricKeyForLabel('Backlog =');
  }
  if (text.startsWith('Finish backlog by age')) {
    return '';
  }
  if (text.startsWith('~') && text.includes('yrs to clear')) {
    return metricKeyForLabel('to clear at your pace');
  }
  if (text.includes('still untouched') || text.startsWith('Added')) {
    return metricKeyForLabel('Added');
  }
  return metricKeyForLabel(concept);
}

/**
 * @param {string} html - insight pill inner HTML
 * @returns {string}
 */
export function insightTip(html) {
  const text = stripHtml(html);
  if (!text) return '';
  const colon = text.indexOf(':');
  const concept = colon >= 0 ? text.slice(0, colon).trim() : text;
  const fromMap = tipFromMap(concept) || tipFromMap(text);
  if (fromMap) return fromMap;
  if (text.includes('yrs to clear at your pace') || text.includes('to clear at your pace')) {
    return METRIC_TIPS['to clear at your pace'];
  }
  if (text.includes('work-weeks') || text.startsWith('Backlog =')) {
    return METRIC_TIPS['Backlog ='];
  }
  if (text.startsWith('Finish backlog by age')) {
    return 'Years to clear backlog at your recent finish pace vs your age (lifetime framing).';
  }
  if (text.startsWith('~') && text.includes('yrs to clear')) {
    return METRIC_TIPS['to clear at your pace'];
  }
  if (text.includes('still untouched') || text.startsWith('Added')) {
    return METRIC_TIPS['Added'];
  }
  return marqueeTip(concept);
}
