import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "landing" / "assets" / "sample"
GAMES = (
    ("neon-drift", "Neon Drift", "portrait", "#38bdf8"),
    ("vault-runner", "Vault Runner", "landscape", "#22d3ee"),
    ("couch-quest", "Couch Quest", "portrait", "#a855f7"),
    ("sale-signal", "Sale Signal", "landscape", "#6ee7b7"),
    ("hidden-circuit", "Hidden Circuit", "portrait", "#f472b6"),
    ("quick-byte", "Quick Byte", "portrait", "#fbbf24"),
    ("coop-cascade", "Coop Cascade", "portrait", "#34d399"),
    ("new-signal", "New Signal", "landscape", "#60a5fa"),
    ("replay-loop", "Replay Loop", "portrait", "#c4b5fd"),
    ("up-next", "Up Next", "portrait", "#38bdf8"),
    ("crit-acclaim", "Crit Acclaim", "landscape", "#22d3ee"),
    ("barrel-roll", "Barrel Roll", "portrait", "#f97316"),
)
BG_TOP = (15, 23, 42)
BG_BOT = (8, 14, 30)
WIN = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
FONTS = (ROOT / "assets" / "fonts" / "SpaceGrotesk-Bold.ttf", WIN / "segoeuib.ttf", WIN / "arialbd.ttf")


def load_font(size):
    for p in FONTS:
        if Path(p).is_file():
            try:
                return ImageFont.truetype(str(p), size)
            except OSError:
                continue
    return ImageFont.load_default()


def hex_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def gradient(w, h, top, bot):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def draw_cover(slug, title, orient, accent):
    if orient == "portrait":
        w, h = (600, 900)
    else:
        w, h = (920, 430)
    accent_rgb = hex_rgb(accent)
    img = gradient(w, h, BG_TOP, BG_BOT)
    draw = ImageDraw.Draw(img)
    cx, cy = (w // 2, int(h * 0.38))
    for r in range(min(w, h) // 2, 0, -8):
        alpha = int(28 * (1 - r / (min(w, h) // 2)))
        c = tuple(min(255, accent_rgb[i] + alpha // 4) for i in range(3))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=c)
    bar_h = max(6, h // 80)
    draw.rectangle((0, h - bar_h, w, h), fill=accent_rgb)
    fs = max(28, min(56, w // max(len(title), 8)))
    font = load_font(fs)
    bbox = draw.textbbox((0, 0), title, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (w - tw) // 2
    ty = (h - th) // 2 - bar_h // 2
    draw.text((tx + 2, ty + 2), title, font=font, fill=(0, 0, 0))
    draw.text((tx, ty), title, font=font, fill=(248, 250, 252))
    wm = load_font(max(12, fs // 4))
    draw.text((16, 16), "BAKLOG SAMPLE", font=wm, fill=accent_rgb)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{slug}.png"
    img.save(path, "PNG", optimize=True)
    print(f"Wrote {path}")


def main():
    for slug, title, orient, accent in GAMES:
        draw_cover(slug, title, orient, accent)
    print("Done.")


if __name__ == "__main__":
    main()
