/* @vitest-environment node */
import { describe, expect, it } from "vitest";
import { checkLandingSeo, extractFaqFromHtml } from "../scripts/check-landing-seo.mjs";
import fs from "node:fs";
import path from "node:path";

describe("landing SEO gate", () => {
  it("passes checkLandingSeo", () => {
    expect(checkLandingSeo()).toEqual([]);
  });

  it("extracts 15 FAQ pairs from index.html", () => {
    const html = fs.readFileSync(
      path.join(import.meta.dirname, "../landing/index.html"),
      "utf8",
    );
    expect(extractFaqFromHtml(html)).toHaveLength(15);
  });
});
