/** sanitizeCoverUrl + libraryCoverFor */
import { describe, expect, it } from "vitest";
import { coverFallbackFor, libraryCoverFor, sanitizeCoverUrl } from "../js/game-core.js";

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
