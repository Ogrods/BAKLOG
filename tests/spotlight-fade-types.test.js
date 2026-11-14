/** Cross-kind spotlight fade contract: logo/cover/sale/ad/portrait swaps. */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

const APP_CSS = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "..", "app.css"),
  "utf8",
);

describe("spotlight fade across slide kinds", () => {
  let startSpotlightRotation;
  let stopSpotlightRotation;
  let stepSpotlight;
  let renderSpotlightHtml;
  let SPOTLIGHT_FADE_MS;
  let gameKey;
  let rafQueue;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.matchMedia = vi.fn(() => ({
      matches: false,
      media: "",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));
    // Fake timeouts only - keep rAF under our queue so fit-wait + double-rAF
    // stay separable (Vitest's fake rAF flushes inside advanceTimersByTime).
    vi.useFakeTimers({
      toFake: [
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "Date",
      ],
    });
    rafQueue = [];
    const raf = (cb) => {
      rafQueue.push(cb);
      return rafQueue.length;
    };
    const caf = (id) => {
      if (id >= 1 && id <= rafQueue.length) rafQueue[id - 1] = null;
    };
    global.requestAnimationFrame = raf;
    global.cancelAnimationFrame = caf;
    win.requestAnimationFrame = raf;
    win.cancelAnimationFrame = caf;

    vi.resetModules();
    await import("../js/covers.js");
    ({ gameKey } = await import("../js/game-core.js"));
    ({
      startSpotlightRotation,
      stopSpotlightRotation,
      stepSpotlight,
      renderSpotlightHtml,
      SPOTLIGHT_FADE_MS,
    } = await import("../js/dashboard-spotlight.js"));
  });

  afterEach(() => {
    stopSpotlightRotation?.();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  const coverSlide = (id, name, eyebrow = "Highly rated") => ({
    store: "steam",
    id,
    name,
    steam_review_percent: 90,
    steam_review_count: 500,
    library_image: `${id}.jpg`,
    header_image: `${id}.jpg`,
    _spotlightReason: { eyebrow, score: 90 },
  });

  const wishlistSaleSlide = () => ({
    store: "wishlist",
    id: "wish-sale",
    name: "Wishlist Sale",
    steam_review_percent: 88,
    steam_review_count: 400,
    library_image: "wish.jpg",
    header_image: "wish.jpg",
    _spotlightReason: { eyebrow: "On sale now", score: 88 },
  });

  const logoSlide = () => ({
    store: "baklog",
    id: "house-pro-logo",
    name: "BAKLOG Pro",
    _spotlightArtMode: "logo",
    _spotlightAd: {
      id: "house-spotlight-pro-logo",
      url: "https://baklog.app/#pro",
      scheme: "ember",
      slogan: "Your backlog, one place",
      cta: "See Pro",
    },
    _spotlightReason: { eyebrow: "BAKLOG Pro", score: 0 },
  });

  const adCoverSlide = () => ({
    store: "baklog",
    id: "sponsor-ember",
    name: "Emberfall",
    library_image: "ad.jpg",
    header_image: "ad.jpg",
    _spotlightAd: {
      id: "sponsor-ember",
      url: "https://example.com/ember",
    },
    _spotlightReason: { eyebrow: "Sponsored", score: 0 },
  });

  function mountPool(pool) {
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    const el = document.getElementById("dashboardSpotlight");
    startSpotlightRotation(pool);
    return el;
  }

  function drainIncomingRelease(el) {
    let guard = 0;
    while (el.classList.contains("is-incoming") && guard++ < 8) {
      const batch = rafQueue.splice(0).filter(Boolean);
      if (!batch.length) break;
      for (const cb of batch) cb(0);
    }
  }

  /** Complete fade-out swap, art-fit wait (covers), and double-rAF fade-in. */
  function completeFadeSwap(el) {
    expect(el.classList.contains("is-fading")).toBe(true);
    const htmlDuringFade = el.innerHTML;
    rafQueue.length = 0;
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.classList.contains("is-fading")).toBe(false);
    expect(el.classList.contains("is-incoming")).toBe(true);
    expect(el.innerHTML).not.toBe(htmlDuringFade);
    // Flush art-fit timeout when still waiting; logo/sync-fit already queued rAFs.
    if (el._spotlightPendingIncomingRelease) {
      rafQueue.length = 0;
      vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    }
    expect(el.classList.contains("is-incoming")).toBe(true);
    expect(el._spotlightPendingIncomingRelease).toBeFalsy();
    expect(rafQueue.filter(Boolean).length).toBeGreaterThanOrEqual(1);
    drainIncomingRelease(el);
    expect(el.classList.contains("is-incoming")).toBe(false);
  }

  function stubArtFit(el, width, height) {
    Object.defineProperty(el, "clientWidth", {
      value: 1000,
      configurable: true,
    });
    Object.defineProperty(el, "clientHeight", {
      value: 400,
      configurable: true,
    });
    const img = el.querySelector(".dash-spotlight-art");
    if (!img) return;
    Object.defineProperty(img, "naturalWidth", {
      value: width,
      configurable: true,
    });
    Object.defineProperty(img, "naturalHeight", {
      value: height,
      configurable: true,
    });
    Object.defineProperty(img, "complete", {
      value: true,
      configurable: true,
    });
    img.classList.add("is-loaded");
    window.applySpotlightArtFit(img);
  }

  it("CSS suppresses motion while fading or incoming", () => {
    expect(APP_CSS).toMatch(
      /\.dash-spotlight\.is-incoming:not\(\.has-portrait-art\):not\(\.is-lowres-art\)[\s\S]*animation:\s*none\s*!important/s,
    );
    expect(APP_CSS).toMatch(
      /\.dash-spotlight\.is-incoming\.has-logo-art\s+\.dash-spotlight-logo-mark\s+svg[\s\S]*animation:\s*none\s*!important/s,
    );
  });

  it("library cover → library cover keeps fade contract", () => {
    const pool = [
      coverSlide("1", "Alpha"),
      coverSlide("2", "Beta", "Solid pick"),
    ];
    const el = mountPool(pool);
    const fromKey = gameKey(pool[0]);
    expect(el.dataset.key).toBe(fromKey);

    stepSpotlight(1);
    expect(el.dataset.key).toBe(gameKey(pool[1]));
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Alpha");
    completeFadeSwap(el);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
    expect(el.classList.contains("has-logo-art")).toBe(false);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(false);
  });

  it("library → wishlist On sale now", () => {
    const pool = [coverSlide("1", "Alpha"), wishlistSaleSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    completeFadeSwap(el);
    expect(el.dataset.key).toBe(gameKey(pool[1]));
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe(
      "Wishlist Sale",
    );
    // eyebrowVariant may rewrite "On sale now" (e.g. Discounted).
    expect(
      el.querySelector(".dash-spotlight-eyebrow")?.textContent?.length,
    ).toBeGreaterThan(0);
    expect(el.classList.contains("has-logo-art")).toBe(false);
  });

  it("cover → logo Pro house", () => {
    const pool = [coverSlide("1", "Alpha"), logoSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    expect(el.classList.contains("is-fading")).toBe(true);
    completeFadeSwap(el);
    expect(el.classList.contains("has-logo-art")).toBe(true);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(true);
    expect(el.dataset.action).toBe("sponsored-deal");
    expect(el.querySelector(".dash-spotlight-art")).toBeNull();
    expect(el.querySelector(".dash-spotlight-logo-lockup")).toBeTruthy();
  });

  it("logo → cover", () => {
    const pool = [logoSlide(), coverSlide("2", "Beta")];
    const el = mountPool(pool);
    expect(el.classList.contains("has-logo-art")).toBe(true);
    stepSpotlight(1);
    completeFadeSwap(el);
    expect(el.classList.contains("has-logo-art")).toBe(false);
    expect(el.querySelector(".dash-spotlight-art")).toBeTruthy();
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
    expect(el.dataset.action).toBe("dash-list-jump");
  });

  it("cover ad → library", () => {
    const pool = [adCoverSlide(), coverSlide("2", "Beta")];
    const el = mountPool(pool);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(true);
    stepSpotlight(1);
    completeFadeSwap(el);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(false);
    expect(el.dataset.action).toBe("dash-list-jump");
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
  });

  it("portrait → landscape settles layout classes before fade-in release", () => {
    const pool = [
      coverSlide("1", "Portrait"),
      coverSlide("2", "Landscape", "Solid pick"),
    ];
    const el = mountPool(pool);
    stubArtFit(el, 600, 900);
    expect(el.classList.contains("has-portrait-art")).toBe(true);

    rafQueue.length = 0;
    stepSpotlight(1);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.classList.contains("is-incoming")).toBe(true);
    // Simulate cached cover so art-fit runs sync via onload hook path.
    stubArtFit(el, 1920, 1080);
    expect(el.classList.contains("has-portrait-art")).toBe(false);
    expect(el.classList.contains("is-incoming")).toBe(true);
    // Fit notify should have queued double-rAF (no need for fit timeout).
    if (rafQueue.filter(Boolean).length === 0) {
      vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    }
    expect(rafQueue.filter(Boolean).length).toBeGreaterThanOrEqual(1);
    drainIncomingRelease(el);
    expect(el.classList.contains("is-incoming")).toBe(false);
    expect(el.classList.contains("has-portrait-art")).toBe(false);
  });

  it("stop mid-fade cancels cross-kind HTML swap", () => {
    const pool = [coverSlide("1", "Alpha"), logoSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    expect(el.classList.contains("is-fading")).toBe(true);
    const htmlBefore = el.innerHTML;
    stopSpotlightRotation();
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS * 2);
    expect(el.innerHTML).toBe(htmlBefore);
    expect(el.classList.contains("is-fading")).toBe(false);
    expect(el.classList.contains("is-incoming")).toBe(false);
  });
});
