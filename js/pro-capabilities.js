/**
 * Pro capability flags from GET /api/config.
 * Sync pair labels: CAPABILITY_MARKETING ↔ js/sponsored-deals.js PRO_PROMO tierCompare.
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
let _proSettings = { cloudMirrorEnabled: false };

/** @param {Record<string, { status?: string, enabled?: boolean }>} caps */
export function setCapabilitiesFromConfig(caps) {
  _capabilities = caps && typeof caps === 'object' ? { ...caps } : {};
}

/** @param {Record<string, unknown>} settings */
export function setProSettingsFromConfig(settings) {
  if (settings && typeof settings === 'object') {
    _proSettings = {
      cloudMirrorEnabled: settings.cloudMirrorEnabled === true,
    };
  }
}

export function getCapabilities() {
  return { ..._capabilities };
}

export function getProSettings() {
  return { ..._proSettings };
}

/** @param {Partial<{ cloudMirrorEnabled: boolean }>} next */
export function setProSettings(next) {
  if (!next || typeof next !== 'object') return getProSettings();
  if ('cloudMirrorEnabled' in next) {
    _proSettings.cloudMirrorEnabled = next.cloudMirrorEnabled === true;
  }
  return getProSettings();
}

/**
 * @param {string} id e.g. queue_bulk_refresh, cloud_sync_mirror
 */
export function hasCapability(id) {
  const cap = _capabilities[id];
  if (!cap || typeof cap !== 'object') return false;
  return !!cap.enabled;
}

export function capabilityStatus(id) {
  const cap = _capabilities[id];
  if (!cap || typeof cap !== 'object') return 'soon';
  if (cap.status === 'live') return 'live';
  if (cap.status === 'off') return 'off';
  return 'soon';
}

export function listLiveCapabilities() {
  return Object.entries(_capabilities)
    .filter(([, cap]) => cap?.status === 'live' && cap?.enabled)
    .map(([id]) => id);
}

export function listComingCapabilities() {
  return Object.entries(_capabilities)
    .filter(([, cap]) => cap?.status === 'soon' || cap?.status === 'coming')
    .map(([id]) => id);
}
