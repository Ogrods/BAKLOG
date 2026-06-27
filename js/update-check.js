/** Boot + in-app update flow against /api/update-check and /api/update/* (frozen installs). */

import { baklogFetch } from './api-client.js';
import { escapeHtml } from './dom-util.js';

export const UPDATE_BANNER_DISMISS_KEY = 'baklog.updateBannerDismissed';
const UPDATE_STATUS_POLL_MS = 800;

/**
 * @param {unknown} data
 * @returns {{
 *   ok: true,
 *   current: string,
 *   latest: string | null,
 *   updateAvailable: boolean,
 *   url: string | null,
 *   downloadUrl: string | null,
 *   sha256: string | null,
 *   applySupported: boolean,
 *   runtimeLabel: string | null,
 * } | { ok: false, error: string }}
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
  const downloadUrl = typeof data.download_url === 'string' && data.download_url.trim()
    ? data.download_url.trim()
    : null;
  const sha256 = typeof data.sha256 === 'string' && data.sha256.trim() ? data.sha256.trim() : null;
  return {
    ok: true,
    current,
    latest,
    updateAvailable: data.update_available === true,
    url,
    downloadUrl,
    sha256,
    applySupported: data.apply_supported === true,
    runtimeLabel: typeof data.runtime_label === 'string' ? data.runtime_label : null,
  };
}

/** @param {{ current: string, latest: string | null, url: string | null }} parsed */
export function formatUpdateAvailableMessage(parsed) {
  const urlPart = parsed.url ? ` Release page: ${parsed.url}` : '';
  return `Update available: v${parsed.latest} (you have v${parsed.current}).${urlPart}`;
}

/** @param {{ current: string }} parsed */
export function formatUpToDateMessage(parsed) {
  return `You're on the latest release (v${parsed.current}).`;
}

/**
 * @param {{
 *   latest: string | null,
 *   url: string | null,
 *   current: string,
 *   applySupported?: boolean,
 * }} parsed
 */
