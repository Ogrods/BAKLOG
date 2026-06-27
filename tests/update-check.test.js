import { describe, expect, it, beforeEach, vi } from 'vitest';
import {
  parseUpdateCheckResponse,
  parseUpdateStatusResponse,
  formatUpdateAvailableMessage,
  formatUpToDateMessage,
  renderUpdateBannerHtml,
  renderUpdateModalHtml,
  renderUpdateReadyBannerHtml,
  renderUpdateProgressHtml,
  renderApplyBlockedHint,
  checkForUpdates,
  runInAppUpdateFlow,
  runApplyReadyUpdate,
  pollUpdateStatusUntilDone,
  pollPostApplyOutcome,
  discardReadyUpdate,
  POST_APPLY_RECOVERY_MESSAGE,
  dismissUpdateForVersion,
  isUpdateBannerDismissed,
  rememberDismissedVersion,
  confirmInstallUpdate,
  showUpdateModal,
  showReadyToInstallBanner,
  syncReadyUpdateFromStatus,
  cancelUpdateDownload,
  mapUpdateError,
  showUpdateToast,
  UPDATE_DISMISSED_VERSION_KEY,
  _resetUpdateBannerForTests,
} from '../js/update-check.js';

beforeEach(() => {
  document.body.innerHTML = '<div id="updateAvailableBanner" class="migration-banner hidden"></div>';
  _resetUpdateBannerForTests();
});

describe('parseUpdateCheckResponse', () => {
  it('parses update available payload with blocked reason metadata', () => {
    const parsed = parseUpdateCheckResponse({
      current: '0.8.25',
      latest: '0.8.26',
      update_available: true,
      url: 'https://github.com/Ogrods/BAKLOG/releases/tag/v0.8.26',
      download_url: 'https://github.com/Ogrods/BAKLOG/releases/download/v0.8.26/BAKLOG-win64.zip',
      sha256: 'abc',
      apply_supported: false,
      apply_blocked_reason: 'dev_runtime',
      apply_blocked_message: 'Updates install only in the desktop app, not the dev server.',
      runtime_label: 'dev',
      release_notes: 'Fixes',
      dismissed: false,
    });
    expect(parsed).toMatchObject({
      ok: true,
      latest: '0.8.26',
      applySupported: false,
      applyBlockedReason: 'dev_runtime',
      releaseNotes: 'Fixes',
    });
  });

  it('returns error when API reports failure', () => {
    expect(parseUpdateCheckResponse({ error: 'rate limited' })).toEqual({
      ok: false,
      error: 'rate limited',
    });
  });
});

describe('renderApplyBlockedHint', () => {
  it('shows helper text when apply is blocked', () => {
    const html = renderApplyBlockedHint({
      applySupported: false,
      applyBlockedMessage: 'Use the release page.',
    });
    expect(html).toContain('Use the release page.');
  });

  it('returns empty string when apply is supported', () => {
    expect(renderApplyBlockedHint({ applySupported: true })).toBe('');
  });
});

