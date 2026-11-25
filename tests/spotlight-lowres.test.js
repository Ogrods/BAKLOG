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
    expect(img.style.objectPosition).toBe("100% 40%");
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
    const sheen = spot.querySelector(".dash-spotlight-sheen");

    expect(spot.classList.contains("has-portrait-art")).toBe(true);
    expect(spot.classList.contains("is-lowres-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
    expect(img.style.objectPosition).toBe("center");
    // Poster geometry is CSS; JS must not leave an inline sheen width.
    expect(sheen.style.width).toBe("");
    // Clear hero left-fade so capsule titles are not clipped (CSS also sets
    // -webkit-mask-image; happy-dom only reliably keeps the standard property).
    expect(img.style.getPropertyValue("mask-image")).toBe("none");
  });

  it("parks low-res at ~2/3 when stacked; portrait stays center (CSS right-tuck)", () => {
    window.matchMedia = vi.fn().mockImplementation((query) => ({
      matches: String(query).includes("1023.98px"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
    }));

    const portraitSpot = mountSpotlight();
    const portraitImg = stubArtDimensions(portraitSpot, 300, 450);
    expect(portraitSpot.classList.contains("has-portrait-art")).toBe(true);
    expect(portraitImg.style.objectPosition).toBe("center");

    const lowresSpot = mountSpotlight();
    const lowresImg = stubArtDimensions(lowresSpot, 460, 215);
    expect(lowresSpot.classList.contains("is-lowres-art")).toBe(true);
    expect(lowresImg.style.objectPosition).toBe("66% 40%");
  });
});

describe("spotlight portrait CSS contract", () => {
  it("clears hero mask and sizes a 2:3 poster for has-portrait-art", async () => {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const css = await fs.readFile(
      path.join(process.cwd(), "app.css"),
      "utf8",
    );
    const portraitArt = css.match(
      /\.dash-spotlight\.has-portrait-art \.dash-spotlight-art \{[\s\S]*?\n\}/,
    )?.[0];
    expect(portraitArt).toBeTruthy();
    expect(portraitArt).toMatch(/aspect-ratio:\s*2\s*\/\s*3/);
    expect(portraitArt).toMatch(/object-fit:\s*contain/);
    expect(portraitArt).toMatch(/mask-image:\s*none/);
    expect(portraitArt).toMatch(/overflow:\s*hidden/);

    const portraitBg = css.match(
      /\.dash-spotlight\.has-portrait-art \.dash-spotlight-art-bg \{[\s\S]*?\n\}/,
    )?.[0];
    expect(portraitBg).toMatch(/mask-image:\s*none/);

    const sheen = css.match(
      /\.dash-spotlight\.has-portrait-art \.dash-spotlight-sheen \{[\s\S]*?\n\}/,
    )?.[0];
    expect(sheen).toMatch(/aspect-ratio:\s*2\s*\/\s*3/);
  });
});
