/** Spotlight "Cat game" wildcard category + "cat games" marquee stat. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Window } from "happy-dom";

vi.mock("../js/deals.js", () => ({
  getDealInfo: vi.fn(() => null),
  dealScore: vi.fn(() => 0),
  isStealDeal: vi.fn(() => false),
  cutBucketClass: vi.fn(() => "cut-low"),
  computeWishlistWoba: vi.fn(() => null),
  isCleanupCandidate: vi.fn(() => false),
  parsePriceLike: vi.fn((v) => {
    if (v == null) return null;
    if (typeof v === "number") return v;
    const m = String(v).match(/-?\d+(?:\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }),
}));

describe("spotlight cat game category", () => {
  let pickSpotlightGames;
  let setStinkerChanceForTest;
  let setRandomPickChanceForTest;
  let setCatGameChanceForTest;
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
    ({
      pickSpotlightGames,
      setStinkerChanceForTest,
      setRandomPickChanceForTest,
      setCatGameChanceForTest,
    } = await import("../js/dashboard-spotlight.js"));
    setStinkerChanceForTest(0);
    setRandomPickChanceForTest(0);
    setCatGameChanceForTest(1);
  });

  const libraryGame = (id, name, rating = 85) => ({
    store: "steam",
    id,
    name,
    steam_review_percent: rating,
    steam_review_count: 1000,
    library_image: "x.jpg",
    header_image: "x.jpg",
  });

  function buildLibrary(games) {
    for (const g of games) {
      state.personal[`steam:${g.id}`] = { status: "backlog" };
    }
    window._dataVersion = (window._dataVersion || 0) + 1;
    return games;
  }

  it("injects exactly one Cat game when a title contains cat as a whole word", () => {
    const games = buildLibrary([
      libraryGame("1", "The Cat Lady"),
      libraryGame("2", "Generic Game"),
      libraryGame("3", "Another Title"),
    ]);
    const pool = pickSpotlightGames(games);
    const cats = pool.filter(g => g._spotlightReason?.isCatGame);
    expect(cats.length).toBe(1);
    expect(cats[0]._spotlightReason.eyebrow).toBe("Cat game");
    expect(cats[0].name).toBe("The Cat Lady");
    const key = `${cats[0].store}:${cats[0].id}`;
    expect(pool.filter(g => `${g.store}:${g.id}` === key).length).toBe(1);
  });

  it("rejects substrings inside other words (word-boundary match)", () => {
    const games = buildLibrary([
      libraryGame("1", "Category Master"),
      libraryGame("2", "Scatter"),
      libraryGame("3", "Delicate"),
    ]);
    const pool = pickSpotlightGames(games);
    expect(pool.find(g => g._spotlightReason?.isCatGame)).toBeFalsy();
  });

  it("never appears when the chance is zero", () => {
    setCatGameChanceForTest(0);
    const games = buildLibrary([
      libraryGame("1", "The Cat Lady"),
      libraryGame("2", "Generic Game"),
    ]);
    const pool = pickSpotlightGames(games);
    expect(pool.find(g => g._spotlightReason?.isCatGame)).toBeFalsy();
  });
});

describe("cat game eyebrow variant + family", () => {
  it("exposes Here, kitty as a display variant of Cat game", async () => {
    const { EYEBROW_VARIANTS, eyebrowVariant } = await import("../js/metric-tips.js");
    const variants = EYEBROW_VARIANTS["Cat game"];
    expect(variants).toContain("Here, kitty");
    const seen = new Set();
    for (let i = 0; i < 200; i++) seen.add(eyebrowVariant("Cat game", `steam:${i}`));
    for (const label of seen) expect(variants).toContain(label);
  });

  it("classifies Cat game and variants as the WILDCARD family", async () => {
    const { familyForEyebrow, FAMILY } = await import("../js/stat-families.js");
    expect(familyForEyebrow("Cat game")).toBe(FAMILY.WILDCARD);
    expect(familyForEyebrow("Here, kitty")).toBe(FAMILY.WILDCARD);
    expect(familyForEyebrow("Meow")).toBe(FAMILY.WILDCARD);
    expect(familyForEyebrow("Cat content")).toBe(FAMILY.WILDCARD);
  });
});

describe("cat games marquee stat", () => {
  beforeEach(async () => {
    vi.resetModules();
    vi.doMock("../js/personal-storage.js", () => ({
      getPersonal: vi.fn((g) => g._personal || { status: "backlog" }),
    }));
    vi.doMock("../js/deals.js", () => ({
      getDealInfo: vi.fn(() => null),
      dealScore: vi.fn(() => 0),
      isStealDeal: vi.fn(() => false),
      cutBucketClass: vi.fn(() => "cut-low"),
      computeWishlistWoba: vi.fn(() => null),
      isCleanupCandidate: vi.fn(() => false),
      parsePriceLike: vi.fn((v) => {
        if (v == null) return null;
        if (typeof v === "number") return v;
        const m = String(v).match(/-?\d+(?:\.\d+)?/);
        return m ? parseFloat(m[0]) : null;
      }),
    }));
  });

  it("counts titles containing cat as a substring", async () => {
    const { state } = await import("../js/state.js");
    const { buildMarqueeItems } = await import("../js/dashboard-insights.js");
    const { getLibrarySnapshot } = await import("../js/sabermetrics.js");

    state.prefs = { quickWinMaxHours: 15 };
    state.wishlistGames = [];
    state.itchGames = [];

    const games = [
      {
        store: "steam",
        id: "1",
        name: "The Cat Lady",
        steam_review_percent: 85,
        steam_review_count: 100,
        hltb_main_hours: 10,
        _personal: { status: "backlog" },
      },
      {
        store: "steam",
        id: "2",
        name: "Scatterblast",
        steam_review_percent: 80,
        steam_review_count: 100,
        hltb_main_hours: 5,
        _personal: { status: "backlog" },
      },
      {
        store: "steam",
        id: "3",
        name: "Plain Game",
        steam_review_percent: 90,
        steam_review_count: 100,
        hltb_main_hours: 8,
        _personal: { status: "backlog" },
      },
    ];
    const snap = getLibrarySnapshot(games);
    const items = buildMarqueeItems(games, snap);
    const catChip = items.find(it => it.label === "cat games");
    expect(catChip).toBeTruthy();
    expect(catChip.valueHtml).toBe("2");
  });
});
