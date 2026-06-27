/**
 * Pro capability flags from GET /api/config.
 * Sync pair: CAPABILITY_MARKETING ↔ js/sponsored-deals.js PRO_PROMO tierCompare.
 */

export const CAPABILITY_MARKETING = {
  no_ads: 'Sponsored deal cards',
  queue_bulk_refresh: 'Manual store refresh',
  scheduled_stale_refresh: 'Refresh while app is closed',
  bonus_claimables: 'Claimable Now (full games)',
  deep_achievement_sync: 'Deep achievement/trophy sync',
  cloud_sync_mirror: 'Cloud sync',
  deal_watchlist_alerts: 'Deal/watchlist alerts',
};

let _capabilities = {};

/** @param {Record<string, { status?: string, enabled?: boolean }>} caps */
export function setCapabilitiesFromConfig(caps) {
  _capabilities = caps && typeof caps === 'object' ? { ...caps } : {};
}

export function getCapabilities() {
  return { ..._capabilities };
}

/**
 * @param {string} id — e.g. queue_bulk_refresh, cloud_sync_mirror
 */
export function hasCapability(id) {
  const cap = _capabilities[id];
  if (!cap || typeof cap !== 'object') return false;
  return !!cap.enabled;
}

export function capabilityStatus(id) {
  const cap = _capabilities[id];
  if (!cap || typeof cap !== 'object') return 'coming';
  return cap.status === 'live' ? 'live' : 'coming';
}

export function listLiveCapabilities() {
  return Object.entries(_capabilities)
    .filter(([, cap]) => cap?.status === 'live' && cap?.enabled)
    .map(([id]) => id);
}

export function listComingCapabilities() {
  return Object.entries(_capabilities)
    .filter(([, cap]) => cap?.status === 'coming')
    .map(([id]) => id);
}
