#!/usr/bin/env python3
"""Render a marketing HTML one-pager to a single-page PDF via headless Chrome.

Uses CDP `Page.printToPDF` with `preferCSSPageSize` so the page's own
`@page { size: letter }` rule wins, then auto-shrinks `scale` to the largest
value that still fits everything on one physical page.

  python tools/make_one_pager_pdf.py
  python tools/make_one_pager_pdf.py --src marketing/one-pager-contact.html
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import websocket  # noqa: E402  (venv dep, used by auth.cdp_browser)

from auth.cdp_browser import _free_port, find_chromium_executable  # noqa: E402


def _file_url(path: Path) -> str:
    return "file:///" + str(path).replace("\\", "/")


def _page_count(pdf_bytes: bytes) -> int:
    counts = re.findall(rb"/Type\s*/Pages.*?/Count\s+(\d+)", pdf_bytes, re.S)
    if counts:
        return int(counts[0])
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf_bytes))


class _Cdp:
    """Minimal CDP client over a single websocket, using flat session routing."""

    def __init__(self, ws_url: str) -> None:
        self._ws = websocket.create_connection(ws_url, max_size=64 * 1024 * 1024)
        self._id = 0

    def send(self, method: str, params: dict | None = None, *, session_id: str | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        payload: dict = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        self._ws.send(json.dumps(payload))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"{method} failed: {msg['error']}")
                return msg.get("result", {})

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass


def render(src: Path, out: Path) -> None:
    chrome = find_chromium_executable()
    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix="baklog-pdf-"))
    proc = subprocess.Popen(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ws_url = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                    ws_url = json.loads(r.read())["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.1)
        if not ws_url:
            raise RuntimeError("Chrome DevTools endpoint did not come up")

        cdp = _Cdp(ws_url)
        target = cdp.send("Target.createTarget", {"url": "about:blank"})
        target_id = target["targetId"]
        info = cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        session_id = info["sessionId"]

        def send(method: str, params: dict | None = None) -> dict:
            return cdp.send(method, params, session_id=session_id)

        send("Page.enable")
        send("Page.navigate", {"url": _file_url(src)})
        # Let images decode / layout settle.
        time.sleep(2.5)

        best: bytes | None = None
        for scale in (1.0, 0.97, 0.94, 0.91, 0.88, 0.85, 0.82, 0.8):
            result = send(
                "Page.printToPDF",
                {
                    "printBackground": True,
                    "preferCSSPageSize": True,
                    "scale": scale,
                },
            )
            pdf = base64.b64decode(result["data"])
            pages = _page_count(pdf)
            print(f"scale={scale:.2f} -> {pages} page(s)")
            if pages <= 1:
                best = pdf
                break
            best = pdf  # keep last as fallback

        if best is None:
            raise RuntimeError("printToPDF returned no data")
        out.write_bytes(best)
        print(f"Wrote {out} ({out.stat().st_size} bytes)")

        cdp.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a one-pager HTML to a single-page PDF.")
    ap.add_argument("--src", type=Path, default=ROOT / "marketing" / "one-pager.html")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    src = args.src.resolve()
    out = (args.out or src.with_suffix(".pdf")).resolve()
    render(src, out)


if __name__ == "__main__":
    main()
