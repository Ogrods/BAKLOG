/** Dev vs installed runtime chip (shared localhost origin awareness). */

import { escapeHtml } from './dom-util.js';
import { hasPersistedMixedRuntimeErrors } from './error-boundary.js';

const DISMISS_KEY = 'baklog.runtimeModeBannerDismissed';

/**
 * @param {{ runtime_label?: string, frozen?: boolean, portable?: boolean, data_dir_path?: string | null }} cfg
 */
export function syncRuntimeModeBanner(cfg = {}) {
  const slot = document.getElementById('runtimeModeBanner');
  if (!slot) return;
  if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem(DISMISS_KEY) === '1') {
    slot.classList.add('hidden');
    slot.replaceChildren();
    return;
  }

  const mode = cfg.runtime_label || (cfg.frozen === true ? 'installed' : 'dev');
  const dataPath = typeof cfg.data_dir_path === 'string' ? cfg.data_dir_path.trim() : '';
  const pathTip = dataPath ? ` Library files: ${dataPath}.` : '';
  let label;
  let detail;

  if (mode === 'dev') {
    label = 'Dev server';
    detail =
      `python server.py is serving this tab.${pathTip} ` +
      'Use PORT=8766 and BAKLOG_DATA_DIR=...\\BAKLOG-Dev so prefs stay off the installed app (see User guide).';
  } else if (hasPersistedMixedRuntimeErrors(cfg.frozen === true)) {
    label = 'Mixed sessions';
    detail =
      'An older shared error log still has entries from both dev and installed runs. Clear site data for 127.0.0.1, or use a private window when switching.';
  } else {
    slot.classList.add('hidden');
    slot.replaceChildren();
    return;
  }

  slot.classList.remove('hidden');
  slot.innerHTML =
    `<span class="runtime-mode-banner-label">${escapeHtml(label)}</span>` +
    `<span class="runtime-mode-banner-detail">${escapeHtml(detail)}</span>` +
    `<button type="button" class="runtime-mode-banner-dismiss" aria-label="Dismiss for this session">×</button>`;
  slot.title = detail;
  const btn = slot.querySelector('.runtime-mode-banner-dismiss');
  btn?.addEventListener('click', () => {
    sessionStorage.setItem(DISMISS_KEY, '1');
    slot.classList.add('hidden');
    slot.replaceChildren();
  });
}

export function _resetRuntimeModeBannerForTests() {
  if (typeof sessionStorage !== 'undefined') sessionStorage.removeItem(DISMISS_KEY);
}

/** @internal Vitest helper */
export function _runtimeBannerLabel(cfg) {
  const mode = cfg.runtime_label || (cfg.frozen === true ? 'installed' : 'dev');
  if (mode === 'dev') return 'Dev server';
  if (hasPersistedMixedRuntimeErrors(cfg.frozen === true)) return 'Mixed sessions';
  return '';
}
