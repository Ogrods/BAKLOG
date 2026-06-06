/** Spotlight pause/play toggles the rotation timer. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import { gameKey } from "../js/game-core.js";

describe("spotlight pause/play", () => {
  let pickSpotlightGames;
  let renderSpotlightHtml;
  let startSpotlightRotation;
  let stopSpotlightRotation;
  let toggleSpotlightPause;
  let isSpotlightRotationActive;
  let getSpotlightPaused;
  let SPOTLIGHT_INTERVAL_MS;
  let SPOTLIGHT_FADE_MS;
  let state;

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
    ({
      pickSpotlightGames,
      renderSpotlightHtml,
      startSpotlightRotation,
      stopSpotlightRotation,
      toggleSpotlightPause,
      isSpotlightRotationActive,
      getSpotlightPaused,
      SPOTLIGHT_INTERVAL_MS,
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
    return { pool, el: document.getElementById("dashboardSpotlight") };
  }

  it("starts rotation by default and pauses/resumes on toggle", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const { pool, el } = mountPool(games);
    const startKey = el.dataset.key;

    expect(isSpotlightRotationActive()).toBe(true);
    toggleSpotlightPause();
    expect(getSpotlightPaused()).toBe(true);
    expect(isSpotlightRotationActive()).toBe(false);

    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS + SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(startKey);

    toggleSpotlightPause();
    expect(getSpotlightPaused()).toBe(false);
    expect(isSpotlightRotationActive()).toBe(true);
    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS + SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(gameKey(pool[1]));
  });
});
