/** Spotlight "Random pick" / "Dealer's choice" wildcard category. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

describe("spotlight random pick category", () => {
  let pickSpotlightGames;
  let setStinkerChanceForTest;
  let setRandomPickChanceForTest;
  let setScoreJitterForTest;
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
    ({ pickSpotlightGames, setStinkerChanceForTest, setRandomPickChanceForTest, setScoreJitterForTest } =
      await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(1);
    setScoreJitterForTest(0);
  });

  const libraryGame = (id, rating = 85) => ({
    store: "steam",
    id,
    name: `Game ${id}`,
    steam_review_percent: rating,
    steam_review_count: 1000,
    library_image: "x.jpg",
    header_image: "x.jpg",
  });

  function buildLibrary(n) {
    const games = [];
    for (let i = 1; i <= n; i++) {
      state.personal[`steam:${i}`] = { status: "backlog" };
      games.push(libraryGame(i));
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    return games;
  }

  it("injects exactly one Random pick from the library for a real library", () => {
    const pool = pickSpotlightGames(buildLibrary(20));
    const randoms = pool.filter(g => g._spotlightReason?.isRandom);
    expect(randoms.length).toBe(1);
    expect(randoms[0]._spotlightReason.eyebrow).toBe("Random pick");
    // Library-only (never a wishlist title).
    expect(randoms[0].store).toBe("steam");
    // No duplicate of the chosen game.
    const key = `${randoms[0].store}:${randoms[0].id}`;
    expect(pool.filter(g => `${g.store}:${g.id}` === key).length).toBe(1);
  });

  it("does not inject a Random pick for tiny libraries", () => {
    const pool = pickSpotlightGames(buildLibrary(3));
    expect(pool.find(g => g._spotlightReason?.isRandom)).toBeFalsy();
  });

  it("never appears when the chance is zero", () => {
    setRandomPickChanceForTest(0);
    const pool = pickSpotlightGames(buildLibrary(20));
    expect(pool.find(g => g._spotlightReason?.isRandom)).toBeFalsy();
  });

  it("never relabels a quota-protected recently-added game", () => {
    state.prefs.librarySeenSeeded = true;
    const now = Date.now();
    const games = buildLibrary(20);
    // Mark the first five as recent additions (quota-protected).
    for (let i = 1; i <= 5; i++) {
      state.libraryFirstSeenByKey[`steam:${i}`] = now - i * 1000;
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    // Run several builds so the random pick samples many candidates.
    for (let r = 0; r < 30; r++) {
      const pool = pickSpotlightGames(games);
      const recents = pool.filter(g => g._spotlightReason?.eyebrow === "Recently added");
      expect(recents.length).toBeGreaterThanOrEqual(1);
    }
  });
});

describe("random pick eyebrow variant + family", () => {
  it("exposes Dealer's choice as a display variant of Random pick", async () => {
    const { EYEBROW_VARIANTS, eyebrowVariant } = await import("../js/metric-tips.js");
    const variants = EYEBROW_VARIANTS["Random pick"];
    expect(variants).toContain("Dealer\u2019s choice");
    const seen = new Set();
    for (let i = 0; i < 200; i++) seen.add(eyebrowVariant("Random pick", `steam:${i}`));
    for (const label of seen) expect(variants).toContain(label);
  });

  it("classifies Random pick and Dealer's choice as the WILDCARD family", async () => {
    const { familyForEyebrow, FAMILY } = await import("../js/stat-families.js");
    expect(familyForEyebrow("Random pick")).toBe(FAMILY.WILDCARD);
    expect(familyForEyebrow("Dealer\u2019s choice")).toBe(FAMILY.WILDCARD);
    expect(familyForEyebrow("Wild card")).toBe(FAMILY.WILDCARD);
  });
});
