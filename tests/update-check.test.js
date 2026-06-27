import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  parseUpdateCheckResponse,
  formatUpdateAvailableMessage,
  formatUpToDateMessage,
  renderUpdateBannerHtml,
  checkForUpdates,
  dismissUpdateBannerForSession,
  UPDATE_BANNER_DISMISS_KEY,
  _resetUpdateBannerForTests,
} from '../js/update-check.js';

beforeEach(() => {
  document.body.innerHTML = '<div id="updateAvailableBanner" class="migration-banner hidden"></div>';
  _resetUpdateBannerForTests();
});

describe('parseUpdateCheckResponse', () => {
  it('parses update available payload', () => {
    const parsed = parseUpdateCheckResponse({
      current: '0.8.25',
      latest: '0.8.26',
      update_available: true,
      url: 'https://github.com/Ogrods/baklog/releases/tag/v0.8.26',
    });
    expect(parsed).toEqual({
      ok: true,
      current: '0.8.25',
      latest: '0.8.26',
      updateAvailable: true,
      url: 'https://github.com/Ogrods/baklog/releases/tag/v0.8.26',
    });
  });

  it('returns error when API reports failure', () => {
    expect(parseUpdateCheckResponse({ error: 'rate limited' })).toEqual({
      ok: false,
      error: 'rate limited',
    });
  });
});

describe('checkForUpdates', () => {
  it('skips boot check when not frozen', async () => {
    const fetchFn = vi.fn();
    const result = await checkForUpdates({ source: 'boot', frozen: false, fetchFn });
    expect(result).toEqual({ skipped: true, reason: 'not-frozen' });
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('shows boot banner when frozen and update available', async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.25',
        latest: '0.8.26',
        update_available: true,
        url: 'https://example.com/release',
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    const banner = document.getElementById('updateAvailableBanner');
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.textContent).toContain('0.8.26');
    expect(banner.querySelector('a')?.href).toBe('https://example.com/release');
  });

  it('respects session dismiss for boot banner', async () => {
    sessionStorage.setItem(UPDATE_BANNER_DISMISS_KEY, '1');
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.25',
        latest: '0.8.26',
        update_available: true,
        url: 'https://example.com/release',
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(true);
  });

  it('routes manual messages through callback', async () => {
    const onManualMessage = vi.fn();
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.26',
        latest: '0.8.26',
        update_available: false,
      }),
    }));
    await checkForUpdates({ source: 'manual', onManualMessage, fetchFn });
    expect(onManualMessage).toHaveBeenCalledWith(formatUpToDateMessage({ current: '0.8.26' }));
  });
});

describe('renderUpdateBannerHtml', () => {
  it('escapes version strings in banner html', () => {
    const html = renderUpdateBannerHtml({
      current: '0.8.25',
      latest: '<bad>',
      url: 'https://example.com',
    });
    expect(html).toContain('&lt;bad&gt;');
    expect(html).not.toContain('<bad>');
  });
});

describe('formatUpdateAvailableMessage', () => {
  it('includes download url when present', () => {
    expect(formatUpdateAvailableMessage({
      current: '1.0.0',
      latest: '1.0.1',
      url: 'https://example.com/dl',
    })).toContain('https://example.com/dl');
  });
});

describe('dismissUpdateBannerForSession', () => {
  it('hides banner and sets session flag', () => {
    document.getElementById('updateAvailableBanner').classList.remove('hidden');
    dismissUpdateBannerForSession();
    expect(sessionStorage.getItem(UPDATE_BANNER_DISMISS_KEY)).toBe('1');
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(true);
  });
});
