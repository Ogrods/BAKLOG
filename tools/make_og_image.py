import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "landing" / "assets" / "og.png"
OUT_W, OUT_H = (1200, 630)
SS = 3
CW, CH = (OUT_W * SS, OUT_H * SS)
PILLS = ((2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24))
KNOBS = ((14, 64), (64, 64), (39, 36))
PILL_RADIUS = 12
KNOB_R = 8
MARK_MINX, MARK_MINY, MARK_MAXX, MARK_MAXY = (2, 24, 98, 76)
MARK_VW = MARK_MAXX - MARK_MINX
MARK_VH = MARK_MAXY - MARK_MINY
BG_TOP = (15, 23, 42)
BG_BOTTOM = (8, 14, 30)
SKY = (56, 189, 248)
VIOLET = (168, 85, 247)
WHITE = (255, 255, 255)
WORDMARK = "BAKLOG"
TAGLINE = "One honest backlog across every store."
WIN = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
BOLD_FONTS = (ROOT / "assets" / "fonts" / "SpaceGrotesk-Bold.ttf", WIN / "segoeuib.ttf", WIN / "arialbd.ttf")
REG_FONTS = (ROOT / "assets" / "fonts" / "SpaceGrotesk-Medium.ttf", WIN / "segoeui.ttf", WIN / "arial.ttf")


def load_font(candidates, size):
    for p in candidates:
        if Path(p).is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def vertical_gradient(w, h, top, bottom):
    base = Image.new("RGB", (w, h))
    px = base.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple((int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        for x in range(w):
            px[x, y] = c
    return base


def gradient_fast(w, h, top, bottom):
    col = Image.new("RGB", (1, h))
    d = col.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        d[0, y] = tuple((int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return col.resize((w, h))


def radial_glow(size, center, radius, color, max_alpha):
    layer = Image.new("L", size, 0)
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=max_alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(radius * 0.55))
    glow = Image.new("RGBA", size, color + (0,))
    glow.putalpha(layer)
    return glow


def map_pt(vx, vy, scale, ox, oy):
    return (ox + (vx - MARK_MINX) * scale, oy + (vy - MARK_MINY) * scale)


def draw_mark(scale, ox, oy):
    layer = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = PILL_RADIUS * scale
    for x, y, w, h in PILLS:
        x0, y0 = map_pt(x, y, scale, ox, oy)
        x1, y1 = map_pt(x + w, y + h, scale, ox, oy)
        d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=WHITE + (255,))
    kr = KNOB_R * scale
    for cx, cy in KNOBS:
        px, py = map_pt(cx, cy, scale, ox, oy)
        d.ellipse((px - kr, py - kr, px + kr, py + kr), fill=(0, 0, 0, 0))
    return layer


def draw_tracked_text(base, text, font, fill, center_x, top_y, tracking):
    d = ImageDraw.Draw(base)
    widths = [d.textbbox((0, 0), ch, font=font)[2] for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = center_x - total / 2
    for ch, w in zip(text, widths):
        d.text((x, top_y), ch, font=font, fill=fill)
        x += w + tracking
    return total


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img = gradient_fast(CW, CH, BG_TOP, BG_BOTTOM).convert("RGBA")
    img.alpha_composite(radial_glow((CW, CH), (CW // 2, int(CH * 0.3)), int(CW * 0.3), SKY, 70))
    img.alpha_composite(radial_glow((CW, CH), (int(CW * 0.74), int(CH * 0.12)), int(CW * 0.22), VIOLET, 48))
    mark_h = int(CH * 0.34)
    scale = mark_h / MARK_VH
    mark_w = MARK_VW * scale
    ox = (CW - mark_w) / 2
    oy = int(CH * 0.14)
    mark = draw_mark(scale, ox, oy)
    img.alpha_composite(mark)
    mark_bottom = oy + mark_h
    word_fs = int(CH * 0.135)
    word_font = load_font(BOLD_FONTS, word_fs)
    word_top = mark_bottom + int(CH * 0.06)
    draw_tracked_text(img, WORDMARK, word_font, WHITE + (255,), CW / 2, word_top, word_fs * 0.14)
    tag_fs = int(CH * 0.046)
    tag_font = load_font(REG_FONTS, tag_fs)
    d = ImageDraw.Draw(img)
    tb = d.textbbox((0, 0), TAGLINE, font=tag_font)
    tag_w = tb[2] - tb[0]
    tag_top = word_top + word_fs * 1.35
    d.text(((CW - tag_w) / 2, tag_top), TAGLINE, font=tag_font, fill=SKY + (255,))
    final = img.convert("RGB").resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
    final.save(OUT, "PNG")
    print(f"Wrote {OUT} ({OUT_W}x{OUT_H})")


if __name__ == "__main__":
    main()
