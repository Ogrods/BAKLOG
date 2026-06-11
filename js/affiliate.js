/**
 * Affiliate tagging for BAKLOG-built store-page links only.
 *
 * ITAD deal URLs (next.isthereanydeal.com redirects) are NOT tagged here —
 * they already carry ITAD's affiliate tag and the API ToS forbids altering
 * them. High-commission marketplaces that only appear as ITAD deal shops
 * (Fanatical, GMG, etc.) are monetized via the Sponsored feed instead.
 */

/* ============================================================================
 *  GO LIVE — paste your affiliate credentials here, then save.
 * ----------------------------------------------------------------------------
 *  A program turns ON automatically the moment its value is non-empty — there
 *  is no separate "enabled" flag to flip. Leave a value blank to keep that
 *  program OFF (URLs pass through untouched).
 *
 *    param programs    -> paste the raw tag value (e.g. your creator id).
 *    deeplink programs -> paste a tracking template that contains "{url}";
 *                         BAKLOG substitutes the encoded store URL for {url}.
 *                         A deeplink template WITHOUT {url} stays OFF.
 *
 *  After filling values: `npm test`, then mirror curated/sponsors.json ->
 *  landing/sponsors.json if you also touched sponsor creatives.
 * ==========================================================================*/

/** @type {Record<string, string>} */
export const AFFILIATE_CREDENTIALS = {
  // --- Store-link programs (tag the dashboard's own store buttons) ---------
  // GOG (deeplink): AdTraction template with {url}, or a branded af.gog.com link.
  //   e.g. 'https://go.adt231.net/c/<AID>/<CID>/<MID>?url={url}'
  gog: '',
  // Epic Games Store (param): your Support-A-Creator creator id.  e.g. 'baklog'
  epic: '',
  // Humble Store (deeplink): Impact template with {url}.
  //   e.g. 'https://humblebundle.pxf.io/c/<AID>/<CID>/<MID>?u={url}'
  humble: '',

  // --- Sponsor-feed programs (reference only) ------------------------------
  // These shops are surfaced via the Sponsored feed (curated/sponsors.json),
  // not by BAKLOG's own store buttons, so filling them here has no effect on
  // the dashboard. Add a sponsor creative with a pre-tagged `url` instead.
  fanatical: '',
  gmg: '',
  gamesplanet: '',
};

/** Hosts that must never be re-tagged (ITAD deal redirects). */
const BLOCKED_HOST_SUFFIXES = ['isthereanydeal.com'];

/**
 * @typedef {Object} AffiliateRule
 * @property {string} id            Key into AFFILIATE_CREDENTIALS.
 * @property {string} shop
 * @property {string[]} hosts       Host suffixes this rule matches.
 * @property {'param'|'deeplink'} mode
 * @property {string} [param]       Query param name (param mode only).
 * @property {boolean} [storeLink]  True when storeUrlForGame can build this host.
 * @property {string} network
 * @property {string} notes
 */