describe('isUpdateBannerDismissed', () => {
  it('respects server dismissed flag', () => {
    expect(isUpdateBannerDismissed({ latest: '0.8.26', dismissed: true })).toBe(true);
  });

  it('respects localStorage version mirror', () => {
    rememberDismissedVersion('0.8.26');
    expect(isUpdateBannerDismissed({ latest: '0.8.26' })).toBe(true);
    expect(isUpdateBannerDismissed({ latest: '0.8.27' })).toBe(false);
    expect(localStorage.getItem(UPDATE_DISMISSED_VERSION_KEY)).toBe('0.8.26');
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

  it('skips boot check when pref disabled', async () => {
    const fetchFn = vi.fn();
    const result = await checkForUpdates({ source: 'boot', frozen: true, checkOnBoot: false, fetchFn });
    expect(result).toEqual({ skipped: true, reason: 'pref-disabled' });
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
        dismissed: false,
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    const banner = document.getElementById('updateAvailableBanner');
    expect(banner.classList.contains('hidden')).toBe(false);
    expect(banner.textContent).toContain('0.8.26');
    expect(banner.querySelector('.update-available-banner-apply')).not.toBeNull();
    expect(banner.textContent).toContain("What's new");
  });

  it('shows blocked hint on banner when apply unsupported', async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.25',
        latest: '0.8.26',
        update_available: true,
        apply_supported: false,
        apply_blocked_message: 'Use the release page.',
        dismissed: false,
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    const banner = document.getElementById('updateAvailableBanner');
    expect(banner.textContent).toContain('Use the release page.');
    expect(banner.querySelector('.update-available-banner-apply')).toBeNull();
  });

  it('respects per-version dismiss for boot banner', async () => {
    rememberDismissedVersion('0.8.26');
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.25',
        latest: '0.8.26',
        update_available: true,
        url: 'https://example.com/release',
        dismissed: true,
      }),
    }));
    await checkForUpdates({ source: 'boot', frozen: true, fetchFn });
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(true);
  });

  it('opens modal on manual update available', async () => {
    const fetchFn = vi.fn(async (url) => {
      if (url === '/api/update/status') {
        return {
          ok: true,
          json: async () => ({ phase: 'idle', ready: false, can_apply: false }),
        };
      }
      return {
        ok: true,
        json: async () => ({
          current: '0.8.25',
          latest: '0.8.26',
          update_available: true,
          url: 'https://example.com/release',
          release_notes: 'Bug fixes',
        }),
      };
    });
    await checkForUpdates({ source: 'manual', fetchFn });
    expect(document.getElementById('updateReleaseModal')).not.toBeNull();
    expect(document.body.textContent).toContain('Bug fixes');
  });

  it('manual check prefers ready banner over update modal', async () => {
    const fetchFn = vi.fn(async (url) => {
      if (url === '/api/update/status') {
        return {
          ok: true,
          json: async () => ({
            phase: 'ready',
            ready: true,
            can_apply: true,
            version: '0.8.26',
          }),
        };
      }
      throw new Error(`unexpected ${url}`);
    });
    const result = await checkForUpdates({ source: 'manual', fetchFn });
    expect(result.ready).toBe(true);
    expect(document.getElementById('updateReleaseModal')).toBeNull();
    expect(document.getElementById('updateAvailableBanner').textContent).toContain('0.8.26');
  });

  it('snoozes version when modal Remind me later is clicked', async () => {
    const fetchFn = vi.fn(async (url, init) => {
      if (url === '/api/update-check') {
        return {
          ok: true,
          json: async () => ({
            current: '0.8.25',
            latest: '0.8.26',
            update_available: true,
          }),
        };
      }
      if (url === '/api/update/dismiss') {
        return { ok: true, json: async () => ({ ok: true }) };
      }
      throw new Error(`unexpected ${url}`);
    });
    await checkForUpdates({ source: 'manual', fetchFn });
    document.querySelector('.update-modal-later')?.click();
    await Promise.resolve();
    expect(localStorage.getItem(UPDATE_DISMISSED_VERSION_KEY)).toBe('0.8.26');
    expect(document.getElementById('updateReleaseModal').classList.contains('hidden')).toBe(true);
  });

  it('routes manual up-to-date through onNotice callback', async () => {
    const onNotice = vi.fn();
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        current: '0.8.26',
        latest: '0.8.26',
        update_available: false,
      }),
    }));
    await checkForUpdates({ source: 'manual', onNotice, fetchFn });
    expect(onNotice).toHaveBeenCalledWith(formatUpToDateMessage({ current: '0.8.26' }));
  });
});

describe('confirmInstallUpdate', () => {
  it('resolves true when user confirms in modal', async () => {
    const promise = confirmInstallUpdate();
    document.querySelector('.update-install-confirm')?.click();
    await expect(promise).resolves.toBe(true);
  });

  it('resolves false when user declines in modal', async () => {
    const promise = confirmInstallUpdate();
    document.querySelector('.update-install-decline')?.click();
    await expect(promise).resolves.toBe(false);
  });
});

