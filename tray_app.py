"""BAKLOG system tray launcher.

Runs quietly in the OS tray: starts the local BAKLOG server (``server.py``) as a
child process, opens your backlog in the default browser, and gives you a menu
to reopen, restart, or quit. No heavy launcher — the dashboard still renders in
a normal browser window against your local data.

Run it:
    python tray_app.py            # dev (clone-and-run)
    pythonw tray_app.py           # dev, no console window (Windows)
    Start BAKLOG (tray).bat       # from scripts/build_installer.ps1 output

The PyInstaller bundle ships ``BAKLOG Tray.exe`` (primary launcher) and
``BAKLOG.exe`` (server + fetcher dispatch). Frozen login autostart registers
``BAKLOG Tray.exe``.

Optional deps (tray UI):
    pip install pystray Pillow

If those aren't installed, the tray falls back to a headless mode: it starts the
server, opens the browser, and waits — same data, no tray icon.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from shared.install_paths import bundle_root, data_root, frozen_server_exe, is_frozen
from shared.startup import (
    is_startup_enabled,
    python_executable,
    startup_supported,
    toggle_startup,
)
from shared.tray_lock import acquire_tray_lock

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
_BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local"
_GRACEFUL_SHUTDOWN_WAIT_SEC = 8.0
_TERMINATE_WAIT_SEC = 5.0


def server_url() -> str:
    return f"http://{HOST}:{PORT}/"


def _port_open(timeout: float = 0.3) -> bool:
    """True when something is already accepting TCP on HOST:PORT."""
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _server_argv() -> list[str]:
    """Command that launches the BAKLOG server.

    Frozen: sibling ``BAKLOG.exe`` next to ``BAKLOG Tray.exe``.
    Dev: run server.py with the project interpreter.
    """
    if is_frozen():
        server = frozen_server_exe()
        if not server.is_file():
            raise FileNotFoundError(
                f"BAKLOG server not found next to tray launcher: {server}"
            )
        return [str(server)]
    return [python_executable(), str(bundle_root() / "server.py")]


def _request_graceful_shutdown() -> bool:
    """Ask the server to shut down via localhost API. True when the port closes."""
    if not _port_open():
        return True
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/api/shutdown",
        method="POST",
        headers={_BAKLOG_LOCAL_HEADER: "1", "Content-Length": "0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status != 200:
                return False
    except (urllib.error.URLError, OSError, TimeoutError):
        return False
    deadline = time.monotonic() + _GRACEFUL_SHUTDOWN_WAIT_SEC
    while time.monotonic() < deadline:
        if not _port_open():
            return True
        time.sleep(0.15)
    return not _port_open()


def _tray_notify(icon, title: str, message: str) -> None:
    """Best-effort tray balloon/toast; never raises."""
    try:
        icon.notify(message, title=title)
    except Exception:  # noqa: BLE001 - notifications are optional
        print(f"[tray] {title}: {message}", file=sys.stderr, flush=True)


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

    def owns_server(self) -> bool:
        """True when this controller spawned the live server child."""
        return self._owns_live_child()

    def _owns_live_child(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, wait_secs: float = 12.0) -> bool:
        """Start the server unless something is already serving. Returns True
        only when the port is accepting connections afterward.

        If a server we don't own is already listening (a prior instance or a
        manual ``python server.py``), we use it rather than double-binding —
        ``stop()``/``restart()`` only ever touch our own child, so we never kill
        a foreign listener.
        """
        if self.is_running():
            return True
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        child_env = {
            **os.environ,
            "BAKLOG_DATA_DIR": str(data_root().resolve()),
            "BAKLOG_TRAY_PID": str(os.getpid()),
        }
        self.proc = subprocess.Popen(
            _server_argv(),
            cwd=str(bundle_root()),
            env=child_env,
            creationflags=flags,
        )
        deadline = time.monotonic() + wait_secs
        while time.monotonic() < deadline:
            if _port_open():
                return True
            if self.proc.poll() is not None:
                # Child exited before binding — failed start; don't report success.
                self.proc = None
                return False
            time.sleep(0.15)
        # Timed out: only a success if OUR child is still alive and serving.
        if self._owns_live_child() and _port_open():
            return True
        self.stop()
        return False

    def stop(self) -> None:
        if not self._owns_live_child():
            self.proc = None
            return
        proc = self.proc
        assert proc is not None
        pid = proc.pid
        # Graceful path: POST /api/shutdown runs _shutdown_server() in the child
        # so in-flight fetchers are cancelled before the process exits. On Windows
        # proc.terminate() is TerminateProcess and skips atexit handlers.
        if _port_open():
            _request_graceful_shutdown()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None and sys.platform != "win32":
            try:
                os.kill(pid, signal.SIGTERM)
                proc.wait(timeout=_TERMINATE_WAIT_SEC)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=_TERMINATE_WAIT_SEC)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except OSError:
                pass
        self.proc = None

    def restart(self) -> bool:
        """Restart our server child. False when a foreign listener blocks restart."""
        if not self._owns_live_child() and self.is_running():
            return False
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


def open_data_folder() -> None:
    """Open the active profile data directory in the OS file manager."""
    folder = data_root()
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 - intentional shell open on Windows
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)


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
                print("[tray] server exited unexpectedly", file=sys.stderr, flush=True)
                break
    except KeyboardInterrupt:
        pass
    finally:
        controller.stop()
    return 0


def _start_server_watchdog(icon, controller: ServerController) -> threading.Thread:
    """Notify when our owned server child dies and nothing is listening."""

    def _loop() -> None:
        notified = False
        while True:
            time.sleep(2.0)
            if controller._owns_live_child():
                notified = False
                continue
            proc = controller.proc
            if proc is not None and proc.poll() is not None:
                controller.proc = None
                if not notified and not controller.is_running():
                    notified = True
                    _tray_notify(
                        icon,
                        "BAKLOG server stopped",
                        "The local server exited unexpectedly. Use Open BAKLOG to restart.",
                    )

    thread = threading.Thread(target=_loop, name="tray-server-watch", daemon=True)
    thread.start()
    return thread


def run_tray() -> int:
    controller = ServerController()
    try:
        import pystray
        from PIL import Image  # noqa: F401 - ensures Pillow is importable for the icon
    except ImportError:
        return _run_headless(controller)

    started = controller.start()
    if started:
        open_browser()
    else:
        print("[tray] server failed to start", file=sys.stderr, flush=True)

    def _on_open(icon, _item) -> None:  # noqa: ANN001 - pystray callback signature
        if not controller.is_running():
            if not controller.start():
                _tray_notify(icon, "Start failed", "Could not start the BAKLOG server.")
                return
        open_browser()

    def _on_open_data_folder(icon, _item) -> None:  # noqa: ANN001
        try:
            open_data_folder()
        except OSError as exc:
            _tray_notify(icon, "Open folder failed", str(exc))

    def _on_restart(icon, _item) -> None:  # noqa: ANN001
        if not controller.restart():
            if controller.is_running() and not controller.owns_server():
                _tray_notify(
                    icon,
                    "Restart skipped",
                    "The server was not started by BAKLOG tray — restart it manually.",
                )
            else:
                _tray_notify(icon, "Restart failed", "Could not restart the BAKLOG server.")

    def _on_quit(icon, _item) -> None:  # noqa: ANN001
        controller.stop()
        icon.stop()

    def _toggle_startup(icon, _item) -> None:  # noqa: ANN001
        toggle_startup()

    menu_items = [
        pystray.MenuItem("Open BAKLOG", _on_open, default=True),
        pystray.MenuItem("Open data folder", _on_open_data_folder),
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
    _start_server_watchdog(icon, controller)
    try:
        icon.run()
    finally:
        controller.stop()
    return 0


def main() -> int:
    if "--uninstall-cleanup" in sys.argv or "--uninstall-wipe-user-data" in sys.argv:
        if not is_frozen():
            print(
                "[uninstall] uninstall cleanup flags require the frozen BAKLOG Tray.exe",
                file=sys.stderr,
                flush=True,
            )
            return 1
    if "--uninstall-cleanup" in sys.argv:
        from shared.uninstall_cleanup import cleanup_autostart

        cleanup_autostart()
        return 0
    if "--uninstall-wipe-user-data" in sys.argv:
        from shared.install_paths import resolved_data_dir_for_uninstall
        from shared.uninstall_cleanup import wipe_user_data

        for note in wipe_user_data(resolved_data_dir_for_uninstall()):
            print(f"[uninstall] {note}", file=sys.stderr, flush=True)
        return 0
    if not acquire_tray_lock():
        print("[tray] another BAKLOG tray instance is already running", file=sys.stderr, flush=True)
        return 0
    return run_tray()


if __name__ == "__main__":
    raise SystemExit(main())
