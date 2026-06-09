/**
 * Global color theme — persisted in localStorage, applied via html[data-theme].
 * Boot IIFE in index.html mirrors KEY for FOUC-free first paint.
 */

export const COLOR_THEME_KEY = 'baklog-color-theme';

export const THEMES = ['default', 'dark', 'timber', 'ember', 'synthwave', 'terminal'];

export const THEME_LABELS = {
  default: 'Default',
  dark: 'Midnight (OLED)',
  timber: 'Timber',
  ember: 'Ember',
  synthwave: 'Synthwave',
  terminal: 'Terminal',
};

/** Swatch preview colors — mirror html[data-theme] tokens in app.css; update both if themes change.
 *  ember accent2 intentionally uses --brand-grad start (#fbbf24), not --accent-bright. */
export const THEME_SWATCHES = {
  default: { bg: '#0f172a', accent: '#38bdf8', accent2: '#0ea5e9' },
  dark: { bg: '#000000', accent: '#ffffff', accent2: '#d4d4d8' },
  timber: { bg: '#171410', accent: '#2f8049', accent2: '#47703a' },
  ember: { bg: '#0f0d0b', accent: '#f97316', accent2: '#fbbf24' },
  synthwave: { bg: '#14101f', accent: '#ff2e88', accent2: '#a855f7' },
  terminal: { bg: '#0c1413', accent: '#34e6b0', accent2: '#22d3ee' },
};

export function getColorTheme() {
  try {
    const v = localStorage.getItem(COLOR_THEME_KEY);
    return THEMES.includes(v) ? v : 'default';
  } catch {
    return 'default';
  }
}

import { BAKLOG_THEME_CHANGE } from './custom-events.js';

export const THEME_CHANGE_EVENT = BAKLOG_THEME_CHANGE;

export function setColorTheme(theme) {
  const t = THEMES.includes(theme) ? theme : 'default';
  const prev = document.documentElement.getAttribute('data-theme');
  try {
    localStorage.setItem(COLOR_THEME_KEY, t);
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
