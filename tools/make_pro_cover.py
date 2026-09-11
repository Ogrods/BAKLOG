#!/usr/bin/env python3
"""
Render BAKLOG Pro cover art for Polar listings and the in-app Pro hero strip.

Fully hardcoded composition (no AI): dark slate-navy background, the canonical
3-pill BAKLOG mark (favicon.svg geometry), a Space Grotesk wordmark + PRO badge,
and a short tagline.

Run from repo root:
  python tools/make_pro_cover.py                 # Polar monthly cover (1200x630)
  python tools/make_pro_cover.py --yearly        # Polar yearly cover
  python tools/make_pro_cover.py --strip         # In-app flat strip (1600x300)
  python tools/make_pro_cover.py --strip --yearly
Output:
  assets/baklog-pro-polar.png
  assets/baklog-pro-polar-yearly.png
  assets/baklog-pro-strip.png
  assets/baklog-pro-strip-yearly.png
"""

from __future__ import annotations

import argparse
import io
import math
from pathlib import Path

from fontTools.ttLib.woff2 import decompress as woff2_decompress
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT_GROTESK = ROOT / "web" / "assets" / "fonts" / "space-grotesk-latin.woff2"
FONT_DMSANS = ROOT / "web" / "assets" / "fonts" / "dm-sans-latin.woff2"
OUT_MONTHLY = ROOT / "assets" / "baklog-pro-polar.png"
OUT_YEARLY = ROOT / "assets" / "baklog-pro-polar-yearly.png"
OUT_STRIP_MONTHLY = ROOT / "assets" / "baklog-pro-strip.png"
OUT_STRIP_YEARLY = ROOT / "assets" / "baklog-pro-strip-yearly.png"

# Canonical BAKLOG mark geometry (favicon.svg / sponsored-deals.js baklogBannerMarkHtml).
PILLS = ((2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24))
KNOBS = ((14, 64), (64, 64), (39, 36))
PILL_RADIUS = 12
KNOB_R = 8
MARK_MINX, MARK_MINY = 2, 24
MARK_VW, MARK_VH = 96, 52

# Polar / OG canvas, supersampled then downscaled.
DISPLAY_W, DISPLAY_H = 1200, 630
# Flat in-app hero strip.
STRIP_W, STRIP_H = 1600, 300
SS = 2
W, H = DISPLAY_W * SS, DISPLAY_H * SS

# Brand palette (app.css :root / --accent / --brand-*).
BG = (15, 23, 42)            # #0f172a slate-navy
BG_DEEP = (8, 13, 26)        # deeper corner
WHITE = (240, 249, 255)
MUTED = (148, 163, 184)      # slate-400 tagline
PILL_BG = (30, 41, 59)       # #1e293b feature pill fill

# Accent palettes - sky-blue (monthly) vs violet (yearly).
ACCENT = (56, 189, 248)         # #38bdf8
ACCENT_BRIGHT = (14, 165, 233)  # #0ea5e9
ACCENT_HI = (125, 211, 252)     # #7dd3fc
GRID = (30, 44, 70)

PALETTE_BLUE = {
    "ACCENT": (56, 189, 248),
    "ACCENT_BRIGHT": (14, 165, 233),
    "ACCENT_HI": (125, 211, 252),
    "GRID": (30, 44, 70),
}
PALETTE_PURPLE = {
    "ACCENT": (168, 85, 247),
    "ACCENT_BRIGHT": (147, 51, 234),
    "ACCENT_HI": (216, 180, 254),
    "GRID": (49, 36, 73),
}


def apply_palette(purple: bool) -> None:
    """Swap the module-level accent globals used by the draw helpers."""
    global ACCENT, ACCENT_BRIGHT, ACCENT_HI, GRID
    p = PALETTE_PURPLE if purple else PALETTE_BLUE
    ACCENT = p["ACCENT"]
    ACCENT_BRIGHT = p["ACCENT_BRIGHT"]
    ACCENT_HI = p["ACCENT_HI"]
    GRID = p["GRID"]


WORDMARK = "BAKLOG"
TRACKING_EM = 0.04
TAGLINE = "One honest backlog across every store."
FEATURES = ("Bulk refresh", "Cloud sync", "No ads")
STRIP_TAGLINE = "Free and local-first. Pro funds the roadmap."


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    buf = io.BytesIO()
    woff2_decompress(str(path), buf)
    buf.seek(0)
    return ImageFont.truetype(buf, size=size)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_background(img: Image.Image) -> None:
    """Diagonal slate base + sky-blue radial glow in the upper-left + faint grid."""
    px = img.load()
    denom = max(W + H - 2, 1)
    glow_cx, glow_cy = W * 0.16, H * 0.18
    glow_r = H * 1.05
    for y in range(H):
        for x in range(W):
            t = (x + y) / denom
            base = lerp(BG, BG_DEEP, t)
            d = math.hypot(x - glow_cx, y - glow_cy)
            g = max(0.0, 1.0 - d / glow_r)
            g = g * g * 0.42
            px[x, y] = (
                min(255, round(base[0] + (ACCENT[0] - base[0]) * g)),
                min(255, round(base[1] + (ACCENT[1] - base[1]) * g)),
                min(255, round(base[2] + (ACCENT[2] - base[2]) * g)),
            )


