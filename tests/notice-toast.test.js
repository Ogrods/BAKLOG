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

  it("CSS pins notice stack without shell margin push", () => {
    expect(APP_CSS).toMatch(/\.notice-toast-stack\s*\{[^}]*position:\s*fixed/s);
    expect(APP_CSS).toMatch(/\.app-notice-toast\s*\{/);
    expect(APP_CSS).not.toMatch(/#updateAvailableBanner:not\(\.hidden\)\s*\{[^}]*position:\s*fixed/s);
  });

  it("adoptNoticeToast moves existing banners into the stack", async () => {
    const { adoptNoticeToast, ensureNoticeToastStack } = await import(
      "../js/notice-toast.js"
    );
    const banner = document.createElement("div");
    banner.id = "updateAvailableBanner";
    banner.className = "migration-banner";
    banner.innerHTML = "<span>Update available</span>";
    document.body.appendChild(banner);
    adoptNoticeToast(banner, { variant: "update" });
    expect(banner.parentElement?.id).toBe("noticeToastStack");
    expect(banner.classList.contains("app-notice-toast--update")).toBe(true);
    expect(ensureNoticeToastStack()?.contains(banner)).toBe(true);
  });
});
