/**
 * Cross-view row drills must paint summary+picks before scheduling scroll,
 * matching toolbar drills (avoids CHROME_SETTLE force-consume undershoot).
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("refreshFilterUI row drill chrome order", () => {
  it("paints summary and picks before scheduleScroll on drillIn (no idle defer)", () => {
    const src = readFileSync(resolve("js/filters-ui.js"), "utf8");
    const drillIdx = src.indexOf("// Row drills (spotlight");
    expect(drillIdx).toBeGreaterThan(0);
    const block = src.slice(drillIdx, drillIdx + 600);
    expect(block).toMatch(/if \(drillIn\) \{/);
    expect(block).toMatch(/renderSummary\(\);/);
    expect(block).toMatch(/renderPicks\(\);/);
    expect(block).toMatch(/scheduleScrollAfterChromeSettled\(\);/);
    expect(block.indexOf("renderSummary()")).toBeLessThan(block.indexOf("scheduleScrollAfterChromeSettled()"));
    expect(block.indexOf("renderPicks()")).toBeLessThan(block.indexOf("scheduleScrollAfterChromeSettled()"));
    expect(block).not.toMatch(/requestIdleCallback\(deferChrome/);
  });
});
