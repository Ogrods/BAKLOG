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

  it("scheduleScrollAfterLayoutSettled consumes afterChrome row target", async () => {
    const { state } = await import("../js/state.js");
    const { setPendingScrollTarget, scheduleScrollAfterLayoutSettled, hasPendingScrollTarget } =
      await import("../js/table-ui.js");
    const list = [{ store: "steam", id: "42", name: "Test Game" }];
    state._visibleList = list;
    setPendingScrollTarget({ kind: "row", key: "steam:42", idx: 5, afterChrome: true });
    expect(hasPendingScrollTarget()).toBe(true);
    scheduleScrollAfterLayoutSettled();
    expect(hasPendingScrollTarget()).toBe(false);
    expect(scrollToSpy).toHaveBeenCalled();
    expect(document.querySelector("tr.row-focused")).toBeTruthy();
  });
});
