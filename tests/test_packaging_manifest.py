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
    block = re.search(r"hiddenimports\s*=\s*\[(.*?)\]", text, re.DOTALL)
    assert block, "hiddenimports block not found in baklog.spec"
    return set(re.findall(r'"([^"]+)"', block.group(1)))


def test_manifest_scripts_in_pyinstaller_hiddenimports() -> None:
    stems = _manifest_script_stems()
    hidden = _spec_hiddenimports()
    missing = sorted(stems - hidden)
    assert not missing, (
        "packaging/baklog.spec hiddenimports missing manifest scripts: "
        + ", ".join(missing)
    )
