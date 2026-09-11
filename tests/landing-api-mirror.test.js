/* @vitest-environment node */
import { describe, expect, it } from "vitest";
import {
  isAllowedOrigin,
  mergeProfileListRows,
} from "../web/api/_mirror-helpers.js";

describe("landing mirror CORS + list helpers", () => {
  it("allows baklog.app and local app ports only", () => {
    expect(isAllowedOrigin("https://baklog.app")).toBe(true);
    expect(isAllowedOrigin("http://127.0.0.1:8765")).toBe(true);
    expect(isAllowedOrigin("http://localhost:8766")).toBe(true);
    expect(isAllowedOrigin("http://127.0.0.1")).toBe(false);
    expect(isAllowedOrigin("http://127.0.0.1:80")).toBe(false);
    expect(isAllowedOrigin("https://evil.example")).toBe(false);
    expect(isAllowedOrigin("")).toBe(false);
  });

  it("merges non-recursive data/ children into artifact paths", () => {
    const merged = mergeProfileListRows(
      [
        { name: "games_steam.json", id: "1", updated_at: "2026-01-01" },
        { name: "data", id: null },
        { name: "free_claims.json", id: "x" },
      ],
      [{ name: "personal.json", id: "2", updated_at: "2026-01-02" }],
      "default",
    );
    expect(merged.map((row) => row.path)).toEqual([
      "data/personal.json",
      "games_steam.json",
    ]);
    expect(merged.every((row) => row.profile === "default")).toBe(true);
  });
});