def draw_flat_background(img: Image.Image) -> None:
    """Solid slate panel with a soft left-to-right accent wash (no grid, no glow)."""
    px = img.load()
    ww, hh = img.size
    for y in range(hh):
        for x in range(ww):
            t = x / max(ww - 1, 1)
            base = lerp(BG, BG_DEEP, t * 0.35)
            wash = 0.08 * (1.0 - t)
            px[x, y] = (
                min(255, round(base[0] + (ACCENT[0] - base[0]) * wash)),
                min(255, round(base[1] + (ACCENT[1] - base[1]) * wash)),
                min(255, round(base[2] + (ACCENT[2] - base[2]) * wash)),
            )


def draw_grid(img: Image.Image) -> None:
    d = ImageDraw.Draw(img, "RGBA")
    step = 64 * SS
    for gx in range(0, W, step):
        d.line((gx, 0, gx, H), fill=(*GRID, 70), width=1)
    for gy in range(0, H, step):
        d.line((0, gy, W, gy), fill=(*GRID, 70), width=1)


def mark_mask(scale: float, ox: float, oy: float) -> Image.Image:
    """Alpha mask of the 3-pill mark with circular knockouts (mask matches SVG)."""
    mw = int(MARK_VW * scale) + 4
    mh = int(MARK_VH * scale) + 4
    mask = Image.new("L", (mw, mh), 0)
    d = ImageDraw.Draw(mask)
    r = PILL_RADIUS * scale
    kr = KNOB_R * scale

    def mp(vx, vy):
        return (2 + (vx - MARK_MINX) * scale, 2 + (vy - MARK_MINY) * scale)

    for x, y, w, h in PILLS:
        x0, y0 = mp(x, y)
        x1, y1 = mp(x + w, y + h)
        d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)
    for cx, cy in KNOBS:
        kx, ky = mp(cx, cy)
        d.ellipse((kx - kr, ky - kr, kx + kr, ky + kr), fill=0)
    return mask


def draw_mark(
    img: Image.Image,
    scale: float,
    ox: float,
    oy: float,
    *,
    glow: bool = True,
) -> tuple[float, float]:
    """Paint the mark with a vertical sky-blue gradient. Returns (w, h)."""
    mask = mark_mask(scale, ox, oy)
    mw, mh = mask.size

    grad = Image.new("RGB", (mw, mh))
    gp = grad.load()
    for y in range(mh):
        t = y / max(mh - 1, 1)
        col = lerp(ACCENT_HI, ACCENT_BRIGHT, t)
        for x in range(mw):
            gp[x, y] = col
    tile = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
    tile.paste(grad, (0, 0))
    tile.putalpha(mask)

    if glow:
        from PIL import ImageFilter
        soft = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
        gd = ImageDraw.Draw(soft)
        gd.bitmap((0, 0), mask, fill=(*ACCENT, 130))
        soft = soft.filter(ImageFilter.GaussianBlur(10 * SS))
        img.alpha_composite(soft, (int(ox) - 2, int(oy) - 2))
    img.alpha_composite(tile, (int(ox), int(oy)))
    return MARK_VW * scale, MARK_VH * scale


def text_w(font, s, tracking=0.0):
    total = 0.0
    for i, ch in enumerate(s):
        total += font.getlength(ch)
        if i < len(s) - 1:
            total += tracking
    return total


def draw_tracked(d, xy, s, font, fill, tracking=0.0):
    x, y = xy
    for i, ch in enumerate(s):
        d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch)
        if i < len(s) - 1:
            x += tracking


