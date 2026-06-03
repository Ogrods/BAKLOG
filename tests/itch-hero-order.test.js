import { describe, it, expect } from "vitest";
import { gameKey } from "../js/game-core.js";

/** Mirrors dashboard-cards.js shuffle/signature for unit coverage. */
function shuffleCopy(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function itchHeroOrderSignature(candidates) {
  return candidates.map((g) => gameKey(g)).sort().join("\0");
}

describe("itch featured hero order", () => {
  it("signature is stable regardless of input order", () => {
    const a = { store: "itch", itch_id: "1", name: "A" };
    const b = { store: "itch", itch_id: "2", name: "B" };
    expect(itchHeroOrderSignature([a, b])).toBe(itchHeroOrderSignature([b, a]));
  });

  it("shuffleCopy preserves multiset", () => {
    const items = [{ store: "itch", itch_id: "1" }, { store: "itch", itch_id: "2" }, { store: "itch", itch_id: "3" }];
    const shuffled = shuffleCopy(items);
    expect(shuffled.map((g) => g.itch_id).sort()).toEqual(["1", "2", "3"]);
  });
});
