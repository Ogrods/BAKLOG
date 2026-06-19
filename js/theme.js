/**
 * Global color theme — persisted in localStorage, applied via html[data-theme].
 * Boot IIFE in index.html mirrors KEY for FOUC-free first paint.
 */

import { COLOR_THEME_KEY } from './state.js';
import { BAKLOG_THEME_CHANGE } from './custom-events.js';

export { COLOR_THEME_KEY };

export const THEME_CHANGE_EVENT = BAKLOG_THEME_CHANGE;

export const THEMES = ['default', 'dark', 'log-jammin', 'ember', 'synthwave', 'terminal'];

/** @deprecated renamed to log-jammin */
const LEGACY_THEME_ALIASES = { timber: 'log-jammin' };

export const THEME_LABELS = {
  default: 'Default',
  dark: 'Midnight (OLED)',
  'log-jammin': "Log Jammin'",
  ember: 'Ember',
  synthwave: 'Synthwave',
  terminal: 'Terminal',
};

/** Swatch preview colors — mirror html[data-theme] tokens in app.css; update both if themes change.
 *  ember accent2 intentionally uses --brand-grad start (#fbbf24), not --accent-bright. */
export const THEME_SWATCHES = {
  default: { bg: '#0f172a', accent: '#38bdf8', accent2: '#0ea5e9' },
  dark: { bg: '#000000', accent: '#ffffff', accent2: '#d4d4d8' },
  'log-jammin': { bg: '#171410', accent: '#2f8049', accent2: '#47703a' },
  ember: { bg: '#0f0d0b', accent: '#f97316', accent2: '#fbbf24' },
  synthwave: { bg: '#14101f', accent: '#ff2e88', accent2: '#a855f7' },
  terminal: { bg: '#0c1413', accent: '#34e6b0', accent2: '#22d3ee' },
};

function resolveThemeId(stored) {
  if (THEMES.includes(stored)) return stored;
  const alias = LEGACY_THEME_ALIASES[stored];
  return alias && THEMES.includes(alias) ? alias : 'default';
}

function themeStorageKey() {
  try {
    const pid = localStorage.getItem('baklog-active-profile') || 'default';
    const suffix = pid && pid !== 'default' ? `:${pid}` : '';
    return `${COLOR_THEME_KEY}${suffix}`;
  } catch {
    return COLOR_THEME_KEY;
  }
}

export function getColorTheme() {
  try {
    const v = localStorage.getItem(themeStorageKey());
    return resolveThemeId(v);
  } catch {
    return 'default';
  }
}

export function setColorTheme(theme) {
  const t = resolveThemeId(theme);
  const prev = document.documentElement.getAttribute('data-theme');
  try {
    localStorage.setItem(themeStorageKey(), t);
  } catch {
    /* ignore */
  }
  document.documentElement.setAttribute('data-theme', t);
  if (t !== prev && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { theme: t } }));
  }
}

/** Sync <html> from storage (module load after head IIFE). */
export function applyColorThemeFromStorage() {
  setColorTheme(getColorTheme());
}
