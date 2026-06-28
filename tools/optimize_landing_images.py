from __future__ import annotations
from pathlib import Path
from PIL import Image
ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / 'landing' / 'assets' / 'sample'
LANDSCAPE_HERO = ('hero-emberfall', 'hero-hollow-crown', 'hero-tidewright', 'hero-ashen-vale', 'hero-stormhallow', 'hero-dawnbanner')
PORTRAIT_COVER = ('cover-ironveil', 'cover-ashlight-saga', 'cover-hollowmaw', 'cover-encore', 'cover-apex-velocity', 'cover-quick-byte')
LANDSCAPE_SIZE = (1200, 800)
PORTRAIT_SIZE = (600, 900)
WEBP_QUALITY = 80

def optimize_png(slug: str, target_size: tuple[int, int]) -> Path:
    src = SAMPLE / f'{slug}.png'
    if not src.is_file():
        raise FileNotFoundError(src)
    dst = SAMPLE / f'{slug}.webp'
    with Image.open(src) as im:
        im = im.convert('RGB')
        if im.size != target_size:
            im = im.resize(target_size, Image.Resampling.LANCZOS)
        im.save(dst, 'WEBP', quality=WEBP_QUALITY, method=6)
    src_kb = src.stat().st_size / 1024
    dst_kb = dst.stat().st_size / 1024
    print(f'{slug}: {src_kb:7.0f} KB png -> {dst_kb:6.0f} KB webp ({target_size[0]}x{target_size[1]})')
    return dst

def main() -> None:
    total_png = 0.0
    total_webp = 0.0
    for slug in LANDSCAPE_HERO:
        src = SAMPLE / f'{slug}.png'
        total_png += src.stat().st_size / 1024
        optimize_png(slug, LANDSCAPE_SIZE)
        total_webp += (SAMPLE / f'{slug}.webp').stat().st_size / 1024
    for slug in PORTRAIT_COVER:
        src = SAMPLE / f'{slug}.png'
        total_png += src.stat().st_size / 1024
        optimize_png(slug, PORTRAIT_SIZE)
        total_webp += (SAMPLE / f'{slug}.webp').stat().st_size / 1024
    pct = 100 * total_webp / total_png
    print(f'Total: {total_png:.0f} KB png -> {total_webp:.0f} KB webp ({pct:.1f}% of original)')
if __name__ == '__main__':
    main()