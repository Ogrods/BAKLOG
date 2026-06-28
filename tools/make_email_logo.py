from __future__ import annotations
import io
from pathlib import Path
from fontTools.ttLib.woff2 import decompress as woff2_decompress
from PIL import Image, ImageDraw, ImageFont
ROOT = Path(__file__).resolve().parents[1]
FONT_WOFF2 = ROOT / 'landing' / 'assets' / 'fonts' / 'space-grotesk-latin.woff2'
OUT = ROOT / 'landing' / 'assets' / 'email-logo.png'
DISPLAY_W = 640
DISPLAY_H = 180
SS = 3
W = DISPLAY_W * SS
H = DISPLAY_H * SS
PAD = 24 * SS
PILLS = ((2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24))
KNOBS = ((14, 64), (64, 64), (39, 36))
PILL_RADIUS = 12
KNOB_R = 8
MARK_MINX, MARK_MINY = (2, 24)
MARK_VW, MARK_VH = (96, 52)
GRAD_TL = (92, 198, 250)
GRAD_BR = (14, 165, 233)
WORDMARK = 'BAKLOG'
TRACKING_EM = 0.16
MARK_WORD_GAP = 20 * SS

def map_pt(vx, vy, scale, ox, oy):
    return (ox + (vx - MARK_MINX) * scale, oy + (vy - MARK_MINY) * scale)

def load_font(size: int) -> ImageFont.FreeTypeFont:
    buf = io.BytesIO()
    woff2_decompress(str(FONT_WOFF2), buf)
    buf.seek(0)
    return ImageFont.truetype(buf, size=size)

def diagonal_gradient(width: int, height: int, tl: tuple[int, int, int], br: tuple[int, int, int]) -> Image.Image:
    base = Image.new('RGB', (width, height))
    px = base.load()
    denom = max(width + height - 2, 1)
    for y in range(height):
        for x in range(width):
            t = (x + y) / denom
            px[x, y] = (round(tl[0] + (br[0] - tl[0]) * t), round(tl[1] + (br[1] - tl[1]) * t), round(tl[2] + (br[2] - tl[2]) * t))
    return base

def draw_mark(mask: Image.Image, scale: float, ox: float, oy: float) -> None:
    d = ImageDraw.Draw(mask)
    r = PILL_RADIUS * scale
    kr = KNOB_R * scale
    for x, y, w, h in PILLS:
        x0, y0 = map_pt(x, y, scale, ox, oy)
        x1, y1 = map_pt(x + w, y + h, scale, ox, oy)
        d.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)
    for cx, cy in KNOBS:
        px, cy2 = map_pt(cx, cy, scale, ox, oy)
        d.ellipse((px - kr, cy2 - kr, px + kr, cy2 + kr), fill=0)

def wordmark_width(font: ImageFont.FreeTypeFont, size: int) -> float:
    tracking = size * TRACKING_EM
    total = 0.0
    for i, ch in enumerate(WORDMARK):
        total += font.getlength(ch)
        if i < len(WORDMARK) - 1:
            total += tracking
    return total

def draw_wordmark(mask: Image.Image, font: ImageFont.FreeTypeFont, x: float, y: float) -> None:
    d = ImageDraw.Draw(mask)
    tracking = font.size * TRACKING_EM
    cursor = x
    for i, ch in enumerate(WORDMARK):
        d.text((cursor, y), ch, font=font, fill=255)
        cursor += font.getlength(ch)
        if i < len(WORDMARK) - 1:
            cursor += tracking

def main():
    inner_h = H - 2 * PAD
    font_size = int(inner_h * 0.62)
    font = load_font(font_size)
    tracking = font_size * TRACKING_EM
    probe = Image.new('L', (1, 1))
    pd = ImageDraw.Draw(probe)
    text_y = 0
    boxes = []
    cursor = 0.0
    for i, ch in enumerate(WORDMARK):
        bb = pd.textbbox((cursor, text_y), ch, font=font)
        boxes.append(bb)
        cursor += font.getlength(ch)
        if i < len(WORDMARK) - 1:
            cursor += tracking
    text_w = wordmark_width(font, font_size)
    text_h = max((bb[3] for bb in boxes)) - min((bb[1] for bb in boxes))
    mark_scale = inner_h * 0.88 / MARK_VH
    mark_w = MARK_VW * mark_scale
    mark_h = MARK_VH * mark_scale
    content_w = mark_w + MARK_WORD_GAP + text_w
    ox = PAD + (W - 2 * PAD - content_w) / 2
    mark_ox = ox
    mark_oy = PAD + (inner_h - mark_h) / 2
    text_x = mark_ox + mark_w + MARK_WORD_GAP
    text_y = PAD + (inner_h - text_h) / 2 - min((bb[1] for bb in boxes))
    mask = Image.new('L', (W, H), 0)
    draw_mark(mask, mark_scale, mark_ox, mark_oy)
    draw_wordmark(mask, font, text_x, text_y)
    grad = diagonal_gradient(W, H, GRAD_TL, GRAD_BR)
    out = Image.new('RGBA', (W, H))
    out.paste(grad, (0, 0))
    out.putalpha(mask)
    out = out.resize((DISPLAY_W, DISPLAY_H), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.save(OUT, 'PNG')
    print(f'Wrote {OUT} ({DISPLAY_W}x{DISPLAY_H})')
if __name__ == '__main__':
    main()