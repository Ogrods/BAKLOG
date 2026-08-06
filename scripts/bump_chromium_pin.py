#!/usr/bin/env python3
"""Refresh shared/chromium_cft_pin.json from Chrome for Testing Stable.

Downloads each platform zip once, records SHA-256, and writes the pin file.
Run when CDP breaks on an old CfT build:

  .\\.venv\\Scripts\\python.exe scripts\\bump_chromium_pin.py
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ROOT / "shared" / "chromium_cft_pin.json"
LKG_URL = (
    "https://googlechromelabs.github.io/chrome-for-testing/"
    "last-known-good-versions-with-downloads.json"
)
PLATFORMS = ("win64", "mac-arm64", "mac-x64", "linux64")
USER_AGENT = "BAKLOG-bump-chromium-pin"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    req = urllib.request.Request(LKG_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    stable = (payload.get("channels") or {}).get("Stable") or {}
    version = str(stable.get("version") or "").strip()
    chrome_downloads = (stable.get("downloads") or {}).get("chrome") or []
    by_plat = {
        str(item.get("platform")): str(item.get("url") or "").strip()
        for item in chrome_downloads
        if isinstance(item, dict)
    }
    if not version:
        print("Stable channel missing version", file=sys.stderr)
        return 1

    platforms: dict[str, dict[str, str]] = {}
    with tempfile.TemporaryDirectory(prefix="baklog-cft-pin-") as tmp:
        tmp_path = Path(tmp)
        for plat in PLATFORMS:
            url = by_plat.get(plat)
            if not url:
                print(f"missing download for {plat}", file=sys.stderr)
                return 1
            print(f"Downloading {plat}…")
            dest = tmp_path / f"{plat}.zip"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            sha = _sha256_file(dest)
            print(f"  {plat}: {sha} ({dest.stat().st_size} bytes)")
            platforms[plat] = {"url": url, "sha256": sha}

    pin = {
        "version": version,
        "channel": "Stable",
        "source": LKG_URL,
        "platforms": platforms,
    }
    PIN_PATH.write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {PIN_PATH} (CfT {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
