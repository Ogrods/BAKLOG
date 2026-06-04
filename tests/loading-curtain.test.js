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
