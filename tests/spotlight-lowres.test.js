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
    expect(img.style.objectPosition).toBe("center");
    expect(spot.querySelector(".dash-spotlight-art-bg").classList.contains("is-loaded")).toBe(true);
  });

  it("uses contain wide card for sharp landscape hero art (never cover)", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 1920, 620);

    expect(spot.classList.contains("is-lowres-art")).toBe(true);
    expect(spot.classList.contains("has-portrait-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
    expect(img.style.objectPosition).toBe("center");
    expect(spot.querySelector(".dash-spotlight-art-bg").classList.contains("is-loaded")).toBe(true);
  });

  it("spotlight HTML omits forced width/height attrs", () => {
    const spot = mountSpotlight();
    const img = spot.querySelector(".dash-spotlight-art");
    expect(img.getAttribute("width")).toBeNull();
    expect(img.getAttribute("height")).toBeNull();
  });

  it("prefers portrait treatment over low-res for tall art", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 300, 450);
    const sheen = spot.querySelector(".dash-spotlight-sheen");

    expect(spot.classList.contains("has-portrait-art")).toBe(true);
    expect(spot.classList.contains("has-square-art")).toBe(false);
    expect(spot.classList.contains("is-lowres-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
    expect(img.style.objectPosition).toBe("center");
    // Sheen matches height-driven card: min(slotW, (slotH - 32) * ratio).
    expect(parseFloat(sheen.style.width)).toBeCloseTo(
      Math.min(800, (400 - 32) * (300 / 450)),
      4,
    );
    // FG mask is CSS (none); JS must not stamp an inline override.
    expect(img.style.getPropertyValue("mask-image")).toBe("");
  });

  it("flags near-square art as square capsule (still portrait path)", () => {
    const spot = mountSpotlight();
    const img = stubArtDimensions(spot, 400, 400);
    const sheen = spot.querySelector(".dash-spotlight-sheen");

    expect(spot.classList.contains("has-portrait-art")).toBe(true);
    expect(spot.classList.contains("has-square-art")).toBe(true);
    expect(spot.classList.contains("is-lowres-art")).toBe(false);
    expect(img.style.objectFit).toBe("contain");
    expect(img.style.objectPosition).toBe("center");
    expect(img.style.getPropertyValue("mask-image")).toBe("");
    // Square sheen geometry is CSS 1:1; clear any prior tall-portrait width.
    expect(sheen.style.width).toBe("");
  });

  it("keeps low-res and portrait focal center when stacked (CSS parks the card)", () => {
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
    expect(lowresImg.style.objectPosition).toBe("center");
  });
});

describe("spotlight portrait CSS contract", () => {
  it("uses intrinsic centered card for tall portrait; 1:1 card for square", async () => {
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
    // Tall portrait is an intrinsic centered card - not a 2:3 capsule.
    expect(portraitArt).not.toMatch(/aspect-ratio:\s*2\s*\/\s*3/);
    expect(portraitArt).toMatch(/width:\s*auto/);
    expect(portraitArt).toMatch(/left:\s*50%/);
    expect(portraitArt).toMatch(/height:\s*calc\(100%\s*-\s*32px\)/);
    expect(portraitArt).toMatch(/top:\s*16px/);
    expect(portraitArt).toMatch(/object-fit:\s*contain/);
    // Hard FG edges - left fade lives on art-bg (same as low-res).
    expect(portraitArt).toMatch(/mask-image:\s*none/);
    expect(portraitArt).not.toMatch(/overflow:\s*hidden/);

    const portraitBg = css.match(
      /\.dash-spotlight\.has-portrait-art \.dash-spotlight-art-bg \{[\s\S]*?\n\}/,
    )?.[0];
    expect(portraitBg).toMatch(/display:\s*block/);
    // No balanced L/R override - inherit base left-edge art-bg fade.
    expect(portraitBg).not.toMatch(/mask-image:/);
    // Anchor on the full-bleed art-bg rule (blur + left fade), not reduced-motion stubs.
    const baseBgIdx = css.indexOf("filter: blur(18px) brightness(0.5)");
    expect(baseBgIdx).toBeGreaterThan(0);
    const baseBg = css.slice(baseBgIdx, baseBgIdx + 450);
    expect(baseBg).toMatch(/mask-image:\s*linear-gradient/);
    expect(baseBg).toMatch(/transparent 12%/);
    // Midnight must not kill portrait/square blur backdrop.
    expect(css).not.toMatch(
      /html\[data-theme=["']dark["']\][\s\S]{0,120}\.has-portrait-art[\s\S]{0,80}art-bg[\s\S]{0,40}display:\s*none/,
    );

    const floatStart = css.indexOf("@keyframes spotlightFloat1");
    const floatEnd = css.indexOf(".dash-spotlight-sheen {", floatStart);
    expect(floatStart).toBeGreaterThanOrEqual(0);
    expect(floatEnd).toBeGreaterThan(floatStart);
    const floatBlock = css.slice(floatStart, floatEnd);
    expect(floatBlock).not.toMatch(/rotateY/);
    expect(floatBlock).toMatch(/translateY/);

    const sheen = css.match(
      /\.dash-spotlight\.has-portrait-art \.dash-spotlight-sheen \{[\s\S]*?\n\}/,
    )?.[0];
    expect(sheen).toMatch(/left:\s*50%/);
    expect(sheen).toMatch(/transform:\s*translateX\(-50%\)/);
    expect(sheen).not.toMatch(/aspect-ratio:\s*2\s*\/\s*3/);

    const squareArt = css.match(
      /\.dash-spotlight\.has-portrait-art\.has-square-art \.dash-spotlight-art \{[\s\S]*?\n\}/,
    )?.[0];
    expect(squareArt).toMatch(/aspect-ratio:\s*1\s*\/\s*1/);

    const squareSheen = css.match(
      /\.dash-spotlight\.has-portrait-art\.has-square-art \.dash-spotlight-sheen \{[\s\S]*?\n\}/,
    )?.[0];
    expect(squareSheen).toMatch(/aspect-ratio:\s*1\s*\/\s*1/);
  });

  it("FG base CSS never forces cover or 2/3 capsule", async () => {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const css = await fs.readFile(path.join(process.cwd(), "app.css"), "utf8");
    const start = css.indexOf("\n.dash-spotlight-art {");
    expect(start).toBeGreaterThan(0);
    const block = css.slice(start, start + 500);
    expect(block).toMatch(/object-fit:\s*contain/);
    expect(block).not.toMatch(/object-fit:\s*cover/);
    expect(block).not.toMatch(/aspect-ratio:\s*2\s*\/\s*3/);
    expect(block).toMatch(/mask-image:\s*none/);
  });

  it("insets low-res art as a wide cover card with vertical margins", async () => {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const css = await fs.readFile(
      path.join(process.cwd(), "app.css"),
      "utf8",
    );
    const lowresArt = css.match(
      /\.dash-spotlight\.is-lowres-art \.dash-spotlight-art \{[\s\S]*?\n\}/,
    )?.[0];
    expect(lowresArt).toBeTruthy();
    expect(lowresArt).toMatch(/top:\s*16%/);
    expect(lowresArt).toMatch(/height:\s*68%/);
    expect(lowresArt).toMatch(/left:\s*50%/);
    expect(lowresArt).toMatch(/translate:\s*-50%\s+0/);
    expect(lowresArt).not.toMatch(/right:\s*14px/);
    expect(lowresArt).toMatch(/mask-image:\s*none/);
    expect(lowresArt).toMatch(/object-fit:\s*contain/);
  });
});
