import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';

describe('table density', () => {
  beforeEach(async () => {
    const win = new Window({ url: 'http://127.0.0.1:8765/' });
    global.window = win;
    global.document = win.document;
    global.ResizeObserver = class {
      observe() {}
      disconnect() {}
    };
    global.requestAnimationFrame = (cb) => {
      cb(0);
      return 1;
    };
    global.cancelAnimationFrame = () => {};
    document.body.innerHTML = `<div id="tableWrap" style="width:400px"><table class="games-table" style="width:900px"><tr><td>x</td></tr></table></div>`;
    const wrap = document.getElementById('tableWrap');
    Object.defineProperty(wrap, 'clientWidth', { configurable: true, get: () => 400 });
    Object.defineProperty(wrap, 'scrollWidth', { configurable: true, get: () => {
      const tier = Number(wrap.dataset.density || 0);
      // Simulate wider table until density hides enough columns
      return tier >= 2 ? 380 : 900;
    }});
    vi.resetModules();
  });

  it('densityHideIdsForTier grows by tier', async () => {
    const { densityHideIdsForTier, DENSITY_MAX_TIER } = await import('../js/table-density.js');
    expect(densityHideIdsForTier(0)).toEqual([]);
    expect(densityHideIdsForTier(1)).toEqual(['notes', 'genres']);
    expect(densityHideIdsForTier(2)).toContain('released');
    expect(densityHideIdsForTier(2)).toContain('lastplayed');
    expect(densityHideIdsForTier(3)).toContain('price');
    expect(densityHideIdsForTier(4)).toContain('steam');
    expect(densityHideIdsForTier(5)).toContain('played');
    expect(densityHideIdsForTier(6)).toContain('hltb');
    expect(densityHideIdsForTier(99).length).toBe(densityHideIdsForTier(DENSITY_MAX_TIER).length);
  });

  it('pins prevent densityWouldHide', async () => {
    const { state } = await import('../js/state.js');
    state.prefs = { columnDensityPins: {} };
    const {
      densityWouldHide,
      setDensityPinned,
      setDensityTier,
    } = await import('../js/table-density.js');
    setDensityTier(2);
    expect(densityWouldHide('library', 'notes')).toBe(true);
    setDensityPinned('library', 'notes', true);
    expect(densityWouldHide('library', 'notes')).toBe(false);
  });

  it('syncTableDensity raises tier until overflow clears', async () => {
    const { syncTableDensity, getDensityTier } = await import('../js/table-density.js');
    const apply = vi.fn();
    const tier = syncTableDensity(apply, 'library');
    expect(tier).toBe(2);
    expect(getDensityTier()).toBe(2);
    expect(apply).toHaveBeenCalled();
  });

  it('bumps density when game title cell is crushed', async () => {
    const wrap = document.getElementById('tableWrap');
    Object.defineProperty(wrap, 'scrollWidth', { configurable: true, get: () => 400 });
    wrap.innerHTML = `<table class="games-table"><tbody><tr>
      <td class="game-name-cell">Title</td>
    </tr></tbody></table>`;
    const cell = wrap.querySelector('.game-name-cell');
    Object.defineProperty(cell, 'getBoundingClientRect', {
      configurable: true,
      value: () => ({ width: 80, height: 20, top: 0, left: 0, right: 80, bottom: 20 }),
    });
    const { measureNeedsMoreDensity, measureGameTitleTooNarrow } = await import('../js/table-density.js');
    expect(measureGameTitleTooNarrow(wrap)).toBe(true);
    expect(measureNeedsMoreDensity(wrap)).toBe(true);
  });

  it('applyColumnVisibility composes prefs + density', async () => {
    const { state } = await import('../js/state.js');
    state.prefs = { columns: {}, columnDensityPins: {} };
    const { setDensityTier } = await import('../js/table-density.js');
    const { applyColumnVisibility } = await import('../js/table-columns.js');
    setDensityTier(1);
    applyColumnVisibility('library');
    const wrap = document.getElementById('tableWrap');
    expect(wrap.classList.contains('table-hide-notes')).toBe(true);
    expect(wrap.classList.contains('table-hide-genres')).toBe(true);
    expect(wrap.classList.contains('table-hide-price')).toBe(false);
  });
});
