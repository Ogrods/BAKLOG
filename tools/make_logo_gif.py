#!/usr/bin/env python3
"""
Generate BAKLOG logo intro GIFs: three logs fly/bounce into place, then BAKLOG wordmark drops in.

Outputs to marketing/assets/logo/:
  logo-toss-a.gif / logo-drop-b.gif / logo-scatter-c.gif  — Log Jammin' theme
  logo-drop-midnight*.gif                               — white-on-black drop variants

Requires: Pillow (pip install pillow)
Run:
  python tools/make_logo_gif.py              # Log Jammin' toss/drop/scatter (both motto + plain)
  python tools/make_logo_gif.py midnight     # six white-on-black drop GIFs
  python tools/make_logo_gif.py blue         # deck-navy orbit GIF(s)
"""

from __future__ import annotations

import math
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageFont

# SVG viewBox "2 24 96 52" — pill rects + knob centers (global SVG coords)
PILLS = (
    {"name": "bl", "rect": (2, 52, 46, 24), "knob": (14, 64), "radius": 12},
    {"name": "br", "rect": (52, 52, 46, 24), "knob": (64, 64), "radius": 12},
    {"name": "top", "rect": (27, 24, 46, 24), "knob": (39, 36), "radius": 12},
)
VIEWBOX = (2, 24, 96, 52)  # min_x, min_y, width, height
KNOB_R = 8

WORDMARK = "BAKLOG"
LETTER_SPACING = 0.18  # fraction of font size between letters

MOTTO = "Bak it up with BAKLOG"
MOTTO_COLOR = "#bfe3c4"

FPS = 30
FRAME_MS = 33
DROP_START_ABOVE = 0.65  # fraction of canvas height above final Y

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "marketing" / "assets" / "logo"

FONT_CANDIDATES = (
    ROOT / "assets" / "fonts" / "SpaceGrotesk-Bold.ttf",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
)

LayoutMode = Literal["wordmark", "mark_center", "mark_wide"]


@dataclass
class GifPreset:
    out_w: int
    out_h: int
    supersample: int = 4
    log_fill: str = "#a9742f"
    log_edge: str = "#7a5520"
    knob_edge: str = "#5c3d1e"
    bg_top: str = "#2c6e49"
    bg_bottom: str = "#1c4a30"
    wordmark_color: str = "#c9a06a"
    wordmark_shadow: str = "#5c3d1e"
    wordmark_size: float = 0.108
    wordmark_gap: float = 0.028
    layout_mode: LayoutMode = "wordmark"
    shadow_rgba: tuple[int, int, int, int] = (0, 0, 0, 48)
    word_shadow: bool = True
    drop_start_above: float = DROP_START_ABOVE

    @property
    def canvas_w(self) -> int:
        return self.out_w * self.supersample

    @property
    def canvas_h(self) -> int:
        return self.out_h * self.supersample


def log_jammin_preset(out_w: int = 400, out_h: int = 400, supersample: int = 4) -> GifPreset:
    return GifPreset(out_w=out_w, out_h=out_h, supersample=supersample)


def blue_preset(out_w: int = 400, out_h: int = 400, supersample: int = 4) -> GifPreset:
    """Deck hero: navy gradient + sky-blue pills + still wordmark."""
    return GifPreset(
        out_w=out_w,
        out_h=out_h,
        supersample=supersample,
        log_fill="#38bdf8",
        log_edge="#22d3ee",
        knob_edge="#0c4a6e",
        bg_top="#0f172a",
        bg_bottom="#0b1220",
        wordmark_color="#7dd3fc",
        wordmark_shadow="#0b1220",
        wordmark_size=0.108,
        wordmark_gap=0.028,
        layout_mode="wordmark",
        shadow_rgba=(0, 0, 0, 48),
        word_shadow=True,
    )


def midnight_preset(
    out_w: int,
    out_h: int,
    supersample: int,
    layout_mode: LayoutMode,
) -> GifPreset:
    return GifPreset(
        out_w=out_w,
        out_h=out_h,
        supersample=supersample,
        log_fill="#ffffff",
        log_edge="#e5e7eb",
        knob_edge="#52525b",
        bg_top="#000000",
        bg_bottom="#000000",
        wordmark_color="#ffffff",
        wordmark_shadow="#000000",
        wordmark_size=0.108 if out_h >= 200 else 0.095,
        wordmark_gap=0.028,
        layout_mode=layout_mode,
        shadow_rgba=(0, 0, 0, 32),
        word_shadow=False,
        drop_start_above=DROP_START_ABOVE,
    )


# ── Easing ───────────────────────────────────────────────────────────────────
def clamp01(t: float) -> float:
    return max(0.0, min(1.0, t))


def ease_out_cubic(t: float) -> float:
    t = clamp01(t)
    return 1.0 - (1.0 - t) ** 3


def ease_out_back(t: float, s: float = 1.70158) -> float:
    t = clamp01(t)
    return 1.0 + (s + 1.0) * (t - 1.0) ** 3 + s * (t - 1.0) ** 2


