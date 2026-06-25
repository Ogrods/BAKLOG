import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

describe('liftBootCurtain reveal nudge', () => {
  beforeEach(() => {
    document.documentElement.setAttribute('data-boot-loading', 'wishlist');
    document.body.innerHTML = `
      <div id="bootLoadingOverlay" aria-busy="true"></div>
      <div id="tableShell">
        <table><tbody id="tbody">
          <tr><td>Game A</td></tr>
          <tr><td>Game B</td></tr>
        </tbody></table>
      </div>`;
    vi.stubGlobal('requestAnimationFrame', (cb) => {
      cb();
      return 0;
    });
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {});
  });

  afterEach(() => {
    document.documentElement.removeAttribute('data-boot-loading');
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('removes boot curtain and nudges scroll when tbody has rows', async () => {
    const { liftBootCurtain } = await import('../js/loading-curtain.js');
    liftBootCurtain(0, { force: true });
    expect(document.documentElement.hasAttribute('data-boot-loading')).toBe(false);
    expect(window.scrollTo).toHaveBeenCalled();
  });
});

describe('releaseViewOverlayWhenReady', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="viewLoadingOverlay" class="app-view-overlay show" aria-hidden="false"></div>
      <button class="view-tab" data-view="library">Library</button>`;
    vi.stubGlobal('requestAnimationFrame', (cb) => {
      cb();
      return 0;
    });
  });

  afterEach(() => {
    document.body.innerHTML = '';
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('waits for ready work, reveals chrome, then lifts the scrim', async () => {
    const { state } = await import('../js/state.js');
    state.activeView = 'library';
    const steps = [];
    const { releaseViewOverlayWhenReady } = await import('../js/loading-curtain.js');
    await releaseViewOverlayWhenReady(Promise.resolve(), 'library', {
      onBeforeHide: () => steps.push('before'),
      onAfterHide: () => steps.push('after'),
    });
    expect(steps).toEqual(['before', 'after']);
    expect(document.getElementById('viewLoadingOverlay').classList.contains('show')).toBe(false);
  });

  it('does not lift when active view changed mid-flight', async () => {
    const { state } = await import('../js/state.js');
    state.activeView = 'wishlist';
    const { releaseViewOverlayWhenReady } = await import('../js/loading-curtain.js');
    await releaseViewOverlayWhenReady(Promise.resolve(), 'library');
    expect(document.getElementById('viewLoadingOverlay').classList.contains('show')).toBe(true);
  });

  it('cached switchView clears abandoned overlay when superseded navigation bails', async () => {
    const { state } = await import('../js/state.js');
    state.activeView = 'dashboard';
    document.querySelector('.view-tab').disabled = true;
    const { hideViewOverlay } = await import('../js/loading-curtain.js');
    hideViewOverlay();
    expect(document.getElementById('viewLoadingOverlay').classList.contains('show')).toBe(false);
    expect(document.querySelector('.view-tab').disabled).toBe(false);
  });
});
