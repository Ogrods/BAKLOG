"""PyInstaller hiddenimports must cover every fetchers/manifest.json script."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fetchers" / "manifest.json"
SPEC = ROOT / "packaging" / "baklog.spec"


def _manifest_script_stems() -> set[str]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stems: set[str] = set()
    for entry in data.get("fetchers") or []:
        script = entry.get("script")
        if script:
            stems.add(Path(script).stem)
    return stems


def _spec_hiddenimports() -> set[str]:
    text = SPEC.read_text(encoding="utf-8")
    blocks = re.findall(r"hiddenimports\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert blocks, "hiddenimports block not found in baklog.spec"
    out: set[str] = set()
    for block in blocks:
        out.update(re.findall(r'"([^"]+)"', block))
    tray_extra = re.search(
        r"tray_hiddenimports\s*=\s*hiddenimports\s*\+\s*\[(.*?)\]",
        text,
        re.DOTALL,
    )
    if tray_extra:
        out.update(re.findall(r'"([^"]+)"', tray_extra.group(1)))
    return out


def test_manifest_scripts_in_pyinstaller_hiddenimports() -> None:
    stems = _manifest_script_stems()
    hidden = _spec_hiddenimports()
    missing = sorted(stems - hidden)
    assert not missing, (
        "packaging/baklog.spec hiddenimports missing manifest scripts: "
        + ", ".join(missing)
    )


def test_pyinstaller_hiddenimports_include_tray_deps() -> None:
    hidden = _spec_hiddenimports()
    for mod in ("pystray", "PIL", "PIL.Image", "PIL.ImageDraw"):
        assert mod in hidden, f"packaging/baklog.spec hiddenimports missing {mod}"
