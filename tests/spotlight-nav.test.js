/** Spotlight prev/next manual navigation. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";
import { gameKey } from "../js/game-core.js";

describe("spotlight nav arrows", () => {
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
      stepSpotlight,
      SPOTLIGHT_FADE_MS,
      setStinkerChanceForTest,
    } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
  });

  afterEach(() => {
    stopSpotlightRotation?.();
    vi.useRealTimers();
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
    const el = document.getElementById("dashboardSpotlight");
    expect(el.dataset.key).toBe(gameKey(pool[0]));
    startSpotlightRotation(pool);
    return { pool, el };
  }

  it("steps forward and back with wrap", () => {
    const games = [];
    for (let i = 0; i < 5; i++) {
      state.personal[`steam:${i + 1}`] = { status: "backlog" };
      games.push(libraryGame(i + 1, 80 + i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const { pool, el } = mountPool(games);

    stepSpotlight(1);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(gameKey(pool[1]));

    stepSpotlight(-1);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(gameKey(pool[0]));
  });

  it("is a no-op when the pool has one game", () => {
    state.personal = { "steam:1": { status: "backlog" } };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const pool = pickSpotlightGames([libraryGame(1, 92)]);
    expect(pool.length).toBe(1);
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    const el = document.getElementById("dashboardSpotlight");
    const keyBefore = el.dataset.key;
    startSpotlightRotation(pool);
    expect(() => stepSpotlight(1)).not.toThrow();
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
    expect(el.dataset.key).toBe(keyBefore);
  });
});
