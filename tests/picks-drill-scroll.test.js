/**
 * Drilling into the table from a Picks card (focusGame) must land the viewport
 * on the picked row, not "much too high" near the top of the page.
 *
 * Regression guard: for a virtual (long) list the pending row target was being
 * consumed via getBoundingClientRect (scrollRowToCenter). When the giant top
 * spacer isn't laid out at measure time the rect reads ~0 and the page scrolls
 * to the top. The deterministic index math (spacer height + measured row
 * height) that dashboard drills already use must be used here too.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

function makeList(n) {
  return Array.from({ length: n }, (_, i) => ({
    store: "steam",
    id: String(i),
    name: `Game ${i}`,
  }));
}

describe("picks drill scroll target", () => {
  let win;
  let scrollToSpy;
  const LIST = makeList(120);

  beforeEach(async () => {
    vi.resetModules();
    vi.doMock("../js/table-query.js", async (importOriginal) => {
      const actual = await importOriginal();
      return {
        ...actual,
        collectTableParams: () => ({}),
        queryGamesAsync: async () => LIST,
        queryGames: () => LIST,
        buildQueryContext: () => ({}),
        querySourceForView: () => "library",
      };
    });

    win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.performance = win.performance;
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
      if (typeof cb === "function") cb();
      return 1;
    };
    global.clearTimeout = () => {};
    global.CSS = { escape: (s) => String(s).replace(/"/g, '\\"') };

    Object.defineProperty(win, "innerHeight", { value: 800, configurable: true });
    scrollToSpy = vi.spyOn(win, "scrollTo").mockImplementation(() => {});

    document.body.innerHTML = `
      <div id="rowCount"></div>
      <div id="bulkBar" class="hidden"><span id="bulkCount"></span></div>
      <nav id="alphaNav"></nav>
      <section id="picksSection"><div id="picksGrid"></div></section>
      <div id="toolbarSection" style="height:80px">toolbar</div>
      <div id="tableShell" style="margin-top:400px">
        <div id="tableWrap">
          <table class="games-table">
            <thead><th id="statusHeader">Status</th><th id="priceHeader">Price</th></thead>
            <tbody id="tbody"></tbody>
          </table>
        </div>
      </div>
    `;
  });

  it("focusGame on an unpainted virtual row scrolls down to the row, not to the top", async () => {
    const { state } = await import("../js/state.js");
    const { focusGame, renderTable } = await import("../js/table-ui.js");
    state.activeView = "library";
    state.prefs = state.prefs || {};
    state.prefs.columns = { library: { score: false, mc: false } };
    state.sessionPrefs = state.sessionPrefs || {};
    state.sortKey = "name";
    state.sortDir = 1;
    state.selectedKeys = new Set();
    state.crossStoreHiddenKeys = new Set();
    state.personal = state.personal || {};

    // Paint the table first so state._visibleList mirrors the live list (the
    // picks card click reads it via visibleListForKeyboard()).
    await renderTable({ force: true });
    state._visibleList = LIST;

    scrollToSpy.mockClear();
    focusGame("steam:60");

    // The picked row must be painted...
    expect(document.querySelector('tr[data-row-key="steam:60"]')).toBeTruthy();
    // ...and the viewport must scroll well down the page toward it, not land
    // near the top (the "arriving much too high" bug).
    const maxTop = Math.max(...scrollToSpy.mock.calls.map((c) => c[0]?.top ?? 0));
    expect(maxTop).toBeGreaterThan(1000);
  });
});
