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

_RESAMPLE = Image.Resampling.LANCZOS
_ICON_SUPER = 4
_WIZARD_LARGE = (164, 314)
_WIZARD_SMALL = 55
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


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


def _downscale(img: Image.Image, size: int | tuple[int, int]) -> Image.Image:
    if isinstance(size, int):
        target = (size, size)
    else:
        target = size
    if img.size == target:
        return img
    return img.resize(target, _RESAMPLE)


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


def _render_app_icon_raw(size: int) -> Image.Image:
    """Render app icon at exact pixel size (no supersampling)."""
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


def render_app_icon(size: int) -> Image.Image:
    """Rounded app icon matching packaging/brand/app-icon.svg."""
    hi = max(size, size * _ICON_SUPER)
    return _downscale(_render_app_icon_raw(hi), size)


def _composite_on_bg(rgba: Image.Image, bg_color: tuple[int, int, int]) -> Image.Image:
    bg = Image.new("RGB", rgba.size, bg_color)
    if rgba.mode == "RGBA":
        bg.paste(rgba, mask=rgba.split()[3])
    else:
        bg.paste(rgba)
    return bg


def _vertical_panel(size: tuple[int, int]) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(int(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    return img


def _make_wizard_large_at(w: int, h: int) -> Image.Image:
    scale = w / _WIZARD_LARGE[0]
    img = _vertical_panel((w, h))
    icon_size = max(1, int(96 * scale))
    icon = render_app_icon(icon_size)
    icon_x = int(34 * scale)
    icon_y = int(24 * scale)
    icon_flat = _composite_on_bg(icon, BG_TOP)
    img.paste(icon_flat, (icon_x, icon_y))
    draw = ImageDraw.Draw(img)
    cx = w // 2
    title_font = _load_font(max(8, int(20 * scale)), bold=True)
    tag_font = _load_font(max(6, int(10 * scale)))
    small_font = _load_font(max(6, int(9 * scale)))
    draw.text((cx, int(138 * scale)), "BAKLOG", font=title_font, fill=TEXT, anchor="mm")
    draw.line(
        [(int(24 * scale), int(156 * scale)), (int(140 * scale), int(156 * scale))],
        fill=ACCENT,
        width=max(1, int(2 * scale)),
    )
    draw.multiline_text(
        (cx, int(176 * scale)),
        "One honest backlog\nacross every store.",
        font=tag_font,
        fill=ACCENT,
        anchor="mm",
        align="center",
        spacing=max(2, int(4 * scale)),
    )
    draw.multiline_text(
        (cx, int(252 * scale)),
        "Local-only beta\nbaklog.app",
        font=small_font,
        fill=MUTED,
        anchor="mm",
        align="center",
        spacing=max(2, int(3 * scale)),
    )
    return img


def make_wizard_large() -> Image.Image:
    """Inno WizardImageFile: 164 x 314, 24-bit BMP."""
    hi = _make_wizard_large_at(_WIZARD_LARGE[0] * 2, _WIZARD_LARGE[1] * 2)
    return _downscale(hi, _WIZARD_LARGE)


def make_wizard_small() -> Image.Image:
    """Inno WizardSmallImageFile: 55 x 55, 24-bit BMP."""
    icon = render_app_icon(_WIZARD_SMALL)
    return _composite_on_bg(icon, BG_TOP)


def write_ico(path: Path, master: Image.Image) -> None:
    img = _downscale(master.convert("RGBA"), 256)
    img.save(path, format="ICO", sizes=[(size, size) for size in ICO_SIZES])


def _ico_embedded_sizes(path: Path) -> set[int]:
    """Read embedded dimensions from the ICO directory (works on all Pillow versions)."""
    data = path.read_bytes()
    if len(data) < 6 or data[:4] != b"\x00\x00\x01\x00":
        with Image.open(path) as img:
            return {img.size[0]} if img.size[0] == img.size[1] else set()
    count = int.from_bytes(data[4:6], "little")
    sizes: set[int] = set()
    offset = 6
    for _ in range(count):
        if offset + 16 > len(data):
            break
        w = data[offset]
        h = data[offset + 1]
        sizes.add(256 if w == 0 else w)
        sizes.add(256 if h == 0 else h)
        offset += 16
    return sizes


def verify_ico(path: Path) -> None:
    """Fail fast when ICO frames are missing expected Windows sizes."""
    found = _ico_embedded_sizes(path)
    required = {16, 32, 48, 256}
    missing = required - found
    if missing:
        raise ValueError(f"{path}: missing ICO sizes {sorted(missing)} (found {sorted(found)})")


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
        verify_ico(ico_path)
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
