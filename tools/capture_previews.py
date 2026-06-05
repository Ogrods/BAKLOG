#!/usr/bin/env python3
"""Capture README / marketing preview screenshots via headless Chrome.

Requires a running local server with auth disabled, e.g.:

  BAKLOG_AUTH_DISABLED=1 PORT=8766 python server.py
  python tools/capture_previews.py --url http://127.0.0.1:8766/
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from auth.cdp_browser import find_chromium_executable  # noqa: E402  (needs ROOT on sys.path first)

DASHBOARD_OUT = ROOT / "dashboard.png"
BOOTSTRAP = "/preview-bootstrap.html"


@contextmanager
def _temporary_dashboard_view(base_url: str):
    """Force server prefs to dashboard for a clean hero capture, then restore."""
    url = f"{base_url.rstrip('/')}/api/personal"
    original_view = None
    doc = None
    try:
        with urllib.request.urlopen(url, timeout=15) as res:
            doc = json.loads(res.read().decode("utf-8"))
        original_view = (doc.get("prefs") or {}).get("activeView")
        if original_view != "dashboard":
            doc.setdefault("prefs", {})["activeView"] = "dashboard"
            payload = json.dumps(doc).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url.rstrip("/"),
                },
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=15):
                pass
        yield
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach {url} — is the dev server running?") from exc
    finally:
        if doc is not None and original_view not in (None, "dashboard"):
            doc.setdefault("prefs", {})["activeView"] = original_view
            payload = json.dumps(doc).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Origin": base_url.rstrip("/"),
                },
                method="PUT",
            )
            try:
                with urllib.request.urlopen(req, timeout=15):
                    pass
            except urllib.error.URLError:
                pass


def capture_dashboard(url: str, out: Path, *, width: int = 1400, height: int = 900) -> None:
    chrome = find_chromium_executable()
    base = url.rstrip("/")
    bootstrap = f"{base}{BOOTSTRAP}"
    profile = Path(tempfile.mkdtemp(prefix="baklog-shot-"))
    try:
        with _temporary_dashboard_view(base):
            common = [
                str(chrome),
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--user-data-dir={profile}",
                f"--window-size={width},{height}",
                "--virtual-time-budget=45000",
                f"--screenshot={out}",
                bootstrap,
            ]
            subprocess.run(common, check=True, capture_output=True, text=True)
        if not out.is_file():
            raise RuntimeError(f"Chrome did not write {out}")
        print(f"Wrote {out} ({out.stat().st_size} bytes)")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture BAKLOG preview screenshots.")
    parser.add_argument("--url", default="http://127.0.0.1:8766/", help="Dashboard base URL")
    parser.add_argument("--out", type=Path, default=DASHBOARD_OUT, help="dashboard.png output path")
    args = parser.parse_args()
    capture_dashboard(args.url, args.out)


if __name__ == "__main__":
    main()
