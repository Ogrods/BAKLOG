import { describe, it, expect, beforeEach } from 'vitest';
import {
  COLOR_THEME_KEY,
  THEMES,
  FREE_THEMES,
  PRO_THEMES,
  THEME_SWATCHES,
  THEME_LABELS,
  isProTheme,
  getColorTheme,
  getStoredColorTheme,
  setColorTheme,
  applyColorThemeFromStorage,
} from '../js/theme.js';
import { __applyConfigEntitlementForTest } from '../js/auth-gate.js';

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    __applyConfigEntitlementForTest({ plan: 'free' });
  });

  it('defaults to default when storage is empty', () => {
    expect(getColorTheme()).toBe('default');
  });

  it('falls back to default for invalid stored values', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'neon');
    expect(getColorTheme()).toBe('default');
  });

  it('setColorTheme persists and sets data-theme on html', () => {
    setColorTheme('log-jammin');
    expect(localStorage.getItem(COLOR_THEME_KEY)).toBe('log-jammin');
    expect(document.documentElement.getAttribute('data-theme')).toBe('log-jammin');
    expect(getColorTheme()).toBe('log-jammin');
  });

  it('migrates legacy timber theme id', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'timber');
    expect(getColorTheme()).toBe('log-jammin');
    setColorTheme('timber');
    expect(localStorage.getItem(COLOR_THEME_KEY)).toBe('log-jammin');
  });

  it('applyColorThemeFromStorage syncs from localStorage', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'ember');
    applyColorThemeFromStorage();
    expect(document.documentElement.getAttribute('data-theme')).toBe('ember');
  });

  it('exposes six free themes and three Pro bonus palettes', () => {
    expect(FREE_THEMES).toEqual(['default', 'dark', 'log-jammin', 'ember', 'synthwave', 'terminal']);
    expect(PRO_THEMES).toEqual(['storybook', 'sapphire', 'emerald']);
    expect(THEMES).toEqual([...FREE_THEMES, ...PRO_THEMES]);
  });

  it('keeps THEME_SWATCHES and THEME_LABELS in parity with THEMES', () => {
    for (const id of THEMES) {
      expect(THEME_LABELS[id], id).toBeTruthy();
      expect(THEME_SWATCHES[id]?.bg, id).toBeTruthy();
      expect(THEME_SWATCHES[id]?.accent, id).toBeTruthy();
      expect(THEME_SWATCHES[id]?.accent2, id).toBeTruthy();
    }
  });

  it('marks Storybook / Sapphire / Emerald as Pro themes', () => {
    expect(isProTheme('storybook')).toBe(true);
    expect(isProTheme('default')).toBe(false);
  });

  it('blocks setting a Pro theme when not entitled', () => {
    expect(setColorTheme('sapphire')).toBe(false);
    expect(localStorage.getItem(COLOR_THEME_KEY)).toBeNull();
    expect(document.documentElement.getAttribute('data-theme')).toBeNull();
  });

  it('clamps stored Pro theme to default when not entitled without wiping storage', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'storybook');
    expect(getStoredColorTheme()).toBe('storybook');
    expect(getColorTheme()).toBe('default');
    applyColorThemeFromStorage();
    expect(document.documentElement.getAttribute('data-theme')).toBe('default');
    expect(localStorage.getItem(COLOR_THEME_KEY)).toBe('storybook');
  });

  it('applies Pro themes when entitled', () => {
    __applyConfigEntitlementForTest({ plan: 'pro' });
    expect(setColorTheme('emerald')).toBe(true);
    expect(getColorTheme()).toBe('emerald');
    expect(document.documentElement.getAttribute('data-theme')).toBe('emerald');
  });

  it('restores stored Pro theme after entitlement returns', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'sapphire');
    __applyConfigEntitlementForTest({ plan: 'free' });
    applyColorThemeFromStorage();
    expect(document.documentElement.getAttribute('data-theme')).toBe('default');
    __applyConfigEntitlementForTest({ plan: 'pro' });
    applyColorThemeFromStorage();
    expect(document.documentElement.getAttribute('data-theme')).toBe('sapphire');
  });
});