describe('runInAppUpdateFlow', () => {
  it('downloads, waits for ready, and applies after in-app confirm', async () => {
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
      if (url === '/api/update/apply-result') {
        return { ok: true, json: async () => ({ ok: true, result: { ok: true, version: '0.8.26' } }) };
      }
      throw new Error(`unexpected fetch ${url}`);
    });
    const result = await runInAppUpdateFlow({
      fetchFn,
      sleepMs: 1,
      timeoutMs: 1,
      confirmInstall: async () => true,
    });
    expect(result.applied).toBe(true);
    expect(fetchFn).toHaveBeenCalledWith('/api/update/apply', { method: 'POST' });
  });

  it('shows ready banner when user declines install confirm', async () => {
    const fetchFn = vi.fn(async (url) => {
      if (url === '/api/update/download') {
        return { ok: true, json: async () => ({ ok: true }) };
      }
      if (url === '/api/update/status') {
        return {
          ok: true,
          json: async () => ({
            phase: 'ready',
            ready: true,
            can_apply: true,
            version: '0.8.26',
          }),
        };
      }
      return { ok: false, json: async () => ({}) };
    });
    const result = await runInAppUpdateFlow({
      fetchFn,
      sleepMs: 1,
      confirmInstall: async () => false,
    });
    expect(result.applied).toBe(false);
    const banner = document.getElementById('updateAvailableBanner');
    expect(banner.textContent).toContain('Install');
    expect(banner.textContent).toContain('0.8.26');
  });

  it('uses only updateAvailableBanner during download (not boot error banner)', async () => {
    document.body.innerHTML += '<div id="bootErrorBanner" class="migration-banner hidden"></div>';
    let calls = 0;
    const fetchFn = vi.fn(async (url) => {
      if (url === '/api/update/status') {
        calls += 1;
        if (calls === 1) {
          return {
            ok: true,
            json: async () => ({
              phase: 'downloading',
              progress_bytes: 5,
              total_bytes: 10,
            }),
          };
        }
        return {
          ok: true,
          json: async () => ({
            phase: 'ready',
            ready: true,
            can_apply: true,
            version: '0.8.26',
          }),
        };
      }
      return { ok: false, json: async () => ({}) };
    });
    const onNotice = vi.fn();
    const status = await pollUpdateStatusUntilDone({ fetchFn, sleepMs: 1, onNotice });
    expect(status.phase).toBe('ready');
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(false);
    expect(document.getElementById('bootErrorBanner').classList.contains('hidden')).toBe(true);
    expect(onNotice).not.toHaveBeenCalled();
  });
});

describe('renderUpdateBannerHtml', () => {
  it('escapes version strings and includes remind me later', () => {
    const html = renderUpdateBannerHtml({
      current: '0.8.25',
      latest: '<bad>',
      url: 'https://example.com',
      applySupported: true,
    });
    expect(html).toContain('&lt;bad&gt;');
    expect(html).toContain('update-available-banner-apply');
    expect(html).toContain('Remind me later');
    expect(html).toContain("What's new");
  });
});

describe('renderUpdateProgressHtml', () => {
  it('includes cancel button while downloading', () => {
    const html = renderUpdateProgressHtml({
      ok: true,
      phase: 'downloading',
      progressBytes: 50,
      totalBytes: 100,
      version: null,
      error: null,
      ready: false,
      canApply: false,
    }, { cancellable: true });
    expect(html).toContain('Cancel download');
  });
});

describe('renderUpdateReadyBannerHtml', () => {
  it('includes install action', () => {
    const html = renderUpdateReadyBannerHtml({ version: '0.8.26' });
    expect(html).toContain('Install');
    expect(html).toContain('0.8.26');
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

describe('dismissUpdateForVersion', () => {
  it('stores version locally and posts to server', async () => {
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true }) }));
    await dismissUpdateForVersion('0.8.26', { fetchFn });
    expect(localStorage.getItem(UPDATE_DISMISSED_VERSION_KEY)).toBe('0.8.26');
    expect(fetchFn).toHaveBeenCalledWith('/api/update/dismiss', expect.objectContaining({ method: 'POST' }));
  });
});