def draw_pro_badge(img, d, *, badge_x, badge_y, grotesk_pro, corner_radius=None):
    pro_txt = "PRO"
    pro_track = grotesk_pro.size * 0.10
    pro_w = text_w(grotesk_pro, pro_txt, pro_track)
    pad_x = 30 * SS
    pad_y = 14 * SS
    pro_bb = d.textbbox((0, 0), "PRO", font=grotesk_pro)
    pro_h = pro_bb[3] - pro_bb[1]
    badge_w = pro_w + 2 * pad_x
    badge_h = pro_h + 2 * pad_y
    badge = Image.new("RGBA", (int(badge_w), int(badge_h)), (0, 0, 0, 0))
    bgrad = Image.new("RGB", (int(badge_w), int(badge_h)))
    bp = bgrad.load()
    for yy in range(int(badge_h)):
        t = yy / max(int(badge_h) - 1, 1)
        col = lerp(ACCENT, ACCENT_BRIGHT, t)
        for xx in range(int(badge_w)):
            bp[xx, yy] = col
    bmask = Image.new("L", (int(badge_w), int(badge_h)), 0)
    radius = badge_h / 2 if corner_radius is None else corner_radius
    ImageDraw.Draw(bmask).rounded_rectangle(
        (0, 0, badge_w - 1, badge_h - 1),
        radius=radius,
        fill=255,
    )
    badge.paste(bgrad, (0, 0))
    badge.putalpha(bmask)
    img.alpha_composite(badge, (int(badge_x), int(badge_y)))
    draw_tracked(
        d,
        (badge_x + pad_x, badge_y + pad_y - pro_bb[1]),
        pro_txt,
        grotesk_pro,
        (8, 17, 30),
        pro_track,
    )
    return badge_w, badge_h


def main_polar(yearly: bool = False):
    global W, H
    W, H = DISPLAY_W * SS, DISPLAY_H * SS
    apply_palette(purple=yearly)
    price_num = "$50" if yearly else "$5"
    price_unit = "/yr" if yearly else "/mo"
    out_path = OUT_YEARLY if yearly else OUT_MONTHLY

    img = Image.new("RGBA", (W, H), (*BG, 255))
    draw_background(img)
    draw_grid(img)
    d = ImageDraw.Draw(img)

    grotesk_big = load_font(FONT_GROTESK, 132 * SS)
    grotesk_pro = load_font(FONT_GROTESK, 52 * SS)
    dm_tag = load_font(FONT_DMSANS, 38 * SS)
    dm_feat = load_font(FONT_DMSANS, 30 * SS)
    dm_price = load_font(FONT_GROTESK, 60 * SS)
    dm_price_unit = load_font(FONT_DMSANS, 30 * SS)

    margin = 96 * SS

    mark_scale = (150 * SS) / MARK_VH
    wm_track = grotesk_big.size * TRACKING_EM
    wm_w = text_w(grotesk_big, WORDMARK, wm_track)
    wm_bb = d.textbbox((0, 0), "BAKLOG", font=grotesk_big)
    wm_h = wm_bb[3] - wm_bb[1]

    lockup_top = 150 * SS
    mark_ox = margin
    mark_oy = lockup_top
    mw, mh = draw_mark(img, mark_scale, mark_ox, mark_oy)

    gap = 44 * SS
    wm_x = mark_ox + mw + gap
    wm_y = mark_oy + (mh - wm_h) / 2 - wm_bb[1]
    draw_tracked(d, (wm_x, wm_y), WORDMARK, grotesk_big, WHITE, wm_track)

    badge_x = wm_x + wm_w + 28 * SS
    # Approximate vertical center; badge height derived inside draw_pro_badge.
    badge_y = mark_oy + (mh - (52 * SS + 28 * SS)) / 2
    draw_pro_badge(img, d, badge_x=badge_x, badge_y=badge_y, grotesk_pro=grotesk_pro)

    tag_y = mark_oy + mh + 46 * SS
    d.text((margin, tag_y), TAGLINE, font=dm_tag, fill=MUTED)

    feat_y = tag_y + 96 * SS
    fx = margin
    fpad_x = 32 * SS
    fpad_y = 18 * SS
    dot_r = 7 * SS
    f_ascent, f_descent = dm_feat.getmetrics()
    pill_h = f_ascent + f_descent + 2 * fpad_y
    for feat in FEATURES:
        fw = d.textlength(feat, font=dm_feat)
        pill_w = dot_r * 2 + 16 * SS + fw + 2 * fpad_x
        cy = feat_y + pill_h / 2
        d.rounded_rectangle(
            (fx, feat_y, fx + pill_w, feat_y + pill_h),
            radius=pill_h / 2, fill=PILL_BG, outline=ACCENT, width=2 * SS,
        )
        d.ellipse((fx + fpad_x, cy - dot_r, fx + fpad_x + 2 * dot_r, cy + dot_r),
                  fill=ACCENT)
        d.text((fx + fpad_x + 2 * dot_r + 16 * SS, cy), feat,
               font=dm_feat, fill=WHITE, anchor="lm")
        fx += pill_w + 28 * SS

    pn_bb = d.textbbox((0, 0), price_num, font=dm_price)
    pn_w = d.textlength(price_num, font=dm_price)
    pn_h = pn_bb[3] - pn_bb[1]
    pu_w = d.textlength(price_unit, font=dm_price_unit)
    tag_pad = 30 * SS
    box_w = pn_w + 10 * SS + pu_w + 2 * tag_pad
    box_h = pn_h + 2 * tag_pad
    box_x = W - margin - box_w
    box_y = H - margin - box_h + 20 * SS
    d.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=24 * SS, fill=(*PILL_BG, 255), outline=ACCENT, width=2 * SS,
    )
    d.text((box_x + tag_pad, box_y + tag_pad - pn_bb[1]), price_num,
           font=dm_price, fill=ACCENT_HI)
    pu_bb = d.textbbox((0, 0), price_unit, font=dm_price_unit)
    d.text((box_x + tag_pad + pn_w + 10 * SS,
            box_y + box_h - tag_pad - (pu_bb[3] - pu_bb[1]) - pu_bb[1] - 6 * SS),
           price_unit, font=dm_price_unit, fill=MUTED)

    out = img.convert("RGB").resize((DISPLAY_W, DISPLAY_H), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, "PNG")
    print(f"Wrote {out_path} ({DISPLAY_W}x{DISPLAY_H})")


