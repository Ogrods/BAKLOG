/** Spotlight portrait tilt re-syncs when the slide changes while the pointer stays over the card. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import { gameKey } from "../js/game-core.js";

describe("spotlight hover sync after slide", () => {
  let pickSpotlightGames;
  let renderSpotlightHtml;
  let startSpotlightRotation;
  let stopSpotlightRotation;
  let stepSpotlight;
  let SPOTLIGHT_FADE_MS;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.__landscapeCovers = new Set();

    vi.useFakeTimers();
    vi.resetModules();
    ({ state } = await import("../js/state.js"));
    state.personal = {};
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;
    await import("../js/covers.js");
    let setStinkerChanceForTest;
    ({
      pickSpotlightGames,
      renderSpotlightHtml,
      startSpotlightRotation,
      stopSpotlightRotation,
      stepSpotlight,
      SPOTLIGHT_FADE_MS,
      setStinkerChanceForTest,
    } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
  });

  afterEach(() => {
    stopSpotlightRotation?.();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  const libraryGame = (id, rating = 85) => ({
    store: "steam",
    id,
    name: `Game ${id}`,
    steam_review_percent: rating,
    steam_review_count: 1000,
    library_image: "portrait.jpg",
    header_image: "hero.jpg",
    release_date: "2015-01-01",
    hltb_main_hours: 20,
  });

  function mountPool(games) {
    const pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThan(1);
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    const el = document.getElementById("dashboardSpotlight");
    startSpotlightRotation(pool);
    return { pool, el };
  }

  function stubArtDimensions(img, width, height) {
    Object.defineProperty(img, "naturalWidth", { value: width, configurable: true });
    Object.defineProperty(img, "naturalHeight", { value: height, configurable: true });
    img.classList.add("is-loaded");
    window.applySpotlightArtFit(img);
  }

  function stubPortrait(el) {
    stubArtDimensions(el.querySelector(".dash-spotlight-art"), 600, 900);
  }

  function stubLandscape(el) {
    stubArtDimensions(el.querySelector(".dash-spotlight-art"), 1920, 1080);
  }

  function simulatePointerHover(el, x = 120, y = 80) {
    vi.spyOn(el, "matches").mockImplementation((sel) => {
      if (sel === ":hover") return true;
      return Element.prototype.matches.call(el, sel);
    });
    el.dispatchEvent(
      new PointerEvent("pointerenter", {
        clientX: x,
        clientY: y,
        pointerType: "mouse",
        bubbles: true,
      }),
    );
  }

  it("arms portrait tilt after slide while pointer stays over the card", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const { pool, el } = mountPool(games);

    stubPortrait(el);
    simulatePointerHover(el);
    expect(el.classList.contains("has-portrait-art")).toBe(true);
    expect(el.classList.contains("is-tilting")).toBe(true);

    stepSpotlight(1);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(gameKey(pool[1]));

    stubPortrait(el);
    expect(el.classList.contains("has-portrait-art")).toBe(true);
    expect(el.classList.contains("is-tilting")).toBe(true);
  });

  it("clears tilt when slide changes to landscape while still hovered", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const { el } = mountPool(games);

    stubPortrait(el);
    simulatePointerHover(el);
    expect(el.classList.contains("is-tilting")).toBe(true);

    stepSpotlight(1);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);

    stubLandscape(el);
    expect(el.classList.contains("has-portrait-art")).toBe(false);
    expect(el.classList.contains("is-tilting")).toBe(false);
  });
});