describe('syncReadyUpdateFromStatus', () => {
  it('shows ready banner when server reports ready package', async () => {
    const fetchFn = vi.fn(async () => ({
      ok: true,
      json: async () => ({
        phase: 'ready',
        ready: true,
        can_apply: true,
        version: '0.8.26',
      }),
    }));
    const result = await syncReadyUpdateFromStatus({ fetchFn, frozen: true });
    expect(result.ready).toBe(true);
    expect(document.getElementById('updateAvailableBanner').textContent).toContain('0.8.26');
  });
});

describe('cancelUpdateDownload', () => {
  it('posts cancel and hides banner', async () => {
    document.getElementById('updateAvailableBanner').classList.remove('hidden');
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, cancelled: true }) }));
    const onNotice = vi.fn();
    await cancelUpdateDownload({ fetchFn, onNotice });
    expect(fetchFn).toHaveBeenCalledWith('/api/update/cancel', { method: 'POST' });
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(true);
    expect(onNotice).toHaveBeenCalledWith('Update download cancelled.');
  });
});

describe('mapUpdateError', () => {
  it('maps fetchers_running code', () => {
    expect(mapUpdateError('raw', 'fetchers_running')).toContain('Fetcher health');
  });
});

describe('showUpdateToast', () => {
  it('creates toast element with message', () => {
    showUpdateToast('All good');
    const el = document.getElementById('updateNoticeToast');
    expect(el).not.toBeNull();
    expect(el.textContent).toBe('All good');
    expect(el.classList.contains('update-notice-toast-info')).toBe(true);
  });
});

describe('renderUpdateModalHtml', () => {
  it('uses Remind me later label', () => {
    const html = renderUpdateModalHtml({
      current: '0.8.25',
      latest: '0.8.26',
      url: 'https://example.com',
      applySupported: true,
    });
    expect(html).toContain('Remind me later');
  });

  it('hides Update now when fetchers are in flight', () => {
    const html = renderUpdateModalHtml({
      current: '0.8.25',
      latest: '0.8.26',
      url: 'https://example.com',
      applySupported: true,
      fetchersInFlight: true,
    });
    expect(html).not.toContain('Update now');
    expect(html).toContain('Fetcher health');
  });
});

describe('renderUpdateReadyBannerHtml', () => {
  it('includes discard download action', () => {
    const html = renderUpdateReadyBannerHtml({ version: '0.8.26' });
    expect(html).toContain('Discard download');
  });
});

describe('discardReadyUpdate', () => {
  it('posts discard-ready and hides banner', async () => {
    document.getElementById('updateAvailableBanner').classList.remove('hidden');
    const fetchFn = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true, discarded: true }) }));
    const onNotice = vi.fn();
    await discardReadyUpdate({ fetchFn, onNotice });
    expect(fetchFn).toHaveBeenCalledWith('/api/update/discard-ready', { method: 'POST' });
    expect(document.getElementById('updateAvailableBanner').classList.contains('hidden')).toBe(true);
    expect(onNotice).toHaveBeenCalledWith('Downloaded update discarded.');
  });
});

describe('pollPostApplyOutcome', () => {
  it('shows recovery copy after timeout', async () => {
    vi.useFakeTimers();
    const fetchFn = vi.fn(async (url) => ({
      ok: true,
      json: async () => (
        url === '/api/update/apply-result'
          ? { ok: true, result: null }
          : { ok: true, phase: 'applying' }
      ),
    }));
    const onNotice = vi.fn();
    const promise = pollPostApplyOutcome({
      fetchFn,
      onNotice,
      timeoutMs: 50,
      sleepMs: 10,
    });
    await vi.advanceTimersByTimeAsync(60);
    await promise;
    expect(onNotice).toHaveBeenCalledWith(POST_APPLY_RECOVERY_MESSAGE);
    expect(document.getElementById('updateAvailableBanner').textContent).toContain('BAKLOG Tray');
    vi.useRealTimers();
  });
});
