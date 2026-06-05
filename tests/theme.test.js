import { describe, it, expect, beforeEach } from 'vitest';
import {
  COLOR_THEME_KEY,
  THEMES,
  getColorTheme,
  setColorTheme,
  applyColorThemeFromStorage,
} from '../js/theme.js';

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('defaults to default when storage is empty', () => {
    expect(getColorTheme()).toBe('default');
  });

  it('falls back to default for invalid stored values', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'neon');
    expect(getColorTheme()).toBe('default');
  });

  it('setColorTheme persists and sets data-theme on html', () => {
    setColorTheme('timber');
    expect(localStorage.getItem(COLOR_THEME_KEY)).toBe('timber');
    expect(document.documentElement.getAttribute('data-theme')).toBe('timber');
    expect(getColorTheme()).toBe('timber');
  });

  it('applyColorThemeFromStorage syncs from localStorage', () => {
    localStorage.setItem(COLOR_THEME_KEY, 'ember');
    applyColorThemeFromStorage();
    expect(document.documentElement.getAttribute('data-theme')).toBe('ember');
  });

  it('exposes all six themes', () => {
    expect(THEMES).toEqual(['default', 'dark', 'timber', 'ember', 'synthwave', 'terminal']);
  });
});
