/**
 * Table render micro-benchmarks against perf-budget.json ceilings.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Window } from 'happy-dom';
import { syntheticSteamGames } from './fixtures/synthetic-games.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const budget = JSON.parse(fs.readFileSync(path.join(root, 'perf-budget.json'), 'utf8'));

function mountTableShell() {
  document.body.innerHTML = `
    <div id="rowCount"></div>
    <div id="rowCountTop"></div>
    <div id="bulkBar" class="hidden"><span id="bulkCount"></span><button id="bulkClear"></button></div>
    <nav id="alphaNav">
      ${'ABCDEFGHIJKLMNOPQRSTUVWXYZ#'.split('').map(l =>
        `<button type="button" class="alpha-nav-btn" data-letter="${l}">${l}</button>`,
      ).join('')}
    </nav>
    <div id="tableShell">
      <div id="tableWrap">
        <table class="games-table">
          <thead><th id="statusHeader">Status</th><th id="priceHeader">Price</th></thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>
    </div>
  `;
}

function setupWindow() {
  const win = new Window({ url: 'http://127.0.0.1:8765/?perf=1' });
  global.window = win;
  global.document = win.document;
  global.performance = win.performance;
  global.localStorage = win.localStorage;
  global.ResizeObserver = class {
    observe() {}
    disconnect() {}
  };
  global.requestAnimationFrame = (cb) => {
    cb(0);
    return 1;
  };
  global.cancelAnimationFrame = () => {};
  global.requestIdleCallback = (cb) => {
    cb();
    return 1;
  };
  global.cancelIdleCallback = () => {};
  global.setTimeout = (cb) => {
    if (typeof cb === 'function') cb();
    return 1;
  };
  global.clearTimeout = () => {};
  global.CSS = { escape: (s) => String(s).replace(/"/g, '\\"') };
  Object.defineProperty(win, 'innerHeight', { value: 800, configurable: true });
  vi.spyOn(win, 'scrollTo').mockImplementation(() => {});
  window.__baklogPerfForce = true;
  mountTableShell();
  return win;
}

async function seedState(count) {
  const { state } = await import('../js/state.js');
  state.activeView = 'library';
  state.allGames = syntheticSteamGames(count);
  state.wishlistGames = [];
  state.itchGames = [];
  state.dashboardDataReady = true;
  state.prefs = state.prefs || {};
  state.prefs.columns = { library: { score: false, mc: false } };
  state.prefs.storeFilter = '';
  state.prefs.genreFilters = [];
  state.prefs.genreFilterMode = 'any';
  state.prefs.dealOnSaleOnly = false;
  state.prefs.dealHistoricalLowOnly = false;
  state.prefs.dealHideOwned = false;
  state.prefs.dealMinDiscount = 0;
  state.prefs.dealMaxPrice = 100;
  state.prefs.hltbBucket = null;
  state.prefs.releaseYearFilter = '';
  state.sessionPrefs = state.sessionPrefs || {};
  state.sortKey = 'name';
  state.sortDir = 1;
  state.selectedKeys = new Set();
  state.crossStoreHiddenKeys = new Set();
  state.wishlistCrossStoreHiddenKeys = new Set();
  state.ownedNormNames = new Set();
  state.personal = state.personal || {};
  state.itadByKey = state.itadByKey || new Map();
  state.combinedPlaytime = state.combinedPlaytime || new Map();
  return state;
}

describe('table render perf', () => {
  beforeEach(() => {
    vi.resetModules();
    delete global.window;
    delete global.document;
    delete global.window?.__baklogPerf;
  });

  for (const count of [100, 500, 2000]) {
    it(`renderTable(${count} rows) stays under budget`, async () => {
      setupWindow();
      await seedState(count);
      const { renderTable } = await import('../js/table-ui.js');
      await renderTable({ force: true });
      const run = window.__baklogPerf?.last;
      expect(run).toBeTruthy();
      expect(run.totalMs).toBeLessThan(budget.tableRenderMs[String(count)]);
      if (count > 50) {
        expect(String(run.meta.paintPath || '')).toMatch(/virtual/);
      }
    });
  }
});
