/**
 * Add-game modal end-to-end surface (re-audit bucket 1).
 *
 * Drives the real bindAddGameModal() handlers against the real index.html
 * modal markup (hydrated into happy-dom). Covers the three add targets
 * (library / wishlist / itch), duplicate Cancel / Add anyway / Go to existing,
 * the _bypassFor one-shot reset, custom-badge rendering, and offline sync.
 *
 * activeView is pinned to 'dashboard' so refreshAfterManualChange's chrome
 * refresh takes the cheap scheduleDashboardRender branch, and fake timers keep
 * every debounced render from firing mid-assertion.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { hydrateIndexDocument } from "./a11y/hydrate-index.js";

let state;
let bindAddGameModal;
let setAddGameTarget;
let loadManualGames;
let getPersonal;
let storeBadgeHtml;

beforeEach(async () => {
  vi.resetModules();
  localStorage.clear();
  vi.useFakeTimers();
  hydrateIndexDocument();

  ({ state } = await import("../js/state.js"));
  ({ bindAddGameModal, setAddGameTarget } =
    await import("../js/add-game-modal.js"));
  ({ loadManualGames, getPersonal } =
    await import("../js/personal-storage.js"));
  ({ storeBadgeHtml } = await import("../js/game-core.js"));

  state.personal = {};
  state.allGames = [];
  state.wishlistGames = [];
  state.itchGames = [];
  state.activeView = "dashboard";
  window._dataVersion = 0;

  bindAddGameModal();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function setTitle(value) {
  document.getElementById("addGameTitle").value = value;
}

function setPlatform(value) {
  document.getElementById("addGamePlatform").value = value;
}

function clickSkipSteam() {
  document.getElementById("addGameSkipSteam").click();
}

function dupWarnVisible() {
  return !document
    .getElementById("addGameDuplicateWarn")
    .classList.contains("hidden");
}

describe("add-game target routing", () => {
  it("library title-only add lands in state.allGames under the chosen platform", () => {
    setAddGameTarget("library");
    setPlatform("gog");
    setTitle("Outer Wilds");
    clickSkipSteam();

    const manual = loadManualGames();
    expect(manual).toHaveLength(1);
    expect(manual[0]).toMatchObject({
      store: "gog",
      name: "Outer Wilds",
      manual: true,
    });
    expect(manual[0].id).toBe("manual-outer-wilds");
    expect(
      state.allGames.some(
        (g) => g.id === "manual-outer-wilds" && g.store === "gog",
      ),
    ).toBe(true);
    expect(state.itchGames).toHaveLength(0);
  });

  it("wishlist title-only add lands in state.wishlistGames with wish- id + wishlist_store", () => {
    setAddGameTarget("wishlist");
    setPlatform("epic");
    setTitle("Hollow Knight Silksong");
    document.getElementById("addGameWishPrice").value = "29.99";
    document.getElementById("addGameWishDiscount").value = "20";
    clickSkipSteam();

    const manual = loadManualGames();
    expect(manual).toHaveLength(1);
    expect(manual[0]).toMatchObject({
      store: "wishlist",
      wishlist_store: "epic",
      wishlist: true,
      manual: true,
    });
    expect(manual[0].id).toBe("wish-manual-hollow-knight-silksong");
    expect(manual[0].price).toBe("$29.99");
    expect(manual[0].discount_percent).toBe(20);
    expect(state.wishlistGames.some((g) => g.id === manual[0].id)).toBe(true);
    expect(state.allGames).toHaveLength(0);
  });

  it("itch add lands in state.itchGames (regression: not the library catalog)", () => {
    setAddGameTarget("itch");
    setPlatform("itch");
    setTitle("Celeste Classic");
    clickSkipSteam();

    const manual = loadManualGames();
    expect(manual).toHaveLength(1);
    expect(manual[0]).toMatchObject({
      store: "itch",
      manual: true,
      name: "Celeste Classic",
    });
    expect(state.itchGames.some((g) => g.id === "manual-celeste-classic")).toBe(
      true,
    );
    expect(state.allGames.some((g) => g.manual)).toBe(false);
  });

  it("title-only add stores null images and no Steam data", () => {
    setAddGameTarget("library");
    setPlatform("steam");
    setTitle("Some Obscure Game");
    clickSkipSteam();

    const g = loadManualGames()[0];
    expect(g.header_image).toBeNull();
    expect(g.library_image).toBeNull();
    expect(g.steam_review_percent).toBeNull();
  });
});

describe("add-game via Steam match", () => {
  it("imports cover/reviews and stores store=steam with appid id", async () => {
    const match = {
      id: 620,
      name: "Portal 2",
      tiny_image: "http://x/tiny.jpg",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url) => {
        const u = String(url);
        if (u.includes("/api/proxy/steam-search")) {
          return { ok: true, json: async () => ({ items: [match] }) };
        }
        if (u.includes("/api/proxy/steam-reviews")) {
          return {
            ok: true,
            json: async () => ({
              success: 1,
              query_summary: {
                total_reviews: 100,
                total_positive: 98,
                review_score_desc: "Overwhelmingly Positive",
              },
            }),
          };
        }
        return { ok: false, status: 404, json: async () => ({}) };
      }),
    );

    setAddGameTarget("library");
    setPlatform("steam");
    setTitle("Portal 2");
    document.getElementById("addGameSearch").click();
    await vi.waitFor(() => {
      expect(document.querySelector(".add-game-match")).toBeTruthy();
    });
    document.querySelector(".add-game-match").click();
    await vi.waitFor(() => {
      expect(loadManualGames()).toHaveLength(1);
    });

    const g = loadManualGames()[0];
    // id is built as `"" + match.id`, so the stored id is the string form.
    expect(g).toMatchObject({
      store: "steam",
      id: "620",
      manual: true,
      name: "Portal 2",
    });
    expect(g.steam_review_percent).toBe(98);
    expect(g.steam_appid).toBe(620);
  });
});

describe("duplicate detection gate", () => {
  beforeEach(() => {
    state.allGames = [
      { store: "steam", id: 42, name: "Hades", playtime_minutes: 0 },
    ];
  });

  it("Cancel hides the warning and does not add", () => {
    setAddGameTarget("library");
    setTitle("Hades");
    clickSkipSteam();
    expect(dupWarnVisible()).toBe(true);
    expect(loadManualGames()).toHaveLength(0);

    document.getElementById("addGameDupCancel").click();
    expect(dupWarnVisible()).toBe(false);
    expect(loadManualGames()).toHaveLength(0);
  });

  it("Add anyway bypasses the dup check and saves the manual row", () => {
    setAddGameTarget("library");
    setPlatform("gog");
    setTitle("Hades");
    clickSkipSteam();
    expect(dupWarnVisible()).toBe(true);

    document.getElementById("addGameDupAnyway").click();
    expect(loadManualGames()).toHaveLength(1);
    expect(loadManualGames()[0]).toMatchObject({
      store: "gog",
      name: "Hades",
      manual: true,
    });
  });

  it("bypass is one-shot: re-adding the same title warns again", () => {
    setAddGameTarget("library");
    setPlatform("gog");
    setTitle("Hades");
    clickSkipSteam();
    document.getElementById("addGameDupAnyway").click();
    expect(loadManualGames()).toHaveLength(1);

    // Second attempt for the same normalized title must re-trigger the warning,
    // proving _bypassFor was consumed rather than left armed.
    clickSkipSteam();
    expect(dupWarnVisible()).toBe(true);
    expect(loadManualGames()).toHaveLength(1);
  });

  it("typing in the title input clears any armed bypass without throwing", () => {
    setAddGameTarget("library");
    setTitle("Hades");
    const evt = new window.Event("input", { bubbles: true });
    expect(() =>
      document.getElementById("addGameTitle").dispatchEvent(evt),
    ).not.toThrow();
  });

  it("Go to existing closes the modal and keeps the existing game visible", () => {
    // The dup warning only fires for a visible match (findDuplicateMatch
    // excludes hidden by default), so "Go to existing" navigates to it and the
    // defensive unhide is a no-op that must leave the game visible.
    const existing = {
      store: "steam",
      id: 7,
      name: "Bastion",
      playtime_minutes: 0,
    };
    state.allGames = [existing];

    setAddGameTarget("library");
    setTitle("Bastion");
    clickSkipSteam();
    expect(dupWarnVisible()).toBe(true);

    document.getElementById("addGameDupGo").click();
    expect(getPersonal(existing).hidden).toBe(false);
    expect(loadManualGames()).toHaveLength(0);
    expect(
      document.getElementById("addGameModal").classList.contains("hidden"),
    ).toBe(true);
  });

  it("duplicate copy names the itch library for itch-target dupes", () => {
    state.allGames = [];
    state.itchGames = [
      {
        store: "itch",
        id: "i1",
        name: "Untitled Goose Game",
        playtime_minutes: 0,
      },
    ];
    setAddGameTarget("itch");
    setPlatform("itch");
    setTitle("Untitled Goose Game");
    clickSkipSteam();
    expect(dupWarnVisible()).toBe(true);
    expect(
      document.getElementById("addGameDuplicateText").textContent,
    ).toContain("itch library");
  });
});

describe("custom badge rendering", () => {
  it("manual library rows render the dashed-outline custom badge", () => {
    const html = storeBadgeHtml({ store: "gog", name: "Custom", manual: true });
    expect(html).toContain("manual");
    expect(html).toContain("(custom)");
  });
});

describe("offline persistence", () => {
  it("saves manual games to localStorage without a PUT when the server probe never ran", () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    setAddGameTarget("library");
    setPlatform("steam");
    setTitle("Stardew Valley");
    clickSkipSteam();

    // loadManualGames reads straight from localStorage, so a non-empty result
    // proves the row persisted locally.
    expect(loadManualGames()).toHaveLength(1);
    expect(loadManualGames()[0].name).toBe("Stardew Valley");
    // personalStore.apiAvailable starts null, so notify() short-circuits: no network.
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
