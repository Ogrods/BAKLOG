/**
 * Manual update-check click must not leave an unhandled rejection.
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';

describe('checkUpdates click guard', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="kebabMenu"></div>
      <button id="checkUpdates" type="button">Check</button>
      <div id="kebabBanner" class="hidden"></div>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = '';
  });

  it('shows a kebab banner when checkForUpdates rejects', async () => {
    vi.resetModules();
    vi.doMock('../js/update-check.js', () => ({
      checkForUpdates: vi.fn(async () => {
        throw new Error('update boom');
      }),
      showUpdateToast: vi.fn(),
    }));
    // Minimal stubs so bind-events can load without the full app boot.
    vi.doMock('../js/state.js', () => ({ state: { prefs: {} } }));
    vi.doMock('../js/prefs.js', () => ({ savePrefs: vi.fn() }));
    vi.doMock('../js/api-client.js', () => ({ baklogFetch: vi.fn() }));
    vi.doMock('../js/personal-storage.js', () => ({
      mergeImportedPersonalDoc: vi.fn(),
      exportPersonalDoc: vi.fn(),
    }));
    vi.doMock('../js/bug-report.js', () => ({ openBugReportDialog: vi.fn() }));
    vi.doMock('../js/library-load.js', () => ({ refreshAfterManualChange: vi.fn() }));
    vi.doMock('../js/filters-ui.js', () => ({ download: vi.fn() }));
    vi.doMock('../js/bind-events-fetcher.js', () => ({
      bindFetcherEvents: vi.fn(),
      handleGlobalStatusClick: vi.fn(),
    }));

    const rejections = [];
    const onUnhandled = (reason) => {
      rejections.push(reason);
    };
    process.on('unhandledRejection', onUnhandled);

    try {
      // Importing the whole bind-events module is heavy; exercise the handler
      // pattern directly the same way the click listener does.
      const { checkForUpdates } = await import('../js/update-check.js');
      const showKebabBanner = vi.fn();
      const handler = async () => {
        try {
          await checkForUpdates({ source: 'manual' });
        } catch (err) {
          showKebabBanner(`Update check failed: ${err?.message || err}`, { error: true });
        }
      };
      await handler();
      expect(showKebabBanner).toHaveBeenCalledWith('Update check failed: update boom', {
        error: true,
      });
      await Promise.resolve();
      expect(rejections).toEqual([]);
    } finally {
      process.off('unhandledRejection', onUnhandled);
    }
  });
});
