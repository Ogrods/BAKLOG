/** Cross-kind spotlight veil fade: logo/cover/sale/ad/portrait swaps. */
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
  let SPOTLIGHT_FADE_OUT_MS;
  let SPOTLIGHT_FADE_IN_MS;
  let SPOTLIGHT_DECODE_WAIT_MS;
  let gameKey;
  let rafQueue;
  let anim;

  function installAnimateStub() {
    const queue = [];
    Element.prototype.animate = function animateStub() {
      let settle;
      const finished = new Promise((resolve) => {
        settle = resolve;
      });
      const animation = {
        finished,
        cancel() {
          settle();
        },
      };
      queue.push({ settle, el: this });
      return animation;
    };
    return {
      pending: () => queue.length,
      async finishNext() {
        const item = queue.shift();
        if (!item) throw new Error("no pending veil animation");
        item.settle();
        await Promise.resolve();
        await Promise.resolve();
      },
    };
  }

  function drainRaf() {
    const batch = rafQueue.splice(0).filter(Boolean);
    for (const cb of batch) cb(0);
  }

  async function flushMicrotasks() {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  }

  /** Finish veil fade-out (swap) → fade-in settle. */
  async function completeFadeSwap(el) {
    const htmlDuringFade = el.innerHTML;
    expect(el.querySelector(".dash-spotlight-veil")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(SPOTLIGHT_FADE_OUT_MS);
    await flushMicrotasks();
    expect(el.innerHTML).not.toBe(htmlDuringFade);
    expect(el.querySelector(".dash-spotlight-veil")).toBeTruthy();
    await vi.advanceTimersByTimeAsync(SPOTLIGHT_FADE_IN_MS);
    await flushMicrotasks();
    // Drain any WAAPI stub finishes kicked in parallel with the timers.
    while (anim.pending() > 0) {
      await anim.finishNext().catch(() => {});
    }
  }

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
    anim = installAnimateStub();

    vi.resetModules();
    await import("../js/covers.js");
    ({ gameKey } = await import("../js/game-core.js"));
    ({
      startSpotlightRotation,
      stopSpotlightRotation,
      stepSpotlight,
      renderSpotlightHtml,
      SPOTLIGHT_FADE_OUT_MS,
      SPOTLIGHT_FADE_IN_MS,
      SPOTLIGHT_DECODE_WAIT_MS,
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

  it("CSS veil geometry covers theme bg + art feather; no per-layer fade", () => {
    expect(APP_CSS).toMatch(/\.dash-spotlight-veil\s*\{[^}]*z-index:\s*4/s);
    expect(APP_CSS).toMatch(/\.dash-spotlight-veil\s*\{[^}]*background:\s*var\(--bg\)/s);
    expect(APP_CSS).toMatch(
      /\.dash-spotlight-veil[\s\S]*mask-image:\s*linear-gradient\([\s\S]*transparent 12%/s,
    );
    expect(APP_CSS).toMatch(/\.dash-spotlight-veil[\s\S]*#000 95%/s);
    expect(APP_CSS).not.toMatch(
      /\.dash-spotlight\.is-fading\s+\.dash-spotlight-art/,
    );
    expect(APP_CSS).not.toMatch(
      /\.dash-spotlight\.is-incoming[\s\S]*animation:\s*none\s*!important/,
    );
    // Stacked phone width clears veil mask with art.
    expect(APP_CSS).toMatch(
      /\.dash-spotlight-veil,\s*\n\s*\.dash-spotlight\.has-portrait-art\s+\.dash-spotlight-sheen/,
    );
  });

  it("cover and logo slides both render a veil", () => {
    document.body.innerHTML = renderSpotlightHtml(coverSlide("1", "Alpha"));
    expect(
      document.querySelector("#dashboardSpotlight .dash-spotlight-veil"),
    ).toBeTruthy();
    document.body.innerHTML = renderSpotlightHtml(logoSlide());
    expect(
      document.querySelector("#dashboardSpotlight .dash-spotlight-veil"),
    ).toBeTruthy();
  });

  it("library cover → library cover keeps veil contract", async () => {
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
    await completeFadeSwap(el);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
    expect(el.classList.contains("has-logo-art")).toBe(false);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(false);
  });

  it("library → wishlist On sale now", async () => {
    const pool = [coverSlide("1", "Alpha"), wishlistSaleSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    await completeFadeSwap(el);
    expect(el.dataset.key).toBe(gameKey(pool[1]));
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe(
      "Wishlist Sale",
    );
    expect(
      el.querySelector(".dash-spotlight-eyebrow")?.textContent?.length,
    ).toBeGreaterThan(0);
    expect(el.classList.contains("has-logo-art")).toBe(false);
  });

  it("cover → logo Pro house", async () => {
    const pool = [coverSlide("1", "Alpha"), logoSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    expect(anim.pending()).toBeGreaterThanOrEqual(1);
    await completeFadeSwap(el);
    expect(el.classList.contains("has-logo-art")).toBe(true);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(true);
    expect(el.dataset.action).toBe("sponsored-deal");
    expect(el.querySelector(".dash-spotlight-art")).toBeNull();
    expect(el.querySelector(".dash-spotlight-logo-lockup")).toBeTruthy();
    expect(el.querySelector(".dash-spotlight-veil")).toBeTruthy();
  });

  it("logo → cover", async () => {
    const pool = [logoSlide(), coverSlide("2", "Beta")];
    const el = mountPool(pool);
    expect(el.classList.contains("has-logo-art")).toBe(true);
    stepSpotlight(1);
    await completeFadeSwap(el);
    expect(el.classList.contains("has-logo-art")).toBe(false);
    expect(el.querySelector(".dash-spotlight-art")).toBeTruthy();
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
    expect(el.dataset.action).toBe("dash-list-jump");
  });

  it("cover ad → library", async () => {
    const pool = [adCoverSlide(), coverSlide("2", "Beta")];
    const el = mountPool(pool);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(true);
    stepSpotlight(1);
    await completeFadeSwap(el);
    expect(el.classList.contains("dash-spotlight--ad")).toBe(false);
    expect(el.dataset.action).toBe("dash-list-jump");
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
  });

  it("portrait → landscape settles layout classes under the veil", async () => {
    const pool = [
      coverSlide("1", "Portrait"),
      coverSlide("2", "Landscape", "Solid pick"),
    ];
    const el = mountPool(pool);
    stubArtFit(el, 600, 900);
    expect(el.classList.contains("has-portrait-art")).toBe(true);

    stepSpotlight(1);
    await vi.advanceTimersByTimeAsync(SPOTLIGHT_FADE_OUT_MS);
    await flushMicrotasks();
    stubArtFit(el, 1920, 1080);
    expect(el.classList.contains("has-portrait-art")).toBe(false);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe(
      "Landscape",
    );
    await vi.advanceTimersByTimeAsync(SPOTLIGHT_FADE_IN_MS);
  });

  it("rapid steps land on the latest slide (latest-wins)", async () => {
    const pool = [
      coverSlide("1", "Alpha"),
      coverSlide("2", "Beta", "Solid pick"),
      coverSlide("3", "Gamma", "Solid pick"),
    ];
    const el = mountPool(pool);
    stepSpotlight(1);
    stepSpotlight(1);
    expect(el.dataset.key).toBe(gameKey(pool[2]));
    // One fade-out for the in-flight transition; retarget happens under the veil.
    await completeFadeSwap(el);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Gamma");
  });

  it("swap still applies when decode is slow (cap does not block HTML)", async () => {
    const pool = [
      coverSlide("1", "Alpha"),
      coverSlide("2", "Beta", "Solid pick"),
    ];
    const el = mountPool(pool);
    stepSpotlight(1);
    const htmlDuring = el.innerHTML;
    // Swap is timer-driven at fade-out; decode race is non-blocking.
    await vi.advanceTimersByTimeAsync(SPOTLIGHT_FADE_OUT_MS);
    await flushMicrotasks();
    expect(el.innerHTML).not.toBe(htmlDuring);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Beta");
    expect(SPOTLIGHT_DECODE_WAIT_MS).toBe(1200);
  });

  it("stop mid-fade cancels cross-kind HTML swap", async () => {
    const pool = [coverSlide("1", "Alpha"), logoSlide()];
    const el = mountPool(pool);
    stepSpotlight(1);
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Alpha");
    stopSpotlightRotation();
    await vi.advanceTimersByTimeAsync(
      SPOTLIGHT_FADE_OUT_MS + SPOTLIGHT_FADE_IN_MS + SPOTLIGHT_DECODE_WAIT_MS,
    );
    drainRaf();
    await flushMicrotasks();
    expect(el.querySelector(".dash-spotlight-title")?.textContent).toBe("Alpha");
    expect(el.classList.contains("has-logo-art")).toBe(false);
  });
});
