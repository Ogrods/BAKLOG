"""BAKLOG system tray launcher.

Runs quietly in the OS tray: starts the local BAKLOG server (``server.py``) as a
child process, opens your backlog in the default browser, and gives you a menu
to reopen, restart, or quit. No heavy launcher — the dashboard still renders in
a normal browser window against your local data.

Run it:
    python tray_app.py            # dev (clone-and-run)
    BAKLOG.exe (tray build)       # frozen onedir build

Optional deps (tray UI):
    pip install pystray Pillow

If those aren't installed, the tray falls back to a headless mode: it starts the
server, opens the browser, and waits — same data, no tray icon.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from shared.install_paths import bundle_root, is_frozen
from shared.startup import is_startup_enabled, startup_supported, toggle_startup

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))


def server_url() -> str:
    return f"http://{HOST}:{PORT}/"


def _port_open(timeout: float = 0.3) -> bool:
    """True when something is already accepting TCP on HOST:PORT."""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def python_executable() -> str:
    """The interpreter used to launch server.py in dev. Prefers the project venv
    so the tray doesn't accidentally use the Windows Store python stub."""
    override = os.environ.get("BAKLOG_PYTHON", "").strip()
    if override:
        return override
    root = bundle_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",  # Windows
        root / ".venv" / "bin" / "python",          # POSIX
        root / ".venv" / "bin" / "python3",
    ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return sys.executable


def _server_argv() -> list[str]:
    """Command that launches the BAKLOG server.

    Frozen: the bundled exe runs the server when launched with no fetcher args.
    Dev: run server.py with the project interpreter.
    """
    if is_frozen():
        return [sys.executable]
    return [python_executable(), str(bundle_root() / "server.py")]


def make_icon_image(size: int = 64):
    """Draw the white BAKLOG logo mark on a slate card so the tray needs no
    raster asset on disk. This reproduces assets/baklog-logo-white.svg (three
    rounded bars with knob cut-outs) since Pillow cannot rasterize SVG and we
    avoid an extra rendering dependency. Requires Pillow; raises ImportError
    if missing."""
    from PIL import Image, ImageDraw

    slate = (15, 23, 42, 255)        # slate-900 background
    white = (255, 255, 255, 255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Slate card fills the whole canvas (no transparent border) so the icon
    # reads large in the tray; only the corners are rounded.
    radius = max(4, size // 5)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=slate)

    # The white logo lives in SVG viewBox x:[2,98], y:[24,76] (96x52, wide).
    # Fit it width-constrained with a small side margin and center it vertically
    # so it fills as much of the card as possible.
    margin = max(2, size // 12)
    content_w = size - 2 * margin
    scale = content_w / 96.0
    logo_h = 52 * scale
    off_x = margin
    off_y = (size - logo_h) / 2

    def tx(lx: float) -> float:
        return off_x + (lx - 2) * scale

    def ty(ly: float) -> float:
        return off_y + (ly - 24) * scale

    r = 12 * scale  # SVG corner radius
    # Three rounded bars (x, y, w, h) in SVG units.
    for bx, by, bw, bh in [(2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24)]:
        draw.rounded_rectangle(
            [tx(bx), ty(by), tx(bx + bw), ty(by + bh)],
            radius=r,
            fill=white,
        )

    # Knob cut-outs: punch slate circles where the SVG mask removed material.
    knob_r = 8 * scale
    for cx, cy in [(14, 64), (64, 64), (39, 36)]:
        draw.ellipse(
            [tx(cx) - knob_r, ty(cy) - knob_r, tx(cx) + knob_r, ty(cy) + knob_r],
            fill=slate,
        )
    return img


def tray_icon_path() -> Path:
    """Swappable tray icon asset. Drop a PNG here to override the drawn mark."""
    return bundle_root() / "assets" / "tray-icon.png"


def load_icon_image():
    """Prefer the on-disk PNG (so the icon can be swapped without code changes),
    falling back to the drawn BAKLOG mark. Requires Pillow."""
    from PIL import Image

    path = tray_icon_path()
    try:
        if path.is_file():
            return Image.open(path)
    except Exception:  # noqa: BLE001 - a bad/missing asset must never block the tray
        pass
    return make_icon_image()


class ServerController:
    """Owns the server child process: start, stop, restart, status."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None

    def is_running(self) -> bool:
        return _port_open()

    def _owns_live_child(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, wait_secs: float = 12.0) -> bool:
        """Start the server unless something is already listening. Returns True
        when the port is accepting connections afterward."""
        if self.is_running():
            return True
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            _server_argv(),
            cwd=str(bundle_root()),
            creationflags=flags,
        )
        deadline = time.monotonic() + wait_secs
        while time.monotonic() < deadline:
            if _port_open():
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(0.15)
        return _port_open()

    def stop(self) -> None:
        if not self._owns_live_child():
            self.proc = None
            return
        proc = self.proc
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass
        self.proc = None

    def restart(self) -> bool:
        self.stop()
        # Give the listener socket a moment to close before re-binding.
        for _ in range(30):
            if not _port_open():
                break
            time.sleep(0.1)
        return self.start()


def open_browser() -> None:
    try:
        webbrowser.open(server_url())
    except Exception:  # noqa: BLE001 - opening a browser must never crash the tray
        pass


def _run_headless(controller: ServerController) -> int:
    """Fallback when pystray/Pillow aren't installed: start server, open browser,
    block until the server exits or Ctrl+C."""
    print(
        "[tray] pystray/Pillow not installed — running headless.\n"
        "       Install the tray UI with: pip install pystray Pillow",
        file=sys.stderr,
        flush=True,
    )
    if not controller.start():
        print("[tray] server failed to start", file=sys.stderr, flush=True)
        return 1
    open_browser()
    print(f"BAKLOG running at {server_url()} — press Ctrl+C to quit.", flush=True)
    try:
        while True:
            time.sleep(1.0)
            if controller.proc is not None and controller.proc.poll() is not None:
                break
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
    return 0


def run_tray() -> int:
    controller = ServerController()
    try:
        import pystray
        from PIL import Image  # noqa: F401 - ensures Pillow is importable for the icon
    except ImportError:
        return _run_headless(controller)

    started = controller.start()
    if not started:
        print("[tray] server failed to start", file=sys.stderr, flush=True)
    open_browser()

    def _on_open(icon, _item) -> None:  # noqa: ANN001 - pystray callback signature
        if not controller.is_running():
            controller.start()
        open_browser()

    def _on_restart(icon, _item) -> None:  # noqa: ANN001
        controller.restart()

    def _on_quit(icon, _item) -> None:  # noqa: ANN001
        controller.stop()
        icon.stop()

    def _toggle_startup(icon, _item) -> None:  # noqa: ANN001
        toggle_startup()

    menu_items = [
        pystray.MenuItem("Open BAKLOG", _on_open, default=True),
        pystray.MenuItem("Restart server", _on_restart),
    ]
    if startup_supported():
        menu_items.append(
            pystray.MenuItem(
                "Start at login",
                _toggle_startup,
                checked=lambda item: is_startup_enabled(),
            )
        )
    menu_items.append(pystray.MenuItem("Quit", _on_quit))
    menu = pystray.Menu(*menu_items)
    icon = pystray.Icon("baklog", load_icon_image(), "BAKLOG", menu=menu)
    try:
        icon.run()
    finally:
        controller.stop()
    return 0


def main() -> int:
    return run_tray()


if __name__ == "__main__":
    raise SystemExit(main())
