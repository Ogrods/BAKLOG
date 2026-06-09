/** Spotlight auto-rotation respects prefers-reduced-motion. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

describe("spotlight reduced motion", () => {
  let pickSpotlightGames;
  let renderSpotlightHtml;
  let startSpotlightRotation;
  let stopSpotlightRotation;
  let isSpotlightRotationActive;
  let toggleSpotlightPause;
  let SPOTLIGHT_INTERVAL_MS;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    win.matchMedia = vi.fn((query) => ({
      matches: query.includes("prefers-reduced-motion"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }));

    vi.useFakeTimers();
    vi.resetModules();
    ({ state } = await import("../js/state.js"));
    state.personal = {};
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;
    let setStinkerChanceForTest;
    let setScoreJitterForTest;
    ({
      pickSpotlightGames,
      renderSpotlightHtml,
      startSpotlightRotation,
      stopSpotlightRotation,
      isSpotlightRotationActive,
      toggleSpotlightPause,
      SPOTLIGHT_INTERVAL_MS,
      setStinkerChanceForTest,
      setScoreJitterForTest,
    } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
    setScoreJitterForTest(0);
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
    library_image: "x.jpg",
    header_image: "x.jpg",
    release_date: "2015-01-01",
    hltb_main_hours: 20,
  });

  function mountPool(games) {
    const pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThan(1);
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    startSpotlightRotation(pool);
    return pool;
  }

  it("does not auto-start rotation when reduced motion is preferred", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    mountPool(games);
    expect(isSpotlightRotationActive()).toBe(false);
    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS + 500);
    expect(document.getElementById("dashboardSpotlight").dataset.key).toBeTruthy();
  });

  it("allows opt-in rotation via pause/play", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const pool = mountPool(games);
    const keyBefore = document.getElementById("dashboardSpotlight").dataset.key;

    toggleSpotlightPause();
    expect(isSpotlightRotationActive()).toBe(true);
    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS + 500);
    expect(document.getElementById("dashboardSpotlight").dataset.key).not.toBe(keyBefore);
    expect(document.getElementById("dashboardSpotlight").dataset.key).toBeTruthy();
    expect(pool.length).toBeGreaterThan(1);
  });
});
