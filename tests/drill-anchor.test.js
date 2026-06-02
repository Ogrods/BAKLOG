/**
 * Drill-anchor unified scroll target — toolbar vs row-center consumption.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

describe("drill-anchor pending scroll target", () => {
  let win;
  let scrollToSpy;

  beforeEach(async () => {
    win = new Window({ url: "http://127.0.0.1:8765/" });
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
    global.setTimeout = (cb, ms) => {
      if (typeof cb === "function") cb();
      return 1;
    };
    global.clearTimeout = () => {};
    global.CSS = { escape: (s) => String(s).replace(/"/g, '\\"') };

    scrollToSpy = vi.spyOn(win, "scrollTo").mockImplementation(() => {});

    document.body.innerHTML = `
      <section id="picksSection" style="height:120px"><div id="picksGrid"></div></section>
      <div id="toolbarSection" style="height:80px;margin-top:200px">toolbar</div>
      <div id="tableShell" style="margin-top:400px">
        <table class="games-table"><thead></thead>
          <tbody id="tbody">
            <tr data-row-key="steam:42" data-row-index="5"><td>Game</td></tr>
          </tbody>
        </table>
      </div>
    `;

    vi.resetModules();
  });

  it("consumePendingScrollTarget scrolls toolbar for kind=toolbar", async () => {
    const { setPendingScrollTarget, consumePendingScrollTarget } = await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "toolbar" });
    const ok = consumePendingScrollTarget([]);
    expect(ok).toBe(true);
    expect(scrollToSpy).toHaveBeenCalled();
    const arg = scrollToSpy.mock.calls[0][0];
    expect(typeof arg.top).toBe("number");
    expect(arg.behavior).toBe("auto");
  });

  it("consumePendingScrollTarget scrolls row into view for kind=row", async () => {
    const { setPendingScrollTarget, consumePendingScrollTarget } = await import("../js/table-ui.js");
    const list = [{ store: "steam", id: "42", name: "Test Game" }];
    setPendingScrollTarget({ kind: "row", key: "steam:42", idx: 5 });
    const ok = consumePendingScrollTarget(list);
    expect(ok).toBe(true);
    expect(scrollToSpy).toHaveBeenCalled();
    expect(document.querySelector("tr.row-focused")).toBeTruthy();
  });

  it("scheduleScrollAfterLayoutSettled consumes pending target", async () => {
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled, hasPendingScrollTarget } =
      await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "toolbar" });
    expect(hasPendingScrollTarget()).toBe(true);
    scheduleScrollAfterLayoutSettled();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(scrollToSpy).toHaveBeenCalled();
  });

  it("pending target is consumed only once", async () => {
    const { setPendingScrollTarget, consumePendingScrollTarget } = await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "toolbar" });
    expect(consumePendingScrollTarget([])).toBe(true);
    expect(consumePendingScrollTarget([])).toBe(false);
    expect(scrollToSpy).toHaveBeenCalledTimes(1);
  });

  it("scheduleScrollAfterLayoutSettled consumes a row target after two rAF ticks", async () => {
    const { state } = await import("../js/state.js");
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled, hasPendingScrollTarget } =
      await import("../js/table-ui.js");
    const list = [{ store: "steam", id: "42", name: "Test Game" }];
    state._visibleList = list;
    setPendingScrollTarget({ kind: "row", key: "steam:42", idx: 5 });
    expect(hasPendingScrollTarget()).toBe(true);
    scheduleScrollAfterLayoutSettled();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(scrollToSpy).toHaveBeenCalled();
    expect(document.querySelector("tr.row-focused")).toBeTruthy();
  });

  it("consumePendingScrollTarget resolves row index by key when stored idx is stale", async () => {
    const { setPendingScrollTarget, consumePendingScrollTarget } = await import("../js/table-ui.js");
    const list = [
      { store: "steam", id: "1", name: "Alpha" },
      { store: "steam", id: "42", name: "Test Game" },
      { store: "steam", id: "9", name: "Zeta" },
    ];
    setPendingScrollTarget({ kind: "row", key: "steam:42", idx: 0 });
    const ok = consumePendingScrollTarget(list);
    expect(ok).toBe(true);
    expect(document.querySelector('tr[data-row-key="steam:42"]')?.classList.contains("row-focused")).toBe(true);
  });

  it("cancelPendingScrollTarget clears an armed scroll", async () => {
    const { setPendingScrollTarget, cancelPendingScrollTarget, hasPendingScrollTarget, consumePendingScrollTarget } =
      await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "toolbar" });
    cancelPendingScrollTarget();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(consumePendingScrollTarget([])).toBe(false);
    expect(scrollToSpy).not.toHaveBeenCalled();
  });

  it("scheduleScrollAfterLayoutSettled never blocks on a ResizeObserver", async () => {
    let observeCount = 0;
    global.ResizeObserver = class {
      observe() {
        observeCount += 1;
      }
      disconnect() {}
    };
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled } = await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "row", key: "steam:42" });
    scheduleScrollAfterLayoutSettled();
    expect(observeCount).toBe(0);
  });

  it("consumes pending row target even while pendingFocusKey is present", async () => {
    const { state } = await import("../js/state.js");
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled, hasPendingScrollTarget } =
      await import("../js/table-ui.js");
    const list = [{ store: "steam", id: "42", name: "Test Game" }];
    state._visibleList = list;
    state._pendingFocusKey = "steam:42";
    setPendingScrollTarget({ kind: "row", key: "steam:42" });
    expect(hasPendingScrollTarget()).toBe(true);
    scheduleScrollAfterLayoutSettled();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(scrollToSpy).toHaveBeenCalled();
  });

  it("single schedule pass resolves cross-view style row drill", async () => {
    const { state } = await import("../js/state.js");
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled, hasPendingScrollTarget } =
      await import("../js/table-ui.js");
    const list = [{ store: "steam", id: "42", name: "Test Game" }];
    state._visibleList = list;
    state._pendingFocusKey = "steam:42";
    setPendingScrollTarget({ kind: "row", key: "steam:42", smooth: false, hideOverlay: true });
    scheduleScrollAfterLayoutSettled();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(document.querySelector("tr.row-focused")).toBeTruthy();
    expect(scrollToSpy).toHaveBeenCalledTimes(1);
  });

  it("consumePendingScrollTarget scrolls virtual list by row index", async () => {
    const { setPendingScrollTarget, consumePendingScrollTarget } = await import("../js/table-ui.js");
    const list = Array.from({ length: 120 }, (_, i) => ({
      store: "steam",
      id: String(i),
      name: `Game ${i}`,
    }));
    setPendingScrollTarget({ kind: "row", key: "steam:60", smooth: false });
    const ok = consumePendingScrollTarget(list);
    expect(ok).toBe(true);
    expect(scrollToSpy).toHaveBeenCalled();
    const top = scrollToSpy.mock.calls[0][0].top;
    expect(top).toBeGreaterThan(0);
  });
});

function makeVirtualList(n) {
  return Array.from({ length: n }, (_, i) => ({
    store: "steam",
    id: String(i),
    name: `Game ${i}`,
  }));
}

describe("virtual drill anchor scroll", () => {
  let win;
  let scrollToSpy;

  beforeEach(async () => {
    vi.resetModules();
    vi.doMock("../js/table-query.js", async (importOriginal) => {
      const actual = await importOriginal();
      const list = makeVirtualList(120);
      return {
        ...actual,
        collectTableParams: () => ({}),
        queryGamesAsync: async () => list,
        queryGames: () => list,
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

  it("renderTable anchorIndex scrolls viewport and paints target row for virtual list", async () => {
    const { state } = await import("../js/state.js");
    const { renderTable } = await import("../js/table-ui.js");
    state.activeView = "library";
    state.prefs = state.prefs || {};
    state.prefs.showScoreColumn = false;
    state.sessionPrefs = state.sessionPrefs || {};
    state.sortKey = "name";
    state.sortDir = 1;
    state.selectedKeys = new Set();
    state.crossStoreHiddenKeys = new Set();
    state.personal = state.personal || {};

    await renderTable({ force: true, anchorIndex: 60 });

    expect(scrollToSpy).toHaveBeenCalled();
    const maxTop = Math.max(...scrollToSpy.mock.calls.map((c) => c[0]?.top ?? 0));
    expect(maxTop).toBeGreaterThan(0);
    expect(document.querySelector('tr[data-row-key="steam:60"]')).toBeTruthy();
  });
});