def decay_bounce(t: float, amp: float = 1.0, freq: float = 3.5, decay: float = 6.0) -> float:
    t = clamp01(t)
    if t >= 1.0:
        return 0.0
    return amp * math.exp(-decay * t) * math.sin(freq * math.pi * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_angle(a: float, b: float, t: float) -> float:
    diff = ((b - a + 180) % 360) - 180
    return a + diff * t


# ── Layout ───────────────────────────────────────────────────────────────────
@dataclass
class MarkLayout:
    scale: float
    origin_x: float
    origin_y: float
    canvas_w: int
    canvas_h: int

    def to_canvas(self, sx: float, sy: float) -> tuple[float, float]:
        vx, vy, _, _ = VIEWBOX
        return (
            self.origin_x + (sx - vx) * self.scale,
            self.origin_y + (sy - vy) * self.scale,
        )

    def pill_center(self, pill: dict) -> tuple[float, float]:
        rx, ry, rw, rh = pill["rect"]
        return self.to_canvas(rx + rw / 2, ry + rh / 2)


def compute_layout(preset: GifPreset) -> MarkLayout:
    vx, vy, vw, vh = VIEWBOX
    cw, ch = preset.canvas_w, preset.canvas_h
    mode = preset.layout_mode

    if mode == "mark_wide":
        target_w = cw * 0.70
        target_h = ch * 0.55
        scale = min(target_w / vw, target_h / vh)
        mark_h = vh * scale
        origin_x = (cw - vw * scale) / 2 + vx * scale
        origin_y = (ch - mark_h) / 2 + vy * scale
    elif mode == "mark_center":
        target_w = cw * 0.72
        target_h = ch * 0.52
        scale = min(target_w / vw, target_h / vh)
        mark_h = vh * scale
        origin_x = (cw - vw * scale) / 2 + vx * scale
        origin_y = (ch - mark_h) / 2 + vy * scale
    else:  # wordmark — mark in upper portion, room below for BAKLOG
        target_w = cw * 0.72
        target_h = ch * 0.38
        scale = min(target_w / vw, target_h / vh)
        origin_x = (cw - vw * scale) / 2 + vx * scale
        origin_y = ch * 0.10 + vy * scale

    return MarkLayout(scale=scale, origin_x=origin_x, origin_y=origin_y, canvas_w=cw, canvas_h=ch)


# ── Drawing ──────────────────────────────────────────────────────────────────
def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def resolve_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size)
            except OSError:
                continue
    return ImageFont.load_default()


def rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: float, fill) -> None:
    x0, y0, x1, y1 = xy
    r = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
    draw.rounded_rectangle(xy, radius=r, fill=fill)


def make_pill_sprite(pill: dict, layout: MarkLayout, preset: GifPreset) -> Image.Image:
    rx, ry, rw, rh = pill["rect"]
    kx, ky = pill["knob"]
    r = pill["radius"]
    pad = int(KNOB_R * layout.scale * 2 + 20)
    cw = int(rw * layout.scale + pad * 2)
    ch = int(rh * layout.scale + pad * 2)
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    cx = cw / 2
    cy = ch / 2
    px0 = cx - (rw * layout.scale) / 2
    py0 = cy - (rh * layout.scale) / 2
    px1 = px0 + rw * layout.scale
    py1 = py0 + rh * layout.scale
    fill = _hex_rgb(preset.log_fill) + (255,)
    edge = _hex_rgb(preset.log_edge) + (255,)

    rounded_rect(draw, (px0, py0, px1, py1), r * layout.scale, fill)
    draw.rounded_rectangle(
        (px0, py0, px1, py1),
        radius=r * layout.scale,
        outline=edge,
        width=max(1, int(layout.scale * 0.8)),
    )

    klx = cx + (kx - (rx + rw / 2)) * layout.scale
    kly = cy + (ky - (ry + rh / 2)) * layout.scale
    kr = KNOB_R * layout.scale
    knob_draw = ImageDraw.Draw(layer)
    knob_draw.ellipse((klx - kr, kly - kr, klx + kr, kly + kr), fill=(0, 0, 0, 0))
    knob_draw.ellipse(
        (klx - kr, kly - kr, klx + kr, kly + kr),
        outline=_hex_rgb(preset.knob_edge) + (90,),
        width=max(1, int(layout.scale * 0.5)),
    )
    return layer


def _gradient_axis(layout: MarkLayout) -> tuple[tuple[float, float], tuple[float, float]]:
    """Mark bbox top-left and bottom-right corners in canvas coords (gradient axis)."""
    tl = layout.to_canvas(VIEWBOX[0], VIEWBOX[1])
    br = layout.to_canvas(VIEWBOX[0] + VIEWBOX[2], VIEWBOX[1] + VIEWBOX[3])
    return tl, br


