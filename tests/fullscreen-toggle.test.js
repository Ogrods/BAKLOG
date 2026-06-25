import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  isFullscreenActive,
  syncFullscreenButton,
  toggleBrowserFullscreen,
} from '../js/fullscreen-toggle.js';

describe('fullscreen-toggle', () => {
  beforeEach(() => {
    document.body.innerHTML = '<button type="button" id="headerFullscreenBtn"></button>';
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: null,
    });
  });

  it('syncFullscreenButton reflects inactive state with TV icon', () => {
    const btn = document.getElementById('headerFullscreenBtn');
    syncFullscreenButton(btn);
    expect(btn.getAttribute('aria-pressed')).toBe('false');
    expect(btn.title).toBe('Full screen (F11)');
    expect(btn.querySelector('rect')).not.toBeNull();
  });

  it('syncFullscreenButton reflects active state with exit icon', () => {
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: document.documentElement,
    });
    const btn = document.getElementById('headerFullscreenBtn');
    syncFullscreenButton(btn);
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    expect(btn.title).toBe('Exit full screen (F11)');
    expect(btn.innerHTML).toContain('M9 4H4v5');
  });

  it('toggleBrowserFullscreen calls requestFullscreen when inactive', async () => {
    const requestFullscreen = vi.fn().mockResolvedValue(undefined);
    document.documentElement.requestFullscreen = requestFullscreen;
    await toggleBrowserFullscreen();
    expect(requestFullscreen).toHaveBeenCalledOnce();
    expect(isFullscreenActive()).toBe(false);
  });

  it('toggleBrowserFullscreen calls exitFullscreen when active', async () => {
    Object.defineProperty(document, 'fullscreenElement', {
      configurable: true,
      value: document.documentElement,
    });
    const exitFullscreen = vi.fn().mockResolvedValue(undefined);
    document.exitFullscreen = exitFullscreen;
    await toggleBrowserFullscreen();
    expect(exitFullscreen).toHaveBeenCalledOnce();
  });
});
