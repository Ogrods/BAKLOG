import json
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

from shared.install_paths import bundle_root, data_root, frozen_server_exe, is_frozen
from shared.startup import is_startup_enabled, python_executable, startup_supported, toggle_startup
from shared.tray_lock import acquire_tray_lock

HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
_BAKLOG_LOCAL_HEADER = "X-BAKLOG-Local"
_GRACEFUL_SHUTDOWN_WAIT_SEC = 8.0
_TERMINATE_WAIT_SEC = 5.0


def server_url():
    return f"http://{HOST}:{PORT}/"


def _port_open(timeout=0.3):
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _server_argv():
    if is_frozen():
        server = frozen_server_exe()
        if not server.is_file():
            raise FileNotFoundError(f"BAKLOG server not found next to tray launcher: {server}")
        return [str(server)]
    return [python_executable(), str(bundle_root() / "server.py")]


def _request_graceful_shutdown():
    if not _port_open():
        return True
    req = urllib.request.Request(
        f"http://{HOST}:{PORT}/api/shutdown", method="POST", headers={_BAKLOG_LOCAL_HEADER: "1", "Content-Length": "0"}
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


def _tray_notify(icon, title, message):
    try:
        icon.notify(message, title=title)
    except Exception:
        print(f"[tray] {title}: {message}", file=sys.stderr, flush=True)


def make_icon_image(size=64):
    from PIL import Image, ImageDraw

    slate = (15, 23, 42, 255)
    white = (255, 255, 255, 255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = max(4, size // 5)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=slate)
    margin = max(2, size // 12)
    content_w = size - 2 * margin
    scale = content_w / 96.0
    logo_h = 52 * scale
    off_x = margin
    off_y = (size - logo_h) / 2

    def tx(lx):
        return off_x + (lx - 2) * scale

    def ty(ly):
        return off_y + (ly - 24) * scale

    r = 12 * scale
    for bx, by, bw, bh in [(2, 52, 46, 24), (52, 52, 46, 24), (27, 24, 46, 24)]:
        draw.rounded_rectangle([tx(bx), ty(by), tx(bx + bw), ty(by + bh)], radius=r, fill=white)
    knob_r = 8 * scale
    for cx, cy in [(14, 64), (64, 64), (39, 36)]:
        draw.ellipse([tx(cx) - knob_r, ty(cy) - knob_r, tx(cx) + knob_r, ty(cy) + knob_r], fill=slate)
    return img


def tray_icon_path():
    return bundle_root() / "assets" / "tray-icon.png"


def load_icon_image():
    from PIL import Image

    path = tray_icon_path()
    try:
        if path.is_file():
            return Image.open(path)
    except Exception:
        pass
    return make_icon_image()


class ServerController:
    def __init__(self):
        self.proc = None

    def is_running(self):
        return _port_open()

    def owns_server(self):
        return self._owns_live_child()

    def _owns_live_child(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, wait_secs=12.0):
        if self.is_running():
            return True
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        child_env = {**os.environ, "BAKLOG_DATA_DIR": str(data_root().resolve()), "BAKLOG_TRAY_PID": str(os.getpid())}
        self.proc = subprocess.Popen(_server_argv(), cwd=str(bundle_root()), env=child_env, creationflags=flags)
        deadline = time.monotonic() + wait_secs
        while time.monotonic() < deadline:
            if _port_open():
                return True
            if self.proc.poll() is not None:
                self.proc = None
                return False
            time.sleep(0.15)
        if self._owns_live_child() and _port_open():
            return True
        self.stop()
        return False

    def stop(self):
        if not self._owns_live_child():
            self.proc = None
            return
        proc = self.proc
        assert proc is not None
        pid = proc.pid
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

    def restart(self):
        if not self._owns_live_child() and self.is_running():
            return False
        self.stop()
        for _ in range(30):
            if not _port_open():
                break
            time.sleep(0.1)
        return self.start()


def open_browser():
    try:
        webbrowser.open(server_url())
    except Exception:
        pass


def open_data_folder():
    folder = data_root()
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
    else:
        subprocess.run(["xdg-open", str(folder)], check=False)


def _run_headless(controller):
    print(
        "[tray] pystray/Pillow not installed — running headless.\n       Install the tray UI with: pip install pystray Pillow",
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


def _start_update_notify(icon):

    def _poll():
        if not is_frozen():
            return
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if _port_open():
                break
            time.sleep(0.5)
        else:
            return
        try:
            req = urllib.request.Request(
                f"http://{HOST}:{PORT}/api/update-check", headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        if not payload.get("update_available"):
            return
        if payload.get("dismissed") is True:
            return
        latest = str(payload.get("latest") or "").strip()
        if not latest:
            return
        _tray_notify(icon, "Update available", f"BAKLOG v{latest} is ready. Open BAKLOG to install.")
        try:
            status_req = urllib.request.Request(
                f"http://{HOST}:{PORT}/api/update/status", headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(status_req, timeout=10) as status_resp:
                status_payload = json.loads(status_resp.read().decode("utf-8"))
            if (
                isinstance(status_payload, dict)
                and status_payload.get("phase") == "ready"
                and (status_payload.get("can_apply") is True)
            ):
                ready_version = str(status_payload.get("version") or latest).strip()
                _tray_notify(
                    icon,
                    "Update ready to install",
                    f"BAKLOG v{ready_version} is downloaded. Open BAKLOG and choose Install & restart.",
                )
        except Exception:
            pass

    threading.Thread(target=_poll, name="tray-update-notify", daemon=True).start()


def _start_server_watchdog(icon, controller):

    def _loop():
        notified = False
        while True:
            time.sleep(2.0)
            if controller._owns_live_child():
                notified = False
                continue
            proc = controller.proc
            if proc is not None and proc.poll() is not None:
                controller.proc = None
                if not notified and (not controller.is_running()):
                    notified = True
                    _tray_notify(
                        icon,
                        "BAKLOG server stopped",
                        "The local server exited unexpectedly. Use Open BAKLOG to restart.",
                    )

    thread = threading.Thread(target=_loop, name="tray-server-watch", daemon=True)
    thread.start()
    return thread


def run_tray():
    controller = ServerController()
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return _run_headless(controller)
    started = controller.start()
    if started:
        open_browser()
    else:
        print("[tray] server failed to start", file=sys.stderr, flush=True)

    def _on_open(icon, _item):
        if not controller.is_running():
            if not controller.start():
                _tray_notify(icon, "Start failed", "Could not start the BAKLOG server.")
                return
        open_browser()

    def _on_open_data_folder(icon, _item):
        try:
            open_data_folder()
        except OSError as exc:
            _tray_notify(icon, "Open folder failed", str(exc))

    def _on_restart(icon, _item):
        if not controller.restart():
            if controller.is_running() and (not controller.owns_server()):
                _tray_notify(
                    icon, "Restart skipped", "The server was not started by BAKLOG tray — restart it manually."
                )
            else:
                _tray_notify(icon, "Restart failed", "Could not restart the BAKLOG server.")

    def _on_quit(icon, _item):
        controller.stop()
        icon.stop()

    def _toggle_startup(icon, _item):
        toggle_startup()

    menu_items = [
        pystray.MenuItem("Open BAKLOG", _on_open, default=True),
        pystray.MenuItem("Open data folder", _on_open_data_folder),
        pystray.MenuItem("Restart server", _on_restart),
    ]
    if startup_supported():
        menu_items.append(
            pystray.MenuItem("Start at login", _toggle_startup, checked=lambda item: is_startup_enabled())
        )
    menu_items.append(pystray.MenuItem("Quit", _on_quit))
    menu = pystray.Menu(*menu_items)
    icon = pystray.Icon("baklog", load_icon_image(), "BAKLOG", menu=menu)
    _start_server_watchdog(icon, controller)
    if started:
        _start_update_notify(icon)
    try:
        icon.run()
    finally:
        controller.stop()
    return 0


def main():
    if "--uninstall-cleanup" in sys.argv or "--uninstall-wipe-user-data" in sys.argv:
        if not is_frozen():
            print("[uninstall] uninstall cleanup flags require the frozen BAKLOG Tray.exe", file=sys.stderr, flush=True)
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
