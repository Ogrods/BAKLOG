/**
 * Global color theme — persisted in localStorage, applied via html[data-theme].
 * Boot IIFE in index.html mirrors KEY for FOUC-free first paint.
 */

import { COLOR_THEME_KEY } from './state.js';
import { BAKLOG_THEME_CHANGE } from './custom-events.js';
import { proFeaturesUnlocked } from './auth-gate.js';

export { COLOR_THEME_KEY };

export const THEME_CHANGE_EVENT = BAKLOG_THEME_CHANGE;

/** Free profile-menu themes (always selectable). */
export const FREE_THEMES = ['default', 'dark', 'log-jammin', 'ember', 'synthwave', 'terminal'];

/** Pro-gated bonus palettes. */
export const PRO_THEMES = ['storybook', 'sapphire', 'emerald'];

export const THEMES = [...FREE_THEMES, ...PRO_THEMES];

/** @deprecated renamed to log-jammin */
const LEGACY_THEME_ALIASES = { timber: 'log-jammin' };

export const THEME_LABELS = {
  default: 'Default',
  dark: 'Midnight (OLED)',
  'log-jammin': "Log Jammin'",
  ember: 'Ember',
  synthwave: 'Synthwave',
  terminal: 'Terminal',
  storybook: 'Storybook',
  sapphire: 'Sapphire',
  emerald: 'Emerald',
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
  storybook: { bg: '#3d2613', accent: '#7ec96a', accent2: '#e0ba8c' },
  sapphire: { bg: '#0a1030', accent: '#5b8cff', accent2: '#818cf8' },
  emerald: { bg: '#04160f', accent: '#34d399', accent2: '#d9b44a' },
};

export function isProTheme(id) {
  return PRO_THEMES.includes(id);
}

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

/** Raw stored id (after alias resolve). Does not apply Pro entitlement clamp. */
export function getStoredColorTheme() {
  try {
    const v = localStorage.getItem(themeStorageKey());
    return resolveThemeId(v);
  } catch {
    return 'default';
  }
}

function effectiveTheme(stored) {
  if (isProTheme(stored) && !proFeaturesUnlocked()) return 'default';
  return stored;
}

export function getColorTheme() {
  return effectiveTheme(getStoredColorTheme());
}

/**
 * Persist and apply a theme. Pro themes require entitlement; returns false if blocked.
 * @returns {boolean}
 */
export function setColorTheme(theme) {
  const t = resolveThemeId(theme);
  if (isProTheme(t) && !proFeaturesUnlocked()) return false;
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
  return true;
}

/** Sync <html> from storage (module load after head IIFE). Clamps Pro themes when locked without wiping storage. */
export function applyColorThemeFromStorage() {
  const stored = getStoredColorTheme();
  const next = effectiveTheme(stored);
  const prev = document.documentElement.getAttribute('data-theme');
  document.documentElement.setAttribute('data-theme', next);
  if (next !== prev && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: { theme: next } }));
  }
}
