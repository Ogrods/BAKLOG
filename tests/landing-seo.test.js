/* @vitest-environment node */
import { describe, expect, it } from "vitest";
import {
  checkLandingSeo,
  cspAllowsHttpsHostname,
  extractFaqFromHtml,
  stripHtmlToText,
} from "../scripts/check-landing-seo.mjs";
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

  it("stripHtmlToText removes nested and leftover angle brackets", () => {
    expect(stripHtmlToText("Hi <b>there</b>")).toBe("Hi there");
    expect(stripHtmlToText("<<script>alert(1)</script>")).toBe("alert(1)");
  });

  it("cspAllowsHttpsHostname matches exact host tokens only", () => {
    const csp =
      "script-src 'self' https://www.googletagmanager.com https://*.googletagmanager.com";
    expect(cspAllowsHttpsHostname(csp, "www.googletagmanager.com")).toBe(true);
    expect(cspAllowsHttpsHostname(csp, "evil.com")).toBe(false);
  });
});
