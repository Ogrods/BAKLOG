/** Shared free-claim outbound link helpers (admin + app). */
import { isSafeHttpUrl } from './dom-util.js';

export const EPIC_MOBILE_STORE = 'epic_mobile';

export function isEpicMobileStore(store) {
  return String(store || '').trim().toLowerCase() === EPIC_MOBILE_STORE;
}

/** Sanitized platform URLs for epic_mobile rows (ios/android, http(s) only). */
export function normalizeClaimUrls(raw) {
  if (!raw || typeof raw !== 'object') return {};
  const out = {};
  for (const key of ['ios', 'android']) {
    const val = String(raw[key] || '').trim();
    if (isSafeHttpUrl(val)) out[key] = val;
  }
  return out;
}

export function hasValidClaimLinks(item) {
  if (isEpicMobileStore(item?.store)) {
    return Object.keys(normalizeClaimUrls(item?.claim_urls)).length > 0;
  }
  return isSafeHttpUrl(item?.claim_url);
}

export function claimPlatformHost(url) {
  try {
    return new URL(String(url || '')).hostname.toLowerCase();
  } catch {
    return '';
  }
}

/** Guess which platform bucket a single URL belongs to (admin store migration). */
export function inferClaimUrlPlatform(url) {
  const host = claimPlatformHost(url);
  if (host.includes('apps.apple.com') || host.includes('itunes.apple.com')) return 'ios';
  if (host.includes('play.google.com')) return 'android';
  return null;
}

export function missingClaimLinkFields(item) {
  const missing = [];
  if (isEpicMobileStore(item?.store)) {
    if (!Object.keys(normalizeClaimUrls(item?.claim_urls)).length) {
      missing.push('claim_urls');
    }
    return missing;
  }
  if (!String(item?.claim_url || '').trim()) missing.push('claim_url');
  return missing;
}
