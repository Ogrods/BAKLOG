#!/usr/bin/env python3
"""
Render a 180x180 apple-touch-icon from the canonical favicon.svg geometry.

Run from repo root:
  python tools/make_apple_touch_icon.py
Output:
  landing/apple-touch-icon.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "landing" / "apple-touch-icon.png"
SIZE = 180

PILLS = ((2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24))
KNOBS = ((14, 64), (64, 64), (39, 36))
PILL_RADIUS = 12
KNOB_R = 8
MARK_MINX, MARK_MINY = 2, 24
MARK_VW, MARK_VH = 96, 52
BG = (15, 23, 42)
WHITE = (255, 255, 255)


def map_pt(vx, vy, scale, ox, oy):
    return (ox + (vx - MARK_MINX) * scale, oy + (vy - MARK_MINY) * scale)


def main():
    img = Image.new("RGB", (SIZE, SIZE), BG)
    layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    mark_h = int(SIZE * 0.62)
    scale = mark_h / MARK_VH
    mark_w = MARK_VW * scale
    ox = (SIZE - mark_w) / 2
    oy = (SIZE - mark_h) / 2
    r = PILL_RADIUS * scale
    kr = KNOB_R * scale

    for x, y, w, h in PILLS:
        x0, y0 = map_pt(x, y, scale, ox, oy)
        x1, y1 = map_pt(x + w, y + h, scale, ox, oy)
        d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=WHITE + (255,))

    for cx, cy in KNOBS:
        px, py = map_pt(cx, cy, scale, ox, oy)
        d.ellipse((px - kr, py - kr, px + kr, py + kr), fill=(0, 0, 0, 0))

    img.paste(layer, mask=layer.split()[3])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"Wrote {OUT} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