def main_strip(yearly: bool = False):
    """Flat brand strip for the in-app Pro hero: no grid, no glow, 4px corners."""
    apply_palette(purple=yearly)
    out_path = OUT_STRIP_YEARLY if yearly else OUT_STRIP_MONTHLY
    ww, hh = STRIP_W * SS, STRIP_H * SS

    img = Image.new("RGBA", (ww, hh), (*BG, 255))
    draw_flat_background(img)
    d = ImageDraw.Draw(img)

    grotesk_big = load_font(FONT_GROTESK, 88 * SS)
    grotesk_pro = load_font(FONT_GROTESK, 36 * SS)
    dm_tag = load_font(FONT_DMSANS, 28 * SS)

    margin_x = 72 * SS
    mark_scale = (88 * SS) / MARK_VH
    wm_track = grotesk_big.size * TRACKING_EM
    wm_w = text_w(grotesk_big, WORDMARK, wm_track)
    wm_bb = d.textbbox((0, 0), "BAKLOG", font=grotesk_big)
    wm_h = wm_bb[3] - wm_bb[1]

    mark_ox = margin_x
    mark_h = MARK_VH * mark_scale
    row_h = max(mark_h, wm_h)
    mark_oy = (hh - row_h) / 2
    mw, mh = draw_mark(img, mark_scale, mark_ox, mark_oy, glow=False)

    gap = 28 * SS
    wm_x = mark_ox + mw + gap
    wm_y = mark_oy + (mh - wm_h) / 2 - wm_bb[1]
    draw_tracked(d, (wm_x, wm_y), WORDMARK, grotesk_big, WHITE, wm_track)

    pro_bb = d.textbbox((0, 0), "PRO", font=grotesk_pro)
    pad_y = 10 * SS
    badge_h = (pro_bb[3] - pro_bb[1]) + 2 * pad_y
    badge_x = wm_x + wm_w + 20 * SS
    badge_y = mark_oy + (mh - badge_h) / 2
    badge_w, _ = draw_pro_badge(
        img, d,
        badge_x=badge_x, badge_y=badge_y,
        grotesk_pro=grotesk_pro,
        corner_radius=4 * SS,
    )

    tag_x = badge_x + badge_w + 36 * SS
    tag_bb = d.textbbox((0, 0), STRIP_TAGLINE, font=dm_tag)
    tag_h = tag_bb[3] - tag_bb[1]
    tag_y = mark_oy + (mh - tag_h) / 2 - tag_bb[1]
    max_tag_w = ww - margin_x - tag_x
    if d.textlength(STRIP_TAGLINE, font=dm_tag) <= max_tag_w:
        d.text((tag_x, tag_y), STRIP_TAGLINE, font=dm_tag, fill=MUTED)
    else:
        under_y = mark_oy + mh + 18 * SS
        d.text((margin_x, under_y), STRIP_TAGLINE, font=dm_tag, fill=MUTED)

    out = img.convert("RGB").resize((STRIP_W, STRIP_H), Image.LANCZOS)
    mask = Image.new("L", (STRIP_W, STRIP_H), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, STRIP_W - 1, STRIP_H - 1), radius=4, fill=255
    )
    rgba = out.convert("RGBA")
    rgba.putalpha(mask)
    final = Image.new("RGB", (STRIP_W, STRIP_H), BG)
    final.paste(rgba, (0, 0), rgba)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path, "PNG")
    print(f"Wrote {out_path} ({STRIP_W}x{STRIP_H})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render BAKLOG Pro cover art.")
    parser.add_argument("--yearly", action="store_true",
                        help="Render the purple yearly variant.")
    parser.add_argument("--strip", action="store_true",
                        help="Render the flat in-app hero strip (1600x300).")
    args = parser.parse_args()
    if args.strip:
        main_strip(yearly=args.yearly)
    else:
        main_polar(yearly=args.yearly)
