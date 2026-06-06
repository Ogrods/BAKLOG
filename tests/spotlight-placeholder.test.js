/** Spotlight hero keeps an in-place placeholder when all art candidates fail. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

describe("spotlight art placeholder", () => {
  let renderSpotlightHtml;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.__landscapeCovers = new Set();
    vi.resetModules();
    ({ renderSpotlightHtml } = await import("../js/dashboard-spotlight.js"));
    await import("../js/covers.js");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders initials placeholder instead of hiding the hero", () => {
    const game = {
      store: "steam",
      id: 42,
      name: "Cat Quest III",
      steam_review_percent: 88,
      steam_review_count: 500,
      header_image: "bad.jpg",
      _spotlightReason: { eyebrow: "Solid pick" },
    };
    document.body.innerHTML = renderSpotlightHtml(game);
    const spot = document.getElementById("dashboardSpotlight");
    const img = spot.querySelector(".dash-spotlight-art");
    img.dataset.spotlightCandidates = "bad1.jpg|bad2.jpg";
    img.dataset.spotlightIdx = "1";
    img.src = "bad2.jpg";

    window.spotlightArtFallback(img);

    expect(spot.style.display).not.toBe("none");
    expect(spot.classList.contains("has-art-placeholder")).toBe(true);
    const placeholder = spot.querySelector(".dash-spotlight-art-placeholder");
    expect(placeholder).toBeTruthy();
    expect(placeholder.textContent).toBe("CQI");
  });
});
