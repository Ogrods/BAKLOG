"""Generate Inno Setup branding assets (ICO + wizard BMPs) for BAKLOG."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
BRAND_DIR = ROOT / "brand"
OUT_DIR = ROOT
REPO_ROOT = ROOT.parent

BG_TOP = (15, 23, 42)
BG_BOTTOM = (30, 41, 59)
ACCENT = (56, 189, 248)
VIOLET = (168, 85, 247)
TEXT = (248, 250, 252)
MUTED = (148, 163, 184)

PILLS = ((2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24))
KNOBS = ((14, 64), (64, 64), (39, 36))
MARK_BOX = (2, 24, 98, 76)  # viewBox 0..100 mark region inside 105% scaled group


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    dejavu = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    mac_font = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
        if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf"
    )
    candidates: list[Path] = []
    if sys.platform == "win32":
        name = "segoeuib.ttf" if bold else "segoeui.ttf"
        candidates.append(Path("C:/Windows/Fonts") / name)
    candidates.extend([Path(dejavu), Path(mac_font)])
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def _diagonal_gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / max(2 * (size - 1), 1)
            px[x, y] = tuple(
                int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
            )
    return img


def _mark_gradient(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / max(2 * (size - 1), 1)
            px[x, y] = tuple(
                int(ACCENT[i] + (VIOLET[i] - ACCENT[i]) * t) for i in range(3)
            )
    return img


def _draw_mark_layer(size: int, *, pad: float = 0.12) -> Image.Image:
    """Gradient three-pill mark with transparent knob holes (RGBA)."""
    min_x, min_y, max_x, max_y = MARK_BOX
    mark_w = max_x - min_x
    mark_h = max_y - min_y
    inner = size * (1 - 2 * pad)
    scale = min(inner / mark_w, inner / mark_h)
    ox = (size - mark_w * scale) / 2
    oy = (size - mark_h * scale) / 2
    grad = _mark_gradient(size)

    def map_pt(vx: float, vy: float) -> tuple[float, float]:
        return ox + (vx - min_x) * scale, oy + (vy - min_y) * scale

    pill_mask = Image.new("L", (size, size), 0)
    pill_draw = ImageDraw.Draw(pill_mask)
    r = 12 * scale
    kr = 8 * scale
    for x, y, w, h in PILLS:
        x0, y0 = map_pt(x, y)
        x1, y1 = map_pt(x + w, y + h)
        pill_draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=255)

    mark_rgb = Image.new("RGBA", (size, size))
    mark_rgb.paste(grad, mask=pill_mask)
    alpha = pill_mask.copy()
    alpha_draw = ImageDraw.Draw(alpha)
    for cx, cy in KNOBS:
        px, py = map_pt(cx, cy)
        alpha_draw.ellipse((px - kr, py - kr, px + kr, py + kr), fill=0)
    mark_rgb.putalpha(alpha)
    return mark_rgb


def render_app_icon(size: int) -> Image.Image:
    """Rounded app icon matching packaging/brand/app-icon.svg."""
    radius = max(4, int(size * 28 / 128))
    base = _diagonal_gradient(size).convert("RGBA")
    rounded = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rounded.paste(base, mask=_rounded_mask(size, radius))

    stroke = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(stroke).rounded_rectangle(
        (1, 1, size - 2, size - 2),
        radius=radius,
        outline=(*ACCENT, 90),
        width=max(1, size // 64),
    )
    icon = Image.alpha_composite(rounded, stroke)
    icon = Image.alpha_composite(icon, _draw_mark_layer(size, pad=0.14))
    return icon


def _vertical_panel(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def make_wizard_large() -> Image.Image:
    """Inno WizardImageFile: 164 x 314, 24-bit BMP."""
    img = _vertical_panel((164, 314))
    icon = render_app_icon(96)
    img.paste(icon, (34, 24), icon)
    draw = ImageDraw.Draw(img)
    title_font = _load_font(20, bold=True)
    tag_font = _load_font(10)
    small_font = _load_font(9)
    draw.text((82, 138), "BAKLOG", font=title_font, fill=TEXT, anchor="mm")
    draw.line([(24, 156), (140, 156)], fill=ACCENT, width=2)
    draw.multiline_text(
        (82, 176),
        "One honest backlog\nacross every store.",
        font=tag_font,
        fill=ACCENT,
        anchor="mm",
        align="center",
        spacing=4,
    )
    draw.multiline_text(
        (82, 252),
        "Local-only beta\nbaklog.app",
        font=small_font,
        fill=MUTED,
        anchor="mm",
        align="center",
        spacing=3,
    )
    return img


def make_wizard_small() -> Image.Image:
    """Inno WizardSmallImageFile: 55 x 55, 24-bit BMP."""
    icon = render_app_icon(55)
    bg = Image.new("RGB", (55, 55), BG_TOP)
    bg.paste(icon, (0, 0), icon)
    return bg


def write_ico(path: Path, master: Image.Image) -> None:
    master.save(
        path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def write_assets() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    large = make_wizard_large()
    large_path = OUT_DIR / "installer-wizard-large.bmp"
    large.save(large_path, format="BMP")
    written.append(large_path)

    small = make_wizard_small()
    small_path = OUT_DIR / "installer-wizard-small.bmp"
    small.save(small_path, format="BMP")
    written.append(small_path)

    icon_master = render_app_icon(256)
    for name in ("installer-icon.ico", "BAKLOG.ico"):
        ico_path = OUT_DIR / name
        write_ico(ico_path, icon_master)
        written.append(ico_path)

    tray_png = render_app_icon(64)
    tray_path = REPO_ROOT / "assets" / "tray-icon.png"
    tray_path.parent.mkdir(parents=True, exist_ok=True)
    tray_png.save(tray_path, format="PNG")
    written.append(tray_path)

    preview = render_app_icon(128)
    preview_path = BRAND_DIR / "app-icon-preview.png"
    preview.save(preview_path, format="PNG")
    written.append(preview_path)

    return written


def main() -> int:
    paths = write_assets()
    for path in paths:
        print(f"[installer-assets] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
