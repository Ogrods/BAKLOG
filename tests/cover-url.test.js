/** sanitizeCoverUrl + libraryCoverFor */
import { describe, expect, it } from "vitest";
import {
  coverFallbackFor,
  libraryCoverFor,
  sanitizeCoverUrl,
  spotlightArtCandidates,
  spotlightCropForAspect,
  steamAppIdFromGame,
  steamLibraryHeroUrl,
} from "../js/game-core.js";

describe("sanitizeCoverUrl", () => {
  it("rewrites Xbox EDS host to SSL variant", () => {
    const bad = "https://images-eds.xboxlive.com/image?url=abc";
    expect(sanitizeCoverUrl(bad)).toBe("https://images-eds-ssl.xboxlive.com/image?url=abc");
  });

  it("leaves other URLs unchanged", () => {
    const ms = "https://store-images.s-microsoft.com/image/apps.1";
    expect(sanitizeCoverUrl(ms)).toBe(ms);
  });
});

describe("libraryCoverFor", () => {
  it("prefers sanitized library_image", () => {
    const g = {
      store: "xbox",
      id: "1",
      library_image: "https://images-eds.xboxlive.com/image?url=x",
      header_image: "https://images-eds.xboxlive.com/image?url=y",
    };
    expect(libraryCoverFor(g)).toBe("https://images-eds-ssl.xboxlive.com/image?url=x");
  });

  it("falls back to sanitized header_image", () => {
    const g = {
      store: "xbox",
      id: "1",
      header_image: "https://images-eds.xboxlive.com/image?url=y",
    };
    expect(libraryCoverFor(g)).toBe("https://images-eds-ssl.xboxlive.com/image?url=y");
    expect(coverFallbackFor(g)).toBe("https://images-eds-ssl.xboxlive.com/image?url=y");
  });
});

describe("spotlight art (A+B)", () => {
  it("steamLibraryHeroUrl uses akamai CDN", () => {
    expect(steamLibraryHeroUrl(1145360)).toBe(
      "https://cdn.akamai.steamstatic.com/steam/apps/1145360/library_hero.jpg",
    );
  });

  it("spotlightArtCandidates prefers library_hero then header for Steam", () => {
    const g = {
      store: "steam",
      id: 367520,
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/367520/header.jpg",
      library_image: "https://cdn.akamai.steamstatic.com/steam/apps/367520/library_600x900.jpg",
    };
    const c = spotlightArtCandidates(g);
    expect(c[0]).toBe(steamLibraryHeroUrl(367520));
    expect(c[1]).toBe(g.header_image);
    expect(c).toContain(g.library_image);
  });

  it("steamAppIdFromGame parses app id from steamstatic URLs", () => {
    expect(steamAppIdFromGame({
      store: "gog",
      id: "x",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/413150/header.jpg",
    })).toBe("413150");
  });

  it("spotlightCropForAspect picks cover vs portrait contain", () => {
    expect(spotlightCropForAspect(2.5)).toEqual({ fit: "cover", pos: "50% 40%", portrait: false });
    expect(spotlightCropForAspect(1.6)).toEqual({ fit: "cover", pos: "35% center", portrait: false });
    expect(spotlightCropForAspect(0.67)).toEqual({ fit: "cover", pos: "center top", portrait: false });
  });
});
