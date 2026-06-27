import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  parseUpdateCheckResponse,
  parseUpdateStatusResponse,
  formatUpdateAvailableMessage,
  formatUpToDateMessage,
  renderUpdateBannerHtml,
  checkForUpdates,
  runInAppUpdateFlow,
  pollUpdateStatusUntilDone,
  dismissUpdateBannerForSession,
  UPDATE_BANNER_DISMISS_KEY,
  _resetUpdateBannerForTests,
} from '../js/update-check.js';

beforeEach(() => {
  document.body.innerHTML = '<div id="updateAvailableBanner" class="migration-banner hidden"></div>';
  _resetUpdateBannerForTests();
});

describe('parseUpdateCheckResponse', () => {
  it('parses update available payload with download metadata', () => {
    const parsed = parseUpdateCheckResponse({
      current: '0.8.25',
      latest: '0.8.26',
      update_available: true,
      url: 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26',
      download_url: 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip',
      sha256: 'abc',
      apply_supported: true,
      runtime_label: 'installed',
    });
    expect(parsed).toEqual({
      ok: true,
      current: '0.8.25',
      latest: '0.8.26',
      updateAvailable: true,
      url: 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26',
      downloadUrl: 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip',
      sha256: 'abc',
      applySupported: true,
      runtimeLabel: 'installed',
    });
  });

  it('returns error when API reports failure', () => {
    expect(parseUpdateCheckResponse({ error: 'rate limited' })).toEqual({
      ok: false,
      error: 'rate limited',
    });
  });
});

describe('parseUpdateStatusResponse', () => {
  it('parses ready status', () => {
    expect(parseUpdateStatusResponse({
      phase: 'ready',
      progress_bytes: 100,
      total_bytes: 100,
      ready: true,
      can_apply: true,
      version: '0.8.26',
    })).toMatchObject({ ok: true, phase: 'ready', canApply: true, ready: true });
  });
});

describe('checkForUpdates', () => {
  it('skips boot check when not frozen', async () => {
    const fetchFn = vi.fn();
    const result = await checkForUpdates({ source: 'boot', frozen: false, fetchFn });
    expect(result).toEqual({ skipped: true, reason: 'not-frozen' });
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it('shows boot banner with update now when apply supported', async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.25',
        latest: '0.8.26',
        update_available: true,
        url: 'https://example.com/release',
        apply_supported: true,
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    const banner = document.getElementById('updateAvailableBanner');
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.textContent).toContain('0.8.26');
    expect(banner.querySelector('.update-available-banner-apply')).not.toBeNull();
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

describe('runInAppUpdateFlow', () => {
  it('downloads, waits for ready, and applies after confirm', async () => {
    vi.stubGlobal('confirm', vi.fn(() => true));
    const fetchFn = vi.fn(async (url, init) => {
      if (url === '/api/update/download' && init?.method === 'POST') {
        return { ok: true, json: async () => ({ ok: true, started: true }) };
      }
      if (url === '/api/update/status') {
        return {
          ok: true,
          json: async () => ({
            phase: 'ready',
            ready: true,
            can_apply: true,
            progress_bytes: 10,
            total_bytes: 10,
            version: '0.8.26',
          }),
        };
      }
      if (url === '/api/update/apply' && init?.method === 'POST') {
        return { ok: true, json: async () => ({ ok: true, applying: true, version: '0.8.26' }) };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const result = await runInAppUpdateFlow({ fetchFn, sleepMs: 1 });
    expect(result.applied).toBe(true);
    expect(fetchFn).toHaveBeenCalledWith('/api/update/apply', { method: 'POST' });
    vi.unstubAllGlobals();
  });

  it('aborts apply when user declines confirm', async () => {
    vi.stubGlobal('confirm', vi.fn(() => false));
    const fetchFn = vi.fn(async (url, init) => {
      if (url === '/api/update/download') {
        return { ok: true, json: async () => ({ ok: true }) };
      }
      if (url === '/api/update/status') {
        return {
          ok: true,
          json: async () => ({ phase: 'ready', ready: true, can_apply: true }),
        };
      }
      return { ok: false, json: async () => ({}) };
    });
    const result = await runInAppUpdateFlow({ fetchFn, sleepMs: 1 });
    expect(result.applied).toBe(false);
    expect(fetchFn.mock.calls.some(([u]) => u === '/api/update/apply')).toBe(false);
    vi.unstubAllGlobals();
  });
});

describe('renderUpdateBannerHtml', () => {
  it('escapes version strings in banner html', () => {
    const html = renderUpdateBannerHtml({
      current: '0.8.25',
      latest: '<bad>',
      url: 'https://example.com',
      applySupported: true,
    });
    expect(html).toContain('&lt;bad&gt;');
    expect(html).toContain('update-available-banner-apply');
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

describe('pollUpdateStatusUntilDone', () => {
  it('returns when phase becomes ready', async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({ phase: 'ready', ready: true, can_apply: true }),
    }));
    const status = await pollUpdateStatusUntilDone({ fetchFn, sleepMs: 1 });
    expect(status.phase).toBe('ready');
  });
});