/** @type {AffiliateRule[]} */
export const AFFILIATE_RULES = [
  {
    id: 'gog',
    shop: 'GOG',
    hosts: ['gog.com'],
    mode: 'deeplink',
    storeLink: true,
    network: 'AdTraction (or CJ)',
    notes: '6% net sales, 7-day last-click. Email affiliate@gog.com + AdTraction signup.',
  },
  {
    id: 'epic',
    shop: 'Epic Games Store',
    hosts: ['store.epicgames.com', 'epicgames.com'],
    mode: 'param',
    param: 'epic_creator_id',
    storeLink: true,
    network: 'Epic Support-A-Creator',
    notes: 'Min 5% (dev-set), $100 payout floor, 14-day attribution. Gated ~1k followers on one eligible social platform (eligible).',
  },
  {
    id: 'humble',
    shop: 'Humble Store',
    hosts: ['humblebundle.com'],
    mode: 'deeplink',
    storeLink: true,
    network: 'Impact',
    notes: '~5.6% storefront, bundles 5.6%+, 30-day cookie.',
  },
  // Reference-only: these shops only surface as ITAD deal links — use Sponsored feed.
  {
    id: 'fanatical',
    shop: 'Fanatical',
    hosts: ['fanatical.com'],
    mode: 'param',
    param: 'ref',
    storeLink: false,
    network: 'CJ Affiliate / Awin',
    notes: 'Sponsor-feed only (up to 5%, 30d). Not produced by storeUrlForGame.',
  },
  {
    id: 'gmg',
    shop: 'Green Man Gaming',
    hosts: ['greenmangaming.com'],
    mode: 'deeplink',
    storeLink: false,
    network: 'Awin',
    notes: 'Sponsor-feed only (5% new / 2% returning, 30d).',
  },
  {
    id: 'gamesplanet',
    shop: 'GamesPlanet',
    hosts: ['gamesplanet.com'],
    mode: 'param',
    param: 'ref',
    storeLink: false,
    network: 'Direct',
    notes: 'Sponsor-feed only (5-10%). Gated ~4k followers for approval.',
  },
];

function hostMatches(host, suffix) {
  const h = host.toLowerCase();
  const s = suffix.toLowerCase();
  return h === s || h.endsWith('.' + s);
}

function isBlockedHost(host) {
  return BLOCKED_HOST_SUFFIXES.some(suffix => hostMatches(host, suffix));
}

/** Trimmed credential string for a rule, or '' when unset. */
function credentialFor(rule) {
  const raw = AFFILIATE_CREDENTIALS[rule.id];
  return typeof raw === 'string' ? raw.trim() : '';
}

/**
 * A rule is live when its credential is filled and valid for its mode:
 * param rules need any non-empty value; deeplink rules need a template
 * containing the {url} placeholder.
 */
function ruleIsLive(rule) {
  const cred = credentialFor(rule);
  if (!cred) return false;
  if (rule.mode === 'param') return true;
  return cred.includes('{url}');
}

/** First live rule whose host suffix matches, else null. */
function ruleForHost(host) {
  if (isBlockedHost(host)) return null;
  for (const rule of AFFILIATE_RULES) {
    if (!ruleIsLive(rule)) continue;
    if (rule.hosts.some(suffix => hostMatches(host, suffix))) return rule;
  }
  return null;
}

function applyParam(url, rule) {
  const value = credentialFor(rule);
  try {
    const u = new URL(url);
    if (u.searchParams.get(rule.param) === value) return url;
    u.searchParams.set(rule.param, value);
    return u.toString();
  } catch {
    return url;
  }
}

function applyDeeplink(url, rule) {
  const template = credentialFor(rule);
  const prefix = template.split('{url}')[0];
  if (prefix && url.startsWith(prefix)) return url;
  return template.replace('{url}', encodeURIComponent(url));
}

/**
 * Apply maintainer affiliate tag when enrolled. Returns rawUrl unchanged for
 * non-http(s), blocked hosts (ITAD), Steam, unknown shops, and disabled rules.
 *
 * @param {string} rawUrl
 * @returns {string}
 */
export function affiliateUrl(rawUrl) {
  if (typeof rawUrl !== 'string' || !rawUrl.trim()) return rawUrl;
  let host;
  try {
    const u = new URL(rawUrl.trim());
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return rawUrl;
    host = u.hostname;
  } catch {
    return rawUrl;
  }
  const rule = ruleForHost(host);
  if (!rule) return rawUrl;
  return rule.mode === 'deeplink' ? applyDeeplink(rawUrl, rule) : applyParam(rawUrl, rule);
}

/** True when at least one affiliate rule is live (honest disclosure copy). */
export function hasLiveAffiliates() {
  return AFFILIATE_RULES.some(ruleIsLive);
}

/** Ids of currently-live programs (diagnostics / honest disclosure). */
export function liveAffiliateShops() {
  return AFFILIATE_RULES.filter(ruleIsLive).map(rule => rule.shop);
}
