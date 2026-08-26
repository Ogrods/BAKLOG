import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from scripts.smoke_port_guard import (  # noqa: E402
    port_collision_message,
    port_listener_pid,
    wait_for_owned_server,
)
from scripts.frozen_smoke_paths import (  # noqa: E402
    frozen_server_path,
    smoke_home_env,
)
from shared.bundled_auth_env import parse_env_file  # noqa: E402


def _wait_for_server(base, proc, *, timeout_sec=25.0):
    return wait_for_owned_server(proc, base, timeout_sec=timeout_sec)


def run_smoke(bundle_dir):
    bundle_dir = bundle_dir.resolve()
    exe = frozen_server_path(bundle_dir)
    if not exe.is_file():
        raise FileNotFoundError(f"missing frozen server: {exe}")
    legacy_profiles = bundle_dir / "profiles"
    backup = None
    if legacy_profiles.exists():
        backup = bundle_dir / ".smoke_profiles_backup"
        if backup.exists():
            shutil.rmtree(backup)
        shutil.move(str(legacy_profiles), str(backup))
    legacy_profiles.mkdir()
    (legacy_profiles / "index.json").write_text(json.dumps({"active": "default", "profiles": []}), encoding="utf-8")
    (bundle_dir / "games_steam_smoke.json").write_text('{"games":[]}', encoding="utf-8")
    report = {"ok": False, "bundle_dir": str(bundle_dir)}
    holder = port_listener_pid()
    if holder is not None:
        report["port_collision_before_start"] = holder
        report["error"] = port_collision_message(holder)
        return report
    proc = None
    try:
        with tempfile.TemporaryDirectory(prefix="baklog-migrate-smoke-") as td:
            env, data_dir = smoke_home_env(Path(td))
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / ".env").write_text(
                "BAKLOG_SUPABASE_URL=https://stale.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=stale-anon\n", encoding="utf-8"
            )
            proc = subprocess.Popen(
                [str(exe)],
                cwd=str(bundle_dir),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
            )
            ok, wait_err = _wait_for_server("http://127.0.0.1:8765", proc)
            if not ok:
                err = (proc.stderr.read() if proc.stderr else b"").decode("utf-8", errors="replace")
                report["error"] = wait_err or f"server did not respond within timeout; stderr tail: {err[-500:]}"
                return report
            migrated_index = data_dir / "profiles" / "index.json"
            migrated_games = data_dir / "games_steam_smoke.json"
            report["data_dir"] = str(data_dir)
            report["migrated_index"] = migrated_index.is_file()
            report["migrated_games"] = migrated_games.is_file()
            report["legacy_profiles_gone"] = not legacy_profiles.exists()
            bundle_auth = parse_env_file(bundle_dir / ".env")
            data_auth = parse_env_file(data_dir / ".env")
            report["auth_env_synced"] = (
                bundle_auth.get("BAKLOG_SUPABASE_URL") == data_auth.get("BAKLOG_SUPABASE_URL")
                and bundle_auth.get("BAKLOG_SUPABASE_ANON_KEY") == data_auth.get("BAKLOG_SUPABASE_ANON_KEY")
                and (data_auth.get("BAKLOG_SUPABASE_URL") != "https://stale.supabase.co")
            )
            report["ok"] = all(
                (
                    report["migrated_index"],
                    report["migrated_games"],
                    report["legacy_profiles_gone"],
                    report["auth_env_synced"],
                )
            )
            return report
    finally:
        if proc is not None and proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(proc.pid), "/T"], capture_output=True, check=False)
            else:
                proc.terminate()
        smoke_games = bundle_dir / "games_steam_smoke.json"
        if smoke_games.is_file():
            smoke_games.unlink()
        if legacy_profiles.exists():
            shutil.rmtree(legacy_profiles, ignore_errors=True)
        if backup is not None and backup.exists():
            if legacy_profiles.exists():
                shutil.rmtree(legacy_profiles, ignore_errors=True)
            shutil.move(str(backup), str(legacy_profiles))


def main():
    parser = argparse.ArgumentParser(description="Frozen legacy data-dir migration smoke")
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=_REPO / "release" / "BAKLOG",
        help="PyInstaller onedir output (contains BAKLOG server binary)",
    )
    parser.add_argument("--json-out", type=Path, default=None, help="Write JSON report to this path")
    args = parser.parse_args()
    report = run_smoke(args.bundle_dir)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
