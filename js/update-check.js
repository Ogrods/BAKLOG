/** Boot + manual update checks against GET /api/update-check (frozen installs only for boot banner). */

import { escapeHtml } from './dom-util.js';

export const UPDATE_BANNER_DISMISS_KEY = 'baklog.updateBannerDismissed';

/**
 * @param {unknown} data
 * @returns {{ ok: true, current: string, latest: string | null, updateAvailable: boolean, url: string | null } | { ok: false, error: string }}
 */
export function parseUpdateCheckResponse(data) {
  if (!data || typeof data !== 'object') {
    return { ok: false, error: 'Invalid update-check response' };
  }
  const err = typeof data.error === 'string' ? data.error.trim() : '';
  if (err) return { ok: false, error: err };
  const current = typeof data.current === 'string' ? data.current : '';
  const latest = typeof data.latest === 'string' && data.latest.trim() ? data.latest.trim() : null;
  const url = typeof data.url === 'string' && data.url.trim() ? data.url.trim() : null;
  return {
    ok: true,
    current,
    latest,
    updateAvailable: data.update_available === true,
    url,
  };
}

/** @param {{ current: string, latest: string | null, url: string | null }} parsed */
export function formatUpdateAvailableMessage(parsed) {
  const urlPart = parsed.url ? ` Download: ${parsed.url}` : '';
  return `Update available: v${parsed.latest} (you have v${parsed.current}).${urlPart}`;
}

/** @param {{ current: string }} parsed */
export function formatUpToDateMessage(parsed) {
  return `You're on the latest release (v${parsed.current}).`;
}

/**
 * @param {{ latest: string | null, url: string | null, current: string }} parsed
 */
export function renderUpdateBannerHtml(parsed) {
  const href = parsed.url || 'https://github.com/Ogrods/baklog/releases/latest';
  return (
    '<div class="migration-banner-body update-available-banner-body">' +
    `<span class="text-amber-400">BAKLOG v${escapeHtml(parsed.latest || '')} is available (you have v${escapeHtml(parsed.current)}).</span> ` +
    `<a href="${escapeHtml(href)}" class="text-sky-300 hover:underline" target="_blank" rel="noopener noreferrer">Download release</a>` +
    '<button type="button" class="update-available-banner-dismiss ml-2 text-slate-400 hover:text-slate-200" aria-label="Dismiss for this session">×</button>' +
    '</div>'
  );
}

export function dismissUpdateBannerForSession() {
  if (typeof sessionStorage !== 'undefined') sessionStorage.setItem(UPDATE_BANNER_DISMISS_KEY, '1');
  hideUpdateBanner();
}

export function hideUpdateBanner() {
  const banner = document.getElementById('updateAvailableBanner');
  if (!banner) return;
  banner.classList.add('hidden');
  banner.replaceChildren();
}

/**
 * @param {{ latest: string | null, url: string | null, current: string }} parsed
 */
export function showUpdateBanner(parsed) {
  if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(UPDATE_BANNER_DISMISS_KEY) === '1') {
    return;
  }
  const banner = document.getElementById('updateAvailableBanner');
  if (!banner) return;
  banner.innerHTML = renderUpdateBannerHtml(parsed);
  banner.classList.remove('hidden');
  banner.querySelector('.update-available-banner-dismiss')?.addEventListener('click', () => {
    dismissUpdateBannerForSession();
  });
}

/**
 * @param {{ source?: 'boot' | 'manual', frozen?: boolean, fetchFn?: typeof fetch, onManualMessage?: (msg: string, opts?: { error?: boolean }) => void }} [opts]
 */
export async function checkForUpdates(opts = {}) {
  const fetchFn = opts.fetchFn || fetch;
  const source = opts.source || 'manual';
  const frozen = opts.frozen === true;
  if (source === 'boot' && !frozen) return { skipped: true, reason: 'not-frozen' };

  try {
    const res = await fetchFn('/api/update-check');
    if (!res.ok) {
      const msg = `Could not check for updates (server returned ${res.status}).`;
      if (source === 'manual') opts.onManualMessage?.(msg, { error: true });
      return { ok: false, error: msg };
    }
    const data = await res.json().catch(() => ({}));
    const parsed = parseUpdateCheckResponse(data);
    if (!parsed.ok) {
      const msg = `Could not check for updates: ${parsed.error}`;
      if (source === 'manual') opts.onManualMessage?.(msg, { error: true });
      return { ok: false, error: parsed.error };
    }
    if (parsed.updateAvailable) {
      if (source === 'boot') showUpdateBanner(parsed);
      else opts.onManualMessage?.(formatUpdateAvailableMessage(parsed));
      return { ok: true, updateAvailable: true, parsed };
    }
    if (source === 'manual') opts.onManualMessage?.(formatUpToDateMessage(parsed));
    return { ok: true, updateAvailable: false, parsed };
  } catch (err) {
    const msg = `Update check failed: ${err?.message || err}`;
    if (source === 'manual') opts.onManualMessage?.(msg, { error: true });
    return { ok: false, error: msg };
  }
}

/** @internal Vitest helper */
export function _resetUpdateBannerForTests() {
  if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(UPDATE_BANNER_DISMISS_KEY);
  hideUpdateBanner();
}
