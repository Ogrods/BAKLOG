"""Generate Inno Setup branding assets (ICO + wizard BMPs) for BAKLOG."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT

BG_TOP = (15, 23, 42)  # --bg #0f172a
BG_BOTTOM = (30, 41, 59)  # --bg-panel #1e293b
ACCENT = (56, 189, 248)  # --accent #38bdf8
LOGO_FILL = (255, 255, 255)
TEXT = (248, 250, 252)


def _rounded_rect(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int],
) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def draw_logo_mark(
    img: Image.Image,
    center: tuple[float, float],
    scale: float,
    fill: tuple[int, int, int] = LOGO_FILL,
) -> None:
    """Draw the three-pill BAKLOG mark (favicon geometry, viewBox 0..100)."""
    draw = ImageDraw.Draw(img)
    cx, cy = center
    s = scale / 100.0

    def map_rect(x: int, y: int, w: int, h: int, rx: int) -> None:
        left = cx + (x - 50) * s
        top = cy + (y - 50) * s
        _rounded_rect(
            draw,
            (
                int(left),
                int(top),
                int(left + w * s),
                int(top + h * s),
            ),
            max(1, int(rx * s)),
            fill,
        )

    map_rect(2, 52, 46, 24, 12)
    map_rect(52, 52, 46, 24, 12)
    map_rect(27, 24, 46, 24, 12)


def _vertical_gradient(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(
            int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3)
        )
        draw.line([(0, y), (w, y)], fill=color)
    return img


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


def make_wizard_large() -> Image.Image:
    """Inno WizardImageFile: 164 x 314, 24-bit BMP."""
    img = _vertical_gradient((164, 314))
    draw = ImageDraw.Draw(img)
    draw_logo_mark(img, (82, 72), scale=95)

    title_font = _load_font(22, bold=True)
    tag_font = _load_font(11)
    small_font = _load_font(9)

    draw.text((82, 138), "BAKLOG", font=title_font, fill=TEXT, anchor="mm")
    draw.line([(24, 158), (140, 158)], fill=ACCENT, width=2)
    draw.multiline_text(
        (82, 178),
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
        fill=(148, 163, 184),
        anchor="mm",
        align="center",
        spacing=3,
    )
    return img


def make_wizard_small() -> Image.Image:
    """Inno WizardSmallImageFile: 55 x 55, 24-bit BMP."""
    img = Image.new("RGB", (55, 55), BG_TOP)
    draw_logo_mark(img, (27.5, 27.5), scale=52, fill=ACCENT)
    return img


def make_icon() -> Image.Image:
    """Master square icon for multi-size ICO."""
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    base = Image.new("RGB", (size, size), BG_TOP)
    draw_logo_mark(base, (size / 2, size / 2 - 8), scale=200)
    img.paste(base)
    return img


def write_assets() -> list[Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    large = make_wizard_large()
    large_path = OUT_DIR / "installer-wizard-large.bmp"
    large.save(large_path, format="BMP")
    written.append(large_path)

    small = make_wizard_small()
    small_path = OUT_DIR / "installer-wizard-small.bmp"
    small.save(small_path, format="BMP")
    written.append(small_path)

    icon_master = make_icon()
    ico_path = OUT_DIR / "installer-icon.ico"
    icon_master.save(
        ico_path,
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48), (256, 256)],
    )
    written.append(ico_path)
    return written


def main() -> int:
    paths = write_assets()
    for path in paths:
        print(f"[installer-assets] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
