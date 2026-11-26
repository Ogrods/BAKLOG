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

  it("expands Nintendo atum CDN size placeholders", () => {
    const raw = "https://atum-img-lp1.cdn.nintendo.net/i/c/abc_${size}";
    expect(sanitizeCoverUrl(raw)).toBe(
      "https://atum-img-lp1.cdn.nintendo.net/i/c/abc_256",
    );
  });

  it("rewrites mangled GOG glx_bg_top_padding URLs to vertical cover", () => {
    const hash = "11b5d020144f3ef465bc36c4d375e579fa65e2858b4f58cdd5540a049b9a6982";
    const mangled =
      `https://images.gog.com/${hash}_glx_bg_top_padding_7.webp?namespace=gamesdb_glx_vertical_cover.jpg`;
    expect(sanitizeCoverUrl(mangled)).toBe(
      `https://images.gog.com/${hash}_glx_vertical_cover.jpg`,
    );
  });

  it("leaves clean GOG vertical covers unchanged", () => {
    const hash = "11b5d020144f3ef465bc36c4d375e579fa65e2858b4f58cdd5540a049b9a6982";
    const ok = `https://images.gog.com/${hash}_glx_vertical_cover.jpg`;
    expect(sanitizeCoverUrl(ok)).toBe(ok);
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

  it("spotlightArtCandidates prefers 600x900 capsule before hero for Steam", () => {
    const g = {
      store: "steam",
      id: 367520,
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/367520/header.jpg",
      library_image: "https://cdn.akamai.steamstatic.com/steam/apps/367520/library_600x900.jpg",
    };
    const c = spotlightArtCandidates(g);
    expect(c[0]).toBe(
      "https://cdn.akamai.steamstatic.com/steam/apps/367520/library_600x900_2x.jpg",
    );
    expect(c[1]).toBe(g.library_image);
    const heroIdx = c.indexOf(steamLibraryHeroUrl(367520));
    const portraitIdx = c.indexOf(g.library_image);
    expect(heroIdx).toBeGreaterThan(portraitIdx);
    expect(c).toContain(g.header_image);
    const headerIdx = c.indexOf(g.header_image);
    expect(headerIdx).toBeGreaterThan(heroIdx);
  });

  it("steamAppIdFromGame parses app id from steamstatic URLs", () => {
    expect(steamAppIdFromGame({
      store: "gog",
      id: "x",
      header_image: "https://cdn.akamai.steamstatic.com/steam/apps/413150/header.jpg",
    })).toBe("413150");
  });

  it("spotlightCropForAspect picks cover vs portrait/square contain", () => {
    expect(spotlightCropForAspect(2.5)).toEqual({
      fit: "cover", pos: "58% 40%", portrait: false, square: false,
    });
    expect(spotlightCropForAspect(1.6)).toEqual({
      fit: "cover", pos: "35% center", portrait: false, square: false,
    });
    expect(spotlightCropForAspect(1.3)).toEqual({
      fit: "cover", pos: "35% center", portrait: false, square: false,
    });
    expect(spotlightCropForAspect(1.0)).toEqual({
      fit: "contain", pos: "center", portrait: true, square: true,
    });
    expect(spotlightCropForAspect(0.67)).toEqual({
      fit: "contain", pos: "center", portrait: true, square: false,
    });
  });
});
