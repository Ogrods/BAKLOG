#!/usr/bin/env python3
"""Export Playwright capture PNGs to landing product WebPs.

Reads assets/screenshots/{name}.png and writes web/assets/product/{name}.webp
at max width 1600, WebP quality 85.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "screenshots"
DST = ROOT / "web" / "assets" / "product"

SHOTS = (
    "dashboard",
    "library",
    "wishlist",
    "connections",
    "fetchers",
)

MAX_WIDTH = 1600
WEBP_QUALITY = 85


def export_one(slug: str) -> Path:
    src = SRC / f"{slug}.png"
    if not src.is_file():
        raise FileNotFoundError(src)
    DST.mkdir(parents=True, exist_ok=True)
    dst = DST / f"{slug}.webp"
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w > MAX_WIDTH:
            nh = max(1, round(h * (MAX_WIDTH / w)))
            im = im.resize((MAX_WIDTH, nh), Image.Resampling.LANCZOS)
        im.save(dst, "WEBP", quality=WEBP_QUALITY, method=6)
        out_w, out_h = im.size
    src_kb = src.stat().st_size / 1024
    dst_kb = dst.stat().st_size / 1024
    print(f"{slug}: {src_kb:7.0f} KB png -> {dst_kb:6.0f} KB webp ({out_w}x{out_h})")
    return dst


def main() -> None:
    for slug in SHOTS:
        export_one(slug)


if __name__ == "__main__":
    main()
