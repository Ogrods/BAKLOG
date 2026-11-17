/** Corner notice stack - no in-flow layout shift for status alerts. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";

const APP_CSS = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "app.css"),
  "utf8",
);

describe("notice-toast", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = "";
  });

  it("showNoticeToast mounts fixed stack host and toast by id", async () => {
    const { showNoticeToast, isNoticeToastVisible, hideNoticeToast } = await import(
      "../js/notice-toast.js"
    );
    const el = showNoticeToast({
      id: "itadAlertBanner",
      html: "<div class='migration-banner-body'><strong>Prices refreshed</strong></div>",
      variant: "itad",
    });
    expect(el).toBeTruthy();
    expect(document.getElementById("noticeToastStack")).toBeTruthy();
    expect(el.parentElement?.id).toBe("noticeToastStack");
    expect(el.className).toContain("app-notice-toast--itad");
    expect(isNoticeToastVisible("itadAlertBanner")).toBe(true);
    hideNoticeToast("itadAlertBanner");
    expect(isNoticeToastVisible("itadAlertBanner")).toBe(false);
  });

  it("CSS pins notice stack and update banners without shell margin push", () => {
    expect(APP_CSS).toMatch(/\.notice-toast-stack\s*\{[^}]*position:\s*fixed/s);
    expect(APP_CSS).toMatch(/\.app-notice-toast\s*\{/);
    expect(APP_CSS).toMatch(/#updateAvailableBanner:not\(\.hidden\)/);
  });
});