def make_gradient_pill_sprite(
    slot_center: tuple[float, float],
    layout: MarkLayout,
    preset: GifPreset,
    stops: tuple[tuple[float, str], ...],
) -> Image.Image:
    """A pill sprite filled with a diagonal gradient sampled in global mark space.

    Colors are sampled at the pill's resting slot position so the assembled mark
    reproduces the continuous top-left -> bottom-right gradient of the SVG logo.
    No edge stroke (matches the flat-filled SVG); knob is punched transparent.
    """
    import numpy as np

    rw, rh = 46, 24  # all pills share rect dims
    knob_off_x = -11.0  # knob sits 11 units left of pill center (identical for all)
    r = 12
    pad = int(KNOB_R * layout.scale * 2 + 20)
    cw = int(rw * layout.scale + pad * 2)
    ch = int(rh * layout.scale + pad * 2)
    cx, cy = cw / 2, ch / 2

    # Shape alpha (rounded rect minus knob hole), no edge.
    shape = Image.new("L", (cw, ch), 0)
    sdraw = ImageDraw.Draw(shape)
    px0 = cx - (rw * layout.scale) / 2
    py0 = cy - (rh * layout.scale) / 2
    px1 = px0 + rw * layout.scale
    py1 = py0 + rh * layout.scale
    sdraw.rounded_rectangle((px0, py0, px1, py1), radius=r * layout.scale, fill=255)
    klx = cx + knob_off_x * layout.scale
    kly = cy
    kr = KNOB_R * layout.scale
    sdraw.ellipse((klx - kr, kly - kr, klx + kr, kly + kr), fill=0)

    # Gradient sampled at canvas position of each sprite pixel (slot-anchored).
    (tlx, tly), (brx, bry) = _gradient_axis(layout)
    ax, ay = brx - tlx, bry - tly
    denom = ax * ax + ay * ay or 1.0

    lx = np.arange(cw, dtype=np.float64) - cx + slot_center[0]
    ly = np.arange(ch, dtype=np.float64) - cy + slot_center[1]
    gx, gy = np.meshgrid(lx, ly)
    t = ((gx - tlx) * ax + (gy - tly) * ay) / denom
    t = np.clip(t, 0.0, 1.0)

    offs = [s[0] for s in stops]
    cols = [np.array(_hex_rgb(s[1]), dtype=np.float64) for s in stops]
    rgb = np.empty((ch, cw, 3), dtype=np.float64)
    for k in range(3):
        rgb[..., k] = cols[0][k]
    for j in range(len(stops) - 1):
        lo, hi = offs[j], offs[j + 1]
        span = (hi - lo) or 1.0
        local = np.clip((t - lo) / span, 0.0, 1.0)
        seg = (t >= lo) if j == 0 else (t > lo)
        for k in range(3):
            rgb[..., k] = np.where(seg, cols[j][k] + (cols[j + 1][k] - cols[j][k]) * local, rgb[..., k])

    arr = np.empty((ch, cw, 4), dtype=np.uint8)
    arr[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    arr[..., 3] = np.asarray(shape, dtype=np.uint8)
    return Image.fromarray(arr, mode="RGBA")


def _draw_static_wordmark(
    bg: Image.Image,
    layout: MarkLayout,
    preset: GifPreset,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Draw a fully-opaque, non-animated BAKLOG wordmark (orbit use)."""
    ch = preset.canvas_h
    word_fs = int(ch * preset.wordmark_size)
    draw = ImageDraw.Draw(bg)
    fnt = font if getattr(font, "size", None) == word_fs else resolve_font(word_fs)
    chars = list(WORDMARK)
    char_widths = [draw.textbbox((0, 0), c, font=fnt)[2] for c in chars]
    gap = word_fs * LETTER_SPACING
    total_w = sum(char_widths) + gap * (len(chars) - 1)
    _, mark_bottom = layout.to_canvas(VIEWBOX[0] + VIEWBOX[2], VIEWBOX[1] + VIEWBOX[3])
    base_y = mark_bottom + ch * preset.wordmark_gap
    fill_rgb = _hex_rgb(preset.wordmark_color)
    cx = (preset.canvas_w - total_w) / 2
    for i, ch_char in enumerate(chars):
        if preset.word_shadow:
            shadow_rgb = _hex_rgb(preset.wordmark_shadow)
            ox = max(2, int(preset.supersample * 0.6))
            oy = max(3, int(preset.supersample * 0.9))
            draw.text((cx + ox, base_y + oy), ch_char, font=fnt, fill=shadow_rgb + (140,))
        draw.text((cx, base_y), ch_char, font=fnt, fill=fill_rgb + (255,))
        cx += char_widths[i] + gap


def draw_background(preset: GifPreset) -> Image.Image:
    cw, ch = preset.canvas_w, preset.canvas_h
    img = Image.new("RGB", (cw, ch))
    draw = ImageDraw.Draw(img)
    top = _hex_rgb(preset.bg_top)
    bot = _hex_rgb(preset.bg_bottom)
    for y in range(ch):
        t = y / max(ch - 1, 1)
        c = tuple(int(lerp(a, b, t)) for a, b in zip(top, bot))
        draw.line([(0, y), (cw, y)], fill=c)
    return img


def composite_pill(
    base: Image.Image,
    sprite: Image.Image,
    cx: float,
    cy: float,
    angle_deg: float,
    preset: GifPreset,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    shadow: bool = True,
) -> None:
    w, h = sprite.size
    sw = max(1, int(w * scale_x))
    sh = max(1, int(h * scale_y))
    piece = sprite.resize((sw, sh), Image.Resampling.LANCZOS)
    piece = piece.rotate(angle_deg, resample=Image.Resampling.BICUBIC, expand=True)
    pw, ph = piece.size
    px = int(cx - pw / 2)
    py = int(cy - ph / 2)
    ss = preset.supersample

    if shadow and abs(angle_deg) < 8 and abs(scale_x - 1) < 0.15 and abs(scale_y - 1) < 0.15:
        shadow_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sh_img = Image.new("RGBA", (pw, ph), preset.shadow_rgba)
        sh_img.putalpha(piece.split()[3])
        shadow_layer.paste(sh_img, (px + int(4 * ss), py + int(6 * ss)), sh_img)
        base.alpha_composite(shadow_layer)

    temp = Image.new("RGBA", base.size, (0, 0, 0, 0))
    temp.paste(piece, (px, py), piece)
    base.alpha_composite(temp)


@dataclass
class PillState:
    x: float
    y: float
    angle: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0


def render_frame(
    layout: MarkLayout,
    preset: GifPreset,
    sprites: list[Image.Image],
    states: list[PillState],
    word_alpha: float = 0.0,
    word_drop: float = 0.0,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
    motto_alpha: float = 0.0,
    motto_font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None,
) -> Image.Image:
    ch = preset.canvas_h
    bg = draw_background(preset).convert("RGBA")
    for sprite, state in zip(sprites, states):
        composite_pill(
            bg, sprite, state.x, state.y, state.angle, preset,
            state.scale_x, state.scale_y,
        )

    wordmark_baseline = None
    word_fs = int(ch * preset.wordmark_size)
    if word_alpha > 0.01 and font is not None and preset.layout_mode == "wordmark":
        draw = ImageDraw.Draw(bg)
        fnt = font if getattr(font, "size", None) == word_fs else resolve_font(word_fs)
        chars = list(WORDMARK)
        char_widths = [draw.textbbox((0, 0), c, font=fnt)[2] for c in chars]
        gap = word_fs * LETTER_SPACING
        total_w = sum(char_widths) + gap * (len(chars) - 1)
        _, mark_bottom = layout.to_canvas(VIEWBOX[0] + VIEWBOX[2], VIEWBOX[1] + VIEWBOX[3])
        base_y = mark_bottom + ch * preset.wordmark_gap + word_drop * ch * 0.03
        x = (preset.canvas_w - total_w) / 2
        fill_rgb = _hex_rgb(preset.wordmark_color)
        alpha = int(255 * clamp01(word_alpha))
        color = fill_rgb + (alpha,)
        cx = x
        for i, ch_char in enumerate(chars):
            if preset.word_shadow:
                shadow_rgb = _hex_rgb(preset.wordmark_shadow)
                ox = max(2, int(preset.supersample * 0.6))
                oy = max(3, int(preset.supersample * 0.9))
                draw.text((cx + ox, base_y + oy), ch_char, font=fnt, fill=shadow_rgb + (int(alpha * 0.55),))
            draw.text((cx, base_y), ch_char, font=fnt, fill=color)
            cx += char_widths[i] + gap
        wordmark_baseline = base_y

    if motto_alpha > 0.01 and motto_font is not None:
        draw = ImageDraw.Draw(bg)
        if wordmark_baseline is None:
            _, mark_bottom = layout.to_canvas(VIEWBOX[0] + VIEWBOX[2], VIEWBOX[1] + VIEWBOX[3])
            wordmark_baseline = mark_bottom + ch * preset.wordmark_gap
        bbox = draw.textbbox((0, 0), MOTTO, font=motto_font)
        motto_w = bbox[2] - bbox[0]
        mx = (preset.canvas_w - motto_w) / 2
        my = wordmark_baseline + word_fs * 1.5
        mint = _hex_rgb(MOTTO_COLOR)
        color = mint + (int(255 * clamp01(motto_alpha)),)
        draw.text((mx, my), MOTTO, font=motto_font, fill=color)

    return bg


# ── Motion A: Tumble toss ────────────────────────────────────────────────────
def motion_toss(layout: MarkLayout, preset: GifPreset, n_frames: int) -> list[list[PillState]]:
    cw, ch = layout.canvas_w, layout.canvas_h
    finals = [layout.pill_center(p) for p in PILLS]
    starts = [
        (finals[0][0] - cw * 0.55, finals[0][1] + ch * 0.35),
        (finals[1][0] + cw * 0.55, finals[1][1] + ch * 0.35),
        (finals[2][0], finals[2][1] - ch * 0.45),
    ]
    start_angles = [-140.0, 120.0, 95.0]
    delays = [0, 4, 8]
    throw_dur = 22
    bounce_dur = 18

    frames: list[list[PillState]] = []
    for fi in range(n_frames):
        states = []
        for i, _pill in enumerate(PILLS):
            t_frame = fi - delays[i]
            fx, fy = finals[i]
            sx, sy = starts[i]
            if t_frame < 0:
                states.append(PillState(sx, sy, start_angles[i], 1.0, 1.0))
                continue
            if t_frame < throw_dur:
                p = ease_out_back(t_frame / throw_dur, s=2.2)
                x = lerp(sx, fx, p)
                y = lerp(sy, fy, p)
                ang = lerp_angle(start_angles[i], 0, ease_out_cubic(t_frame / throw_dur))
            else:
                bt = (t_frame - throw_dur) / bounce_dur
                x = fx + decay_bounce(bt, amp=layout.scale * 5, freq=2.8, decay=5.5) * (1 if i % 2 else -1)
                y = fy + decay_bounce(bt, amp=layout.scale * 3, freq=3.2, decay=5.0)
                ang = decay_bounce(bt, amp=4.0, freq=2.5, decay=6.0) * (1 if i == 1 else -1)
            sq = 1.0 + decay_bounce(max(0, (t_frame - throw_dur) / bounce_dur), amp=0.06, freq=4, decay=8)
            states.append(PillState(x, y, ang, 1.0 / sq, sq))
        frames.append(states)
    return frames


# ── Motion B: Drop & stack ───────────────────────────────────────────────────
def motion_drop(layout: MarkLayout, preset: GifPreset, n_frames: int) -> list[list[PillState]]:
    ch = layout.canvas_h
    above = preset.drop_start_above
    finals = [layout.pill_center(p) for p in PILLS]
    delays = [0, 3, 14]
    fall_dur = 16
    settle_dur = 20
    start_y_off = ch * above

    frames: list[list[PillState]] = []
    for fi in range(n_frames):
        states = []
        for i, _pill in enumerate(PILLS):
            fx, fy = finals[i]
            delay = delays[i]
            t_frame = fi - delay
            if t_frame < 0:
                states.append(PillState(fx, fy - start_y_off, 0, 1.0, 1.0))
                continue
            if t_frame < fall_dur:
                p = (t_frame / fall_dur) ** 2
                y = lerp(fy - start_y_off, fy, ease_out_cubic(p))
                x = fx
                ang = 0
                sy = 1.0 + (1 - p) * 0.08
                sx = 1.0 - (1 - p) * 0.04
            else:
                bt = (t_frame - fall_dur) / settle_dur
                x = fx
                y = fy + decay_bounce(bt, amp=layout.scale * 4, freq=3.0, decay=5.0)
                ang = decay_bounce(bt, amp=2.5, freq=2.0, decay=7.0) * (1 if i == 0 else -1)
                impact = decay_bounce(min(bt * 2, 1), amp=0.12, freq=5, decay=10)
                sx = 1.0 + impact
                sy = 1.0 - impact * 0.8
            states.append(PillState(x, y, ang, sx, sy))
        if fi > max(delays) + fall_dur + 4:
            wob_t = (fi - (max(delays) + fall_dur + 4)) / 14
            wob = decay_bounce(wob_t, amp=layout.scale * 1.5, freq=1.8, decay=4.0)
            for j in range(3):
                states[j] = PillState(
                    states[j].x + wob * 0.3,
                    states[j].y + wob * 0.15,
                    states[j].angle + wob * 0.02,
                    states[j].scale_x,
                    states[j].scale_y,
                )
        frames.append(states)
    return frames


# ── Motion C: Scatter-in ─────────────────────────────────────────────────────
def motion_scatter(layout: MarkLayout, preset: GifPreset, n_frames: int) -> list[list[PillState]]:
    cw, ch = layout.canvas_w, layout.canvas_h
    finals = [layout.pill_center(p) for p in PILLS]
    starts = [
        (finals[0][0] - cw * 0.42, finals[0][1] + ch * 0.08),
        (finals[1][0] + cw * 0.42, finals[1][1] + ch * 0.08),
        (finals[2][0] + cw * 0.12, finals[2][1] - ch * 0.38),
    ]
    start_angles = [-18.0, 22.0, -30.0]
    delays = [0, 2, 5]
    skid_dur = 20
    jiggle_dur = 16

    frames: list[list[PillState]] = []
    for fi in range(n_frames):
        states = []
        for i, _pill in enumerate(PILLS):
            t_frame = fi - delays[i]
            fx, fy = finals[i]
            sx, sy = starts[i]
            if t_frame < 0:
                states.append(PillState(sx, sy, start_angles[i], 1.0, 1.0))
                continue
            if t_frame < skid_dur:
                p = ease_out_back(t_frame / skid_dur, s=2.8)
                x = lerp(sx, fx, p)
                y = lerp(sy, fy, p)
                ang = lerp_angle(start_angles[i], 0, ease_out_cubic(t_frame / skid_dur))
            else:
                jt = (t_frame - skid_dur) / jiggle_dur
                x = fx + decay_bounce(jt, amp=layout.scale * 3.5, freq=3.5, decay=6.5) * (1 if i != 1 else -1)
                y = fy + decay_bounce(jt, amp=layout.scale * 2, freq=4.0, decay=7.0)
                ang = decay_bounce(jt, amp=5.0, freq=2.8, decay=6.0) * (1 if i == 2 else -1)
            states.append(PillState(x, y, ang, 1.0, 1.0))
        frames.append(states)
    return frames


# ── Motion D: Orbit (clockwise slot-swap) ────────────────────────────────────
# Per-hop frame budget (at FPS). Raise these to slow the orbit down; the
# seamless loop length is derived from them (see ORBIT_LOOP_FRAMES).
ORBIT_HOP_MOVE = 28
ORBIT_HOP_HOLD = 48
ORBIT_HOPS = 3
ORBIT_STAGGER = 4  # frames between each pill's departure
# slot departure order (top leads, then bottom-left, then bottom-right)
ORBIT_STAGGER_RANK = {2: 0, 0: 1, 1: 2}
ORBIT_LOOP_FRAMES = ORBIT_HOPS * (ORBIT_HOP_MOVE + ORBIT_HOP_HOLD)
# Diagonal gradient matching the top-left deck mark (mark-gradient.svg):
# blue -> cyan -> purple along the mark's top-left -> bottom-right bbox axis.
ORBIT_GRADIENT_STOPS = (
    (0.0, "#38bdf8"),
    (0.5, "#22d3ee"),
    (1.0, "#a855f7"),
)


def _slot_at_hop(pill_idx: int, hop: int) -> int:
    """Slot index for pill i after hop complete swaps (hop=0 → home slot).

    Counter-clockwise cycle (top -> bl -> br -> top in screen terms)."""
    return (pill_idx + hop) % 3


def _orbit_progress(hop_t: float, start_slot: int) -> float:
    """Per-pill move progress within a hop (0 at departure, 1 at arrival)."""
    delay = ORBIT_STAGGER_RANK[start_slot] * ORBIT_STAGGER
    span = ORBIT_HOP_MOVE - ORBIT_STAGGER * 2  # 3 pills -> 2 gaps
    return clamp01((hop_t - delay) / max(span, 1))


def _polar_from_centroid(
    cx: float, cy: float, px: float, py: float,
) -> tuple[float, float]:
    return math.atan2(py - cy, px - cx), math.hypot(px - cx, py - cy)


def _cw_arc_theta(theta_start: float, theta_end: float, t: float) -> float:
    """Interpolate angle clockwise (screen coords, y-down)."""
    diff = (theta_end - theta_start) % (2 * math.pi)
    if diff <= 1e-6:
        diff = 2 * math.pi
    if diff > math.pi:
        diff -= 2 * math.pi
    return theta_start + diff * t


def motion_orbit(
    layout: MarkLayout,
    preset: GifPreset,
    n_frames: int,
    straight: bool = True,
) -> list[list[PillState]]:
    """Three pills swap slots; identical mark after every hop.

    ``straight=True`` moves each pill in a straight line to its next slot with a
    slight per-pill stagger; ``straight=False`` is the legacy circular-arc swap
    (all pills depart together, travelling on an arc around the centroid).
    """
    finals = [layout.pill_center(p) for p in PILLS]

    hop_move = ORBIT_HOP_MOVE
    hop_hold = ORBIT_HOP_HOLD
    hop_total = hop_move + hop_hold
    loop_frames = ORBIT_LOOP_FRAMES

    cx = cy = 0.0
    slot_polar: list[tuple[float, float]] = []
    if not straight:
        cx = sum(f[0] for f in finals) / 3
        cy = sum(f[1] for f in finals) / 3
        slot_polar = [
            _polar_from_centroid(cx, cy, finals[s][0], finals[s][1]) for s in range(3)
        ]

    frames: list[list[PillState]] = []
    for fi in range(n_frames):
        hop_idx = (fi % loop_frames) // hop_total
        hop_t = (fi % loop_frames) % hop_total
        in_hold = hop_t >= hop_move

        states: list[PillState] = []
        for i, _pill in enumerate(PILLS):
            start_slot = _slot_at_hop(i, hop_idx)
            end_slot = _slot_at_hop(i, hop_idx + 1)
            sx, sy = finals[start_slot]
            ex, ey = finals[end_slot]

            if in_hold:
                x, y = ex, ey
                sx_scale, sy_scale = 1.0, 1.0
            elif straight:
                raw_p = _orbit_progress(hop_t, start_slot)
                p = ease_out_cubic(raw_p)
                x = lerp(sx, ex, p)
                y = lerp(sy, ey, p)
                snap_t = max(0.0, (raw_p - 0.82) / 0.18)
                squash = decay_bounce(snap_t, amp=0.05, freq=4.5, decay=9.0)
                sx_scale = 1.0 + squash
                sy_scale = 1.0 - squash * 0.75
            else:
                p = ease_out_cubic(hop_t / hop_move)
                ts, rs = slot_polar[start_slot]
                te, re = slot_polar[end_slot]
                theta = _cw_arc_theta(ts, te, p)
                r = lerp(rs, re, p)
                x = cx + r * math.cos(theta)
                y = cy + r * math.sin(theta)
                snap_t = max(0.0, (hop_t - hop_move * 0.82) / (hop_move * 0.18))
                squash = decay_bounce(snap_t, amp=0.05, freq=4.5, decay=9.0)
                sx_scale = 1.0 + squash
                sy_scale = 1.0 - squash * 0.75

            states.append(PillState(x, y, 0.0, sx_scale, sy_scale))
        frames.append(states)
    return frames


# ── Wordmark phase ───────────────────────────────────────────────────────────
def apply_wordmark_phase(
    pill_frames: list[list[PillState]],
    settle_end: int,
    include_wordmark: bool = True,
    include_motto: bool = False,
    word_dur: int = 14,
    word_pause: int = 4,
    motto_dur: int = 12,
    hold_dur: int = 16,
) -> tuple[list[list[PillState]], list[float], list[float], list[float]]:
    finals = pill_frames[min(settle_end, len(pill_frames) - 1)]
    states_out = list(pill_frames)
    alphas: list[float] = [0.0] * len(pill_frames)
    drops: list[float] = [0.0] * len(pill_frames)
    motto: list[float] = [0.0] * len(pill_frames)

    if not include_wordmark:
        for _ in range(hold_dur):
            states_out.append(finals)
            alphas.append(0.0)
            drops.append(0.0)
            motto.append(0.0)
        return states_out, alphas, drops, motto

    for i in range(word_dur):
        t = (i + 1) / word_dur
        states_out.append(finals)
        alphas.append(ease_out_cubic(t))
        drops.append(1.0 - ease_out_back(t, s=1.4))
        motto.append(0.0)

    for _ in range(word_pause):
        states_out.append(finals)
        alphas.append(1.0)
        drops.append(0.0)
        motto.append(0.0)

    if include_motto:
        for i in range(motto_dur):
            t = (i + 1) / motto_dur
            states_out.append(finals)
            alphas.append(1.0)
            drops.append(0.0)
            motto.append(ease_out_cubic(t))

    for _ in range(hold_dur):
        states_out.append(finals)
        alphas.append(1.0)
        drops.append(0.0)
        motto.append(1.0 if include_motto else 0.0)

    return states_out, alphas, drops, motto


# ── GIF export ───────────────────────────────────────────────────────────────
def quantize_frames(frames: list[Image.Image]) -> list[Image.Image]:
    w, h = frames[0].size
    sample = frames[:: max(1, len(frames) // 8)] + [frames[-1]]
    combined = Image.new("RGB", (w, h * len(sample)))
    for i, fr in enumerate(sample):
        combined.paste(fr.convert("RGB"), (0, i * h))
    palette_ref = combined.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    return [fr.quantize(palette=palette_ref, dither=Image.Dither.FLOYDSTEINBERG) for fr in frames]


def save_gif(path: Path, frames: list[Image.Image], preset: GifPreset) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    small = [f.resize((preset.out_w, preset.out_h), Image.Resampling.LANCZOS) for f in frames]
    quantized = quantize_frames(small)
    quantized[0].save(
        path,
        save_all=True,
        append_images=quantized[1:],
        duration=FRAME_MS,
        loop=0,
        disposal=2,
        optimize=False,
    )


def build_orbit_animation(
    preset: GifPreset,
    include_wordmark: bool = True,
    loop_frames: int = ORBIT_LOOP_FRAMES,
    gradient_stops: tuple[tuple[float, str], ...] | None = None,
    straight: bool = True,
) -> list[Image.Image]:
    """Orbit loop with optional still wordmark visible from frame 0.

    When ``gradient_stops`` is given, pills are filled with a global-space
    diagonal gradient (per slot) so the assembled mark matches the SVG logo;
    pills crossfade between slot colors as they swap, keeping the resting mark
    identical after every hop. ``straight`` selects straight-line (staggered)
    vs. legacy circular-arc travel.
    """
    layout = compute_layout(preset)
    word_fs = int(preset.canvas_h * preset.wordmark_size)
    font = resolve_font(word_fs) if include_wordmark else None
    pill_frames = motion_orbit(layout, preset, loop_frames, straight=straight)

    if gradient_stops is None:
        sprites = [make_pill_sprite(p, layout, preset) for p in PILLS]
        frames: list[Image.Image] = []
        for st in pill_frames:
            fr = render_frame(
                layout, preset, sprites, st,
                word_alpha=1.0 if include_wordmark else 0.0,
                word_drop=0.0,
                font=font,
            )
            frames.append(fr.convert("RGB"))
        return frames

    slot_centers = [layout.pill_center(p) for p in PILLS]
    slot_sprites = [
        make_gradient_pill_sprite(slot_centers[s], layout, preset, gradient_stops)
        for s in range(3)
    ]
    hop_move = ORBIT_HOP_MOVE
    hop_total = ORBIT_HOP_MOVE + ORBIT_HOP_HOLD

    frames = []
    for fi, st in enumerate(pill_frames):
        hop_idx = (fi % loop_frames) // hop_total
        hop_t = (fi % loop_frames) % hop_total
        in_hold = hop_t >= hop_move

        bg = draw_background(preset).convert("RGBA")
        for i in range(3):
            start_slot = _slot_at_hop(i, hop_idx)
            end_slot = _slot_at_hop(i, hop_idx + 1)
            if in_hold or end_slot == start_slot:
                sprite = slot_sprites[end_slot]
            else:
                raw_p = _orbit_progress(hop_t, start_slot) if straight else (hop_t / hop_move)
                move_p = ease_out_cubic(raw_p)
                sprite = Image.blend(
                    slot_sprites[start_slot], slot_sprites[end_slot], move_p
                )
            state = st[i]
            composite_pill(
                bg, sprite, state.x, state.y, state.angle, preset,
                state.scale_x, state.scale_y,
            )
        if include_wordmark and font is not None:
            _draw_static_wordmark(bg, layout, preset, font)
        frames.append(bg.convert("RGB"))
    return frames


def build_animation(
    preset: GifPreset,
    motion_fn: Callable,
    include_wordmark: bool = True,
    include_motto: bool = False,
) -> list[Image.Image]:
    layout = compute_layout(preset)
    sprites = [make_pill_sprite(p, layout, preset) for p in PILLS]
    word_fs = int(preset.canvas_h * preset.wordmark_size)
    font = resolve_font(word_fs) if include_wordmark else None
    motto_font = resolve_font(int(preset.canvas_h * 0.032)) if include_motto else None

    settle_frames = 42
    pill_frames = motion_fn(layout, preset, settle_frames)
    settle_end = len(pill_frames) - 1
    states, alphas, drops, mottos = apply_wordmark_phase(
        pill_frames, settle_end,
        include_wordmark=include_wordmark,
        include_motto=include_motto,
        word_pause=0 if not include_motto else 4,
        motto_dur=0 if not include_motto else 12,
    )

    frames: list[Image.Image] = []
    for i, st in enumerate(states):
        fr = render_frame(
            layout, preset, sprites, st, alphas[i], drops[i], font,
            motto_alpha=mottos[i], motto_font=motto_font,
        )
        frames.append(fr.convert("RGB"))
    return frames


def run_log_jammin_batch(arg: str) -> None:
    preset = log_jammin_preset()
    print(f"Canvas {preset.canvas_w}x{preset.canvas_h} -> {preset.out_w}x{preset.out_h} @ {FPS}fps")
    print(f"Output: {OUT_DIR}")

    do_motto = arg in ("both", "motto")
    do_plain = arg in ("both", "plain")
    variants = (
        ("logo-toss-a", motion_toss),
        ("logo-drop-b", motion_drop),
        ("logo-scatter-c", motion_scatter),
    )
    for stem, motion in variants:
        if do_motto:
            out_path = OUT_DIR / f"{stem}.gif"
            print(f"  {out_path.name} (motto)...", end=" ", flush=True)
            frames = build_animation(preset, motion, include_wordmark=True, include_motto=True)
            save_gif(out_path, frames, preset)
            print(f"{len(frames)} frames")
        if do_plain:
            out_path = OUT_DIR / f"{stem}-plain.gif"
            print(f"  {out_path.name} (plain)...", end=" ", flush=True)
            frames = build_animation(preset, motion, include_wordmark=True, include_motto=False)
            save_gif(out_path, frames, preset)
            print(f"{len(frames)} frames")


def run_blue_batch() -> None:
    """Deck-navy orbit: mark + still wordmark, plus mark-only plain variant."""
    preset = blue_preset()
    print(f"Blue orbit batch -> {OUT_DIR}")
    print(f"Canvas {preset.canvas_w}x{preset.canvas_h} -> {preset.out_w}x{preset.out_h} @ {FPS}fps")

    jobs = (
        # filename, wordmark, straight
        ("logo-orbit-blue.gif", True, True),
        ("logo-orbit-blue-plain.gif", False, True),
        ("logo-orbit-blue-circle.gif", True, False),
    )
    for filename, wordmark, straight in jobs:
        plain_preset = preset
        if not wordmark:
            plain_preset = GifPreset(
                out_w=preset.out_w,
                out_h=preset.out_h,
                supersample=preset.supersample,
                log_fill=preset.log_fill,
                log_edge=preset.log_edge,
                knob_edge=preset.knob_edge,
                bg_top=preset.bg_top,
                bg_bottom=preset.bg_bottom,
                layout_mode="mark_center",
                shadow_rgba=preset.shadow_rgba,
            )
        print(f"  {filename}...", end=" ", flush=True)
        frames = build_orbit_animation(
            plain_preset,
            include_wordmark=wordmark,
            gradient_stops=ORBIT_GRADIENT_STOPS,
            straight=straight,
        )
        save_gif(OUT_DIR / filename, frames, plain_preset)
        print(f"{len(frames)} frames")


def run_midnight_batch() -> None:
    """Six white-on-black drop GIFs: sm/lg × wordmark / plain square / plain wide."""
    jobs = (
        ("logo-drop-midnight-sm.gif", 120, 120, 2, "wordmark", True),
        ("logo-drop-midnight-sm-plain.gif", 120, 120, 2, "mark_center", False),
        ("logo-drop-midnight-sm-plain-wide.gif", 213, 120, 2, "mark_wide", False),
        ("logo-drop-midnight.gif", 400, 400, 4, "wordmark", True),
        ("logo-drop-midnight-plain.gif", 400, 400, 4, "mark_center", False),
        ("logo-drop-midnight-plain-wide.gif", 711, 400, 4, "mark_wide", False),
    )
    print(f"Midnight drop batch -> {OUT_DIR}")
    for filename, ow, oh, ss, mode, wordmark in jobs:
        preset = midnight_preset(ow, oh, ss, mode)  # type: ignore[arg-type]
        print(f"  {filename} ({ow}x{oh}, {mode})...", end=" ", flush=True)
        frames = build_animation(
            preset, motion_drop,
            include_wordmark=wordmark,
            include_motto=False,
        )
        save_gif(OUT_DIR / filename, frames, preset)
        print(f"{len(frames)} frames")


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else "both"
    if arg == "midnight":
        run_midnight_batch()
    elif arg == "blue":
        run_blue_batch()
    else:
        run_log_jammin_batch(arg)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
