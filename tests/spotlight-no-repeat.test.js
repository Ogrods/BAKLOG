/** Spotlight no-repeat window: a shown slide can't reappear for ~25 rotations. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { gameKey } from "../js/game-core.js";
import { Window } from "happy-dom";

describe("spotlight no-repeat window", () => {
  let pickSpotlightGames;
  let renderSpotlightHtml;
  let startSpotlightRotation;
  let stopSpotlightRotation;
  let getSpotlightRecentKeysForTest;
  let resetSpotlightRecentKeysForTest;
  let SPOTLIGHT_INTERVAL_MS;
  let SPOTLIGHT_FADE_MS;
  let SPOTLIGHT_NO_REPEAT_WINDOW;
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
    let setRandomPickChanceForTest;
    let setCatGameChanceForTest;
    ({
      pickSpotlightGames,
      renderSpotlightHtml,
      startSpotlightRotation,
      stopSpotlightRotation,
      getSpotlightRecentKeysForTest,
      resetSpotlightRecentKeysForTest,
      SPOTLIGHT_INTERVAL_MS,
      SPOTLIGHT_FADE_MS,
      SPOTLIGHT_NO_REPEAT_WINDOW,
      setStinkerChanceForTest,
      setRandomPickChanceForTest,
      setCatGameChanceForTest,
    } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(0);
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

  function buildLibrary(n) {
    const games = [];
    for (let i = 1; i <= n; i++) {
      state.personal[`steam:${i}`] = { status: "backlog" };
      games.push(libraryGame(i, 80 + (i % 15)));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    return games;
  }

  // Drive exactly one rotation, keeping the fake-timer clock aligned to the
  // setInterval period. Each interval fire schedules a fade SPOTLIGHT_FADE_MS
  // later, so a rotation costs (interval fire + fade apply). Advancing
  // INTERVAL + FADE every tick would drift FADE ms per tick and eventually
  // double-fire the interval in a single advance, so after the first prime we
  // split the advance into (INTERVAL - FADE) + FADE, which nets exactly
  // INTERVAL and stays phase-locked to the timer.
  function prime() {
    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
  }
  function tick() {
    vi.advanceTimersByTime(SPOTLIGHT_INTERVAL_MS - SPOTLIGHT_FADE_MS);
    vi.advanceTimersByTime(SPOTLIGHT_FADE_MS);
  }

  it("never repeats a slide within the no-repeat window, even across reshuffles", () => {
    const games = buildLibrary(40);
    resetSpotlightRecentKeysForTest();

    let pool = pickSpotlightGames(games);
    expect(pool.length).toBeGreaterThan(SPOTLIGHT_NO_REPEAT_WINDOW);
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    const el = document.getElementById("dashboardSpotlight");
    startSpotlightRotation(pool);

    const window = Math.min(SPOTLIGHT_NO_REPEAT_WINDOW, pool.length - 1);
    prime();
    const shown = [el.dataset.key];

    for (let i = 0; i < 120; i++) {
      // Reshuffle the pool partway through to simulate a dashboard re-render —
      // the no-repeat history must persist and still be honored.
      if (i > 0 && i % 17 === 0) {
        pool = pickSpotlightGames(games);
        startSpotlightRotation(pool);
      }
      tick();
      const key = el.dataset.key;
      const recentWindow = shown.slice(-window);
      expect(recentWindow).not.toContain(key);
      shown.push(key);
    }
  });

  it("falls back to plain cycling when the pool is smaller than the window", () => {
    const games = buildLibrary(6);
    resetSpotlightRecentKeysForTest();
    const pool = pickSpotlightGames(games);
    document.body.innerHTML = renderSpotlightHtml(pool[0]);
    const el = document.getElementById("dashboardSpotlight");
    startSpotlightRotation(pool);

    // With a 6-slide pool the effective window is 5, so a full cycle still
    // surfaces every game once before any repeat.
    const seen = new Set([el.dataset.key]);
    prime();
    seen.add(el.dataset.key);
    for (let i = 0; i < pool.length; i++) {
      tick();
      seen.add(el.dataset.key);
    }
    expect(seen.size).toBe(pool.length);
    expect(getSpotlightRecentKeysForTest().length).toBeGreaterThan(0);
  });
});
