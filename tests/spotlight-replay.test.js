/** Spotlight "Replay" category — surfaces finished games occasionally. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    let setStinkerChanceForTest;
    ({ pickSpotlightGames, setStinkerChanceForTest } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
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

  it("caps replay entries to roughly ~3.5% of the pool", () => {
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

describe("spotlight recently added category", () => {
  let pickSpotlightGames;
  let computeRecentSpotlightKeys;
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
    state.libraryFirstSeenByKey = {};
    state.prefs = {};
    win._dataVersion = (win._dataVersion || 0) + 1;
    let setStinkerChanceForTest;
    ({ pickSpotlightGames, computeRecentSpotlightKeys, setStinkerChanceForTest } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
  });

  const libraryGame = (id, rating, count = 500) => ({
    store: "steam",
    id,
    name: `Game ${id}`,
    steam_review_percent: rating,
    steam_review_count: count,
    library_image: "x.jpg",
    header_image: "x.jpg",
  });

  it("surfaces seeded recent additions with the Recently added eyebrow", () => {
    state.prefs.librarySeenSeeded = true;
    state.libraryFirstSeenByKey = {
      "steam:1": 2000,
      "steam:2": 3000,
    };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const games = [libraryGame(1, 85), libraryGame(2, 85), libraryGame(3, 80)];
    const pool = pickSpotlightGames(games);
    const recent = pool.filter(g => g._spotlightReason?.eyebrow === "Recently added");
    expect(recent.map(g => `${g.store}:${g.id}`).sort()).toEqual(["steam:1", "steam:2"]);
    const ordered = [...computeRecentSpotlightKeys(games)];
    expect(ordered[0]).toBe("steam:2");
    expect(ordered[1]).toBe("steam:1");
  });

  it("does not surface Recently added before the library is seeded", () => {
    state.prefs.librarySeenSeeded = false;
    state.libraryFirstSeenByKey = { "steam:1": 9000 };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const pool = pickSpotlightGames([libraryGame(1, 92)]);
    expect(pool.find(g => g._spotlightReason?.eyebrow === "Recently added")).toBeFalsy();
    expect(computeRecentSpotlightKeys([libraryGame(1, 92)]).size).toBe(0);
  });

  it("guarantees recent additions in the pool when score cutoff would drop them", () => {
    state.prefs.librarySeenSeeded = true;
    const now = Date.now();
    state.libraryFirstSeenByKey = {
      "steam:10": now - 3000,
      "steam:11": now - 2000,
      "steam:12": now - 1000,
    };
    const games = [
      libraryGame(10, 82),
      libraryGame(11, 82),
      libraryGame(12, 82),
    ];
    for (let i = 0; i < 80; i++) {
      games.push(libraryGame(1000 + i, 99));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    const pool = pickSpotlightGames(games);
    const recentEyebrows = pool.filter(g => g._spotlightReason?.eyebrow === "Recently added");
    expect(recentEyebrows.length).toBe(3);
    for (const g of recentEyebrows) {
      expect(g._spotlightReason.isRecent).toBe(true);
    }
  });
});

describe("spotlight expanded categories", () => {
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
    state.itadByKey = {};
    state.prefs = { librarySeenSeeded: true };
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;
    let setStinkerChanceForTest;
    ({ pickSpotlightGames, setStinkerChanceForTest } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
  });

  const libraryGame = (id, overrides = {}) => ({
    store: "steam",
    id,
    name: `Game ${id}`,
    steam_review_percent: 85,
    steam_review_count: 1000,
    library_image: "x.jpg",
    header_image: "x.jpg",
    release_date: "2015-01-01",
    hltb_main_hours: 20,
    ...overrides,
  });

  function eyebrowFor(games, id) {
    const pool = pickSpotlightGames(games);
    return pool.find((g) => g.id === id)?._spotlightReason?.eyebrow;
  }

  it("tags coop_online backlog games as Co-op campaign", () => {
    state.personal = { "steam:1": { status: "backlog" } };
    const games = [libraryGame(1, { coop_online: true })];
    expect(eyebrowFor(games, 1)).toBe("Co-op campaign");
  });

  it("excludes live-status games from the spotlight pool", () => {
    state.personal = { "steam:1": { status: "live" } };
    const games = [libraryGame(1, { coop_online: true })];
    expect(pickSpotlightGames(games).length).toBe(0);
  });

  it("tags coop_local backlog games as Couch co-op", () => {
    state.personal = { "steam:2": { status: "backlog" } };
    const games = [libraryGame(2, { coop_local: true })];
    expect(eyebrowFor(games, 2)).toBe("Couch co-op");
  });

  it("does NOT tag on-sale LIBRARY games as On sale now", () => {
    state.personal = { "steam:3": { status: "backlog" } };
    state.itadByKey = { "steam:3": { cut: 40, price: 9.99 } };
    const games = [libraryGame(3)];
    expect(eyebrowFor(games, 3)).not.toBe("On sale now");
  });

  it("tags on-sale WISHLIST games as On sale now", () => {
    state.itadByKey = { "wishlist:3": { cut: 40, price: 9.99 } };
    state.wishlistGames = [{
      store: "wishlist",
      id: 3,
      name: "Wishlist 3",
      steam_review_percent: 85,
      steam_review_count: 1000,
      library_image: "x.jpg",
      header_image: "x.jpg",
    }];
    const pool = pickSpotlightGames([]);
    const sale = pool.find(g => g.store === "wishlist" && g.id === 3);
    expect(sale?._spotlightReason?.eyebrow).toBe("On sale now");
  });

  it("tags recent releases as New release", () => {
    state.personal = { "steam:4": { status: "backlog" } };
    const recent = new Date();
    recent.setMonth(recent.getMonth() - 2);
    const games = [libraryGame(4, { release_date: recent.toISOString().slice(0, 10) })];
    expect(eyebrowFor(games, 4)).toBe("New release");
  });

  it("tags long HLTB titles as Long haul", () => {
    state.personal = { "steam:5": { status: "backlog" } };
    const games = [libraryGame(5, { hltb_main_hours: 50, steam_review_percent: 88 })];
    expect(eyebrowFor(games, 5)).toBe("Long haul");
  });

  it("tags 8–15h titles as Weekend-sized", () => {
    state.personal = { "steam:6": { status: "backlog" } };
    const games = [libraryGame(6, {
      steam_review_percent: 73,
      hltb_main_hours: 10,
      release_date: "2022-06-01",
    })];
    expect(eyebrowFor(games, 6)).toBe("Weekend-sized");
  });

  it("tags near-complete unfinished games as Almost mastered", () => {
    state.personal = { "steam:7": { status: "unfinished" } };
    const games = [libraryGame(7, { trophy_progress: 90 })];
    expect(eyebrowFor(games, 7)).toBe("Almost mastered");
  });

  it("tags mid-progress unfinished games as Pick back up", () => {
    state.personal = { "steam:8": { status: "unfinished" } };
    const games = [libraryGame(8, { trophy_progress: 50 })];
    expect(eyebrowFor(games, 8)).toBe("Pick back up");
  });
});

describe("spotlight rare stinker easter egg", () => {
  let pickSpotlightGames;
  let setStinkerChanceForTest;
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
    state.prefs = {};
    state.libraryFirstSeenByKey = {};
    state.wishlistGames = [];
    state.wishlistCrossStoreHiddenKeys = new Set();
    win._dataVersion = (win._dataVersion || 0) + 1;
    ({ pickSpotlightGames, setStinkerChanceForTest } = await import("../js/dashboard-spotlight.js"));
  });

  const game = (id, rating) => ({
    store: "steam",
    id,
    name: `Game ${id}`,
    steam_review_percent: rating,
    steam_review_count: 1000,
    library_image: "x.jpg",
    header_image: "x.jpg",
  });

  it("fronts the lowest-rated game with the Rare stinker eyebrow when the roll hits", () => {
    setStinkerChanceForTest(1);
    state.personal = {
      "steam:1": { status: "backlog" },
      "steam:2": { status: "backlog" },
      "steam:3": { status: "backlog" },
    };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const games = [game(1, 92), game(2, 41), game(3, 85)];
    const pool = pickSpotlightGames(games);
    expect(pool[0].id).toBe(2);
    expect(pool[0]._spotlightReason.eyebrow).toBe("Rare stinker");
    expect(pool[0]._spotlightReason.isStinker).toBe(true);
    // The stinker is not duplicated in the pool.
    expect(pool.filter(g => g.id === 2).length).toBe(1);
  });

  it("never surfaces the stinker when the chance is zero", () => {
    setStinkerChanceForTest(0);
    state.personal = { "steam:2": { status: "backlog" } };
    window._dataVersion = (window._dataVersion || 0) + 1;
    const games = [game(1, 92), game(2, 41)];
    const pool = pickSpotlightGames(games);
    expect(pool.find(g => g._spotlightReason?.isStinker)).toBeFalsy();
  });
});

describe("spotlight rotation safety", () => {
  beforeEach(async () => {
    const win = new Window({ url: "http://127.0.0.1:8765/" });
    global.window = win;
    global.document = win.document;
    global.localStorage = win.localStorage;
    win.__dashFailedCovers = new Set();
    vi.useFakeTimers();
    vi.resetModules();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("stopSpotlightRotation prevents fade timer from mutating innerHTML after click", async () => {
    const { startSpotlightRotation, stopSpotlightRotation } = await import("../js/dashboard-spotlight.js");
    const games = [
      { store: "steam", id: "1", name: "A", steam_review_percent: 90, steam_review_count: 500, library_image: "a.jpg", header_image: "a.jpg" },
      { store: "steam", id: "2", name: "B", steam_review_percent: 88, steam_review_count: 500, library_image: "b.jpg", header_image: "b.jpg" },
    ];
    games[0]._spotlightReason = { eyebrow: "Highly rated", score: 90 };
    games[1]._spotlightReason = { eyebrow: "Solid pick", score: 85 };

    document.body.innerHTML = `
      <button type="button" class="dash-spotlight" id="dashboardSpotlight" data-key="steam:1">
        <span id="spot-inner">slide-1</span>
      </button>
    `;
    const el = document.getElementById("dashboardSpotlight");
    el.dataset.key = "steam:1";

    startSpotlightRotation(games);
    vi.advanceTimersByTime(7000);
    expect(el.classList.contains("is-fading")).toBe(true);

    stopSpotlightRotation();
    const htmlBefore = el.innerHTML;
    vi.advanceTimersByTime(500);
    expect(el.innerHTML).toBe(htmlBefore);
    expect(el.classList.contains("is-fading")).toBe(false);
  });
});
