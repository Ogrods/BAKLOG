/**
 * Catalog merges must not snap the library table to the top.
 * Soft invalidate keeps #tbody mounted so scrollY is not clamped during
 * the async renderTable gap after applyMergedLibrary.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

describe("table merge scroll preserve", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = `
      <div id="tableShell">
        <div id="tableWrap">
          <table class="game-table"><tbody id="tbody"></tbody></table>
        </div>
      </div>
      <div id="rowCount"></div>
      <div id="rowCountTop"></div>
      <div id="summary"></div>
      <div id="picks"></div>
      <div id="toolbarSection"></div>
    `;
    Object.defineProperty(window, "scrollY", { configurable: true, writable: true, value: 2400 });
    Object.defineProperty(window, "scrollTo", {
      configurable: true,
      value: vi.fn(({ top } = {}) => {
        if (typeof top === "number") window.scrollY = top;
      }),
    });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 800 });
  });

  it("invalidateTableCache({ keepDom: true }) leaves tbody content and scrollY", async () => {
    const tbody = document.getElementById("tbody");
    tbody.innerHTML = `<tr data-row-index="40" style="height:2000px"><td>spacer</td></tr>`;
    window.scrollY = 1800;

    const { invalidateTableCache } = await import("../js/table-ui.js");
    invalidateTableCache({ keepDom: true });

    expect(tbody.querySelector("tr[data-row-index='40']")).toBeTruthy();
    expect(window.scrollY).toBe(1800);
  });

  it("invalidateTableCache() hard clear empties tbody (view/filter path)", async () => {
    const tbody = document.getElementById("tbody");
    tbody.innerHTML = `<tr data-row-index="1"><td>x</td></tr>`;

    const { invalidateTableCache } = await import("../js/table-ui.js");
    invalidateTableCache();

    expect(tbody.innerHTML).toBe("");
  });

  it("hard clear without keepDom still cancels pending scroll targets", async () => {
    const {
      invalidateTableCache,
      setPendingScrollTarget,
      hasPendingScrollTarget,
    } = await import("../js/table-ui.js");
    setPendingScrollTarget({ kind: "row", key: "steam:1", smooth: false });
    expect(hasPendingScrollTarget()).toBe(true);
    invalidateTableCache({ keepDom: true });
    expect(hasPendingScrollTarget()).toBe(true);
    invalidateTableCache();
    expect(hasPendingScrollTarget()).toBe(false);
  });
});