export function renderUpdateBannerHtml(parsed) {
  const href = parsed.url || 'https://github.com/Ogrods/BAKLOG/releases/latest';
  const updateBtn = parsed.applySupported
    ? '<button type="button" class="update-available-banner-apply ml-2 text-sky-300 hover:underline">Update now</button>'
    : '';
  return (
    '<div class="migration-banner-body update-available-banner-body">' +
    `<span class="text-amber-400">BAKLOG v${escapeHtml(parsed.latest || '')} is available (you have v${escapeHtml(parsed.current)}).</span> ` +
    updateBtn +
    `<a href="${escapeHtml(href)}" class="update-available-banner-release ml-2 text-sky-300 hover:underline" target="_blank" rel="noopener noreferrer">Release page</a>` +
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

function setBannerMessage(html, { hidden = false } = {}) {
  const banner = document.getElementById('updateAvailableBanner');
  if (!banner) return;
  banner.innerHTML = html;
  banner.classList.toggle('hidden', hidden);
}

/**
 * @param {{ latest: string | null, url: string | null, current: string, applySupported?: boolean }} parsed
 * @param {{ onManualMessage?: (msg: string, opts?: { error?: boolean }) => void, fetchFn?: typeof fetch }} [handlers]
 */
export function showUpdateBanner(parsed, handlers = {}) {
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
  banner.querySelector('.update-available-banner-apply')?.addEventListener('click', () => {
    runInAppUpdateFlow({ onManualMessage: handlers.onManualMessage, fetchFn: handlers.fetchFn }).catch(() => {});
  });
}

/**
 * @param {unknown} data
 */
export function parseUpdateStatusResponse(data) {
  if (!data || typeof data !== 'object') {
    return { ok: false, error: 'Invalid update status response' };
  }
  return {
    ok: true,
    phase: typeof data.phase === 'string' ? data.phase : 'idle',
    progressBytes: Number(data.progress_bytes) || 0,
    totalBytes: data.total_bytes == null ? null : Number(data.total_bytes) || 0,
    version: typeof data.version === 'string' ? data.version : null,
    error: typeof data.error === 'string' ? data.error : null,
    ready: data.ready === true,
    canApply: data.can_apply === true,
  };
}

function formatProgressMessage(status) {
  if (status.phase === 'downloading') {
    if (status.totalBytes) {
      const pct = Math.min(100, Math.round((status.progressBytes / status.totalBytes) * 100));
      return `Downloading update… ${pct}%`;
    }
    return 'Downloading update…';
  }
  if (status.phase === 'ready') return 'Update downloaded and verified. Ready to install.';
  if (status.phase === 'applying') return 'Installing update and restarting BAKLOG…';
  if (status.phase === 'error') return status.error || 'Update failed';
  return '';
}

/**
 * @param {{ fetchFn?: typeof fetch, onManualMessage?: (msg: string, opts?: { error?: boolean }) => void, sleepMs?: number }} [opts]
 */
export async function pollUpdateStatusUntilDone(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;
  const sleepMs = opts.sleepMs ?? UPDATE_STATUS_POLL_MS;
  for (;;) {
    const res = await fetchFn('/api/update/status');
    const data = await res.json().catch(() => ({}));
    const status = parseUpdateStatusResponse(data);
    if (!status.ok) throw new Error(status.error || 'Update status unavailable');
    const msg = formatProgressMessage(status);
    if (msg) {
      setBannerMessage(
        `<div class="migration-banner-body"><span class="text-amber-400">${escapeHtml(msg)}</span></div>`,
      );
      opts.onManualMessage?.(msg);
    }
    if (status.phase === 'ready' || status.phase === 'error' || status.phase === 'idle') {
      return status;
    }
    if (status.phase === 'applying') return status;
    await new Promise((resolve) => setTimeout(resolve, sleepMs));
  }
}

/**
 * @param {{ fetchFn?: typeof fetch, onManualMessage?: (msg: string, opts?: { error?: boolean }) => void }} [opts]
 */
export async function runInAppUpdateFlow(opts = {}) {
  const fetchFn = opts.fetchFn || baklogFetch;
  const onManualMessage = opts.onManualMessage;

  const downloadRes = await fetchFn('/api/update/download', { method: 'POST' });
  const downloadPayload = await downloadRes.json().catch(() => ({}));
  if (!downloadRes.ok || downloadPayload.ok === false) {
    const msg = downloadPayload.error || `Download request failed (${downloadRes.status})`;
    onManualMessage?.(msg, { error: true });
    throw new Error(msg);
  }

  const status = await pollUpdateStatusUntilDone(opts);
  if (status.phase === 'error') {
    const msg = status.error || 'Update download failed';
    onManualMessage?.(msg, { error: true });
    throw new Error(msg);
  }
  if (!status.canApply) {
    const msg = 'Update package is not ready to apply';
    onManualMessage?.(msg, { error: true });
    throw new Error(msg);
  }

  const confirmed = typeof window !== 'undefined'
    ? window.confirm('Install the downloaded update and restart BAKLOG now? Your library data will be kept.')
    : true;
  if (!confirmed) {
    onManualMessage?.('Update ready — choose Update now when you want to install.');
    return { ok: true, ready: true, applied: false };
  }

  const applyRes = await fetchFn('/api/update/apply', { method: 'POST' });
  const applyPayload = await applyRes.json().catch(() => ({}));
  if (!applyRes.ok || applyPayload.ok === false) {
    const msg = applyPayload.error || `Apply request failed (${applyRes.status})`;
    onManualMessage?.(msg, { error: true });
    throw new Error(msg);
  }

  setBannerMessage(
    '<div class="migration-banner-body"><span class="text-amber-400">Installing update and restarting BAKLOG…</span></div>',
  );
  onManualMessage?.('Installing update and restarting BAKLOG…');
  return { ok: true, applied: true, version: applyPayload.version || status.version };
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
      if (source === 'boot') {
        showUpdateBanner(parsed, {
          onManualMessage: opts.onManualMessage,
          fetchFn: opts.fetchFn || baklogFetch,
        });
      } else {
        opts.onManualMessage?.(formatUpdateAvailableMessage(parsed));
      }
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
