/** Spotlight "Replay" category — surfaces finished games occasionally. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

describe("spotlight replay category", () => {
  let pickSpotlightGames;
  let state;

  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();

    vi.resetModules();
    ({ state } = await import("../js/state.js"));
    state.personal = {};
    win._dataVersion = (win._dataVersion || 0) + 1;
    ({ pickSpotlightGames } = await import("../js/dashboard-spotlight.js"));
  });

  const finishedGame = (id, rating, count = 1000) => ({
    store: "steam",
    id,
    name: `Finished ${id}`,
    steam_review_percent: rating,
    steam_review_count: count,
    library_image: "x.jpg",
    header_image: "x.jpg",
    playtime_minutes: 600,
  });
  const backlogGame = (id, rating, count = 500) => ({
    store: "steam",
    id,
    name: `Backlog ${id}`,
    steam_review_percent: rating,
    steam_review_count: count,
    library_image: "x.jpg",
    header_image: "x.jpg",
  });

  it("tags eligible finished games with the Replay eyebrow", () => {
    state.personal = {
      "steam:100": { status: "finished" },
      "steam:200": { status: "backlog" },
    };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const games = [finishedGame(100, 92), backlogGame(200, 88)];
    const pool = pickSpotlightGames(games);
    const replay = pool.find(g => g._spotlightReason?.isReplay);
    expect(replay).toBeTruthy();
    expect(replay._spotlightReason.eyebrow).toBe("Replay");
  });

  it("skips finished games with low ratings or insufficient reviews", () => {
    state.personal = {
      "steam:100": { status: "finished" },
      "steam:101": { status: "finished" },
    };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const games = [
      finishedGame(100, 70),
      finishedGame(101, 90, 10),
      backlogGame(200, 85),
    ];
    const pool = pickSpotlightGames(games);
    expect(pool.find(g => g._spotlightReason?.isReplay)).toBeFalsy();
  });

  it("caps replay entries to roughly ~6% of the pool", () => {
    state.personal = {};
    const games = [];
    for (let i = 0; i < 60; i++) {
      games.push(backlogGame(1000 + i, 85));
    }
    for (let i = 0; i < 60; i++) {
      state.personal[`steam:${2000 + i}`] = { status: "finished" };
      games.push(finishedGame(2000 + i, 92));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;

    const pool = pickSpotlightGames(games);
    const replays = pool.filter(g => g._spotlightReason?.isReplay).length;
    expect(pool.length).toBeGreaterThan(20);
    const ratio = replays / pool.length;
    expect(ratio).toBeGreaterThan(0);
    expect(ratio).toBeLessThanOrEqual(0.12);
  });
});
