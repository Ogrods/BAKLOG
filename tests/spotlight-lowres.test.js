/** Spotlight low-res art uses blurred-backdrop contain instead of stretched cover. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import { renderSpotlightHtml } from "../js/dashboard-spotlight.js";

describe("spotlight low-res art", () => {
  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.__landscapeCovers = new Set();
    vi.resetModules();
    await import("../js/covers.js");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  const game = {
    store: "steam",
    id: 1,
    name: "Test Game",
    steam_review_percent: 90,
    steam_review_count: 500,
    header_image: "https://cdn.akamai.steamstatic.com/steam/apps/1/header.jpg",
    _spotlightReason: { eyebrow: "Solid pick" },
  };

  function mountSpotlight() {
    document.body.innerHTML = renderSpotlightHtml(game);
    const spot = document.getElementById("dashboardSpotlight");
    Object.defineProperty(spot, "clientWidth", { value: 800, configurable: true });
    Object.defineProperty(spot, "clientHeight", { value: 400, configurable: true });
    return spot;
  }

  function stubArtDimensions(spot, width, height) {
    const img = spot.querySelector(".dash-spotlight-art");
    Object.defineProperty(img, "naturalWidth", { value: width, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: height, configurable: true });
    img.classList.add("is-loaded");
    window.applySpotlightArtFit(img);
    return img;
  }

  it("flags small landscape art as low-res and uses contain + blurred bg", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 460, 215);

    expect(spot.classList.contains("is-lowres-art")).toBe(true);
    expect(spot.classList.contains("has-portrait-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
    expect(spot.querySelector(".dash-spotlight-art-bg").classList.contains("is-loaded")).toBe(true);
  });

  it("uses cover for sharp landscape hero art", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 1920, 620);

    expect(spot.classList.contains("is-lowres-art")).toBe(false);
    expect(img.style.objectFit).toBe("cover");
    expect(spot.querySelector(".dash-spotlight-art-bg").classList.contains("is-loaded")).toBe(false);
  });

  it("prefers portrait treatment over low-res for tall art", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 300, 450);

    expect(spot.classList.contains("has-portrait-art")).toBe(true);
    expect(spot.classList.contains("is-lowres-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
  });
});
