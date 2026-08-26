import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from scripts.frozen_smoke_paths import (  # noqa: E402
    frozen_server_path,
    smoke_home_env,
)
from scripts.frozen_smoke_server import (  # noqa: E402
    MIGRATION_SMOKE_PORT,
    FrozenSmokeServer,
)
from shared.bundled_auth_env import parse_env_file  # noqa: E402


def run_smoke(bundle_dir, *, port=MIGRATION_SMOKE_PORT):
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
    report = {"ok": False, "bundle_dir": str(bundle_dir), "port": port}
    try:
        with tempfile.TemporaryDirectory(prefix="baklog-migrate-smoke-") as td:
            env, data_dir = smoke_home_env(Path(td))
            data_dir.mkdir(parents=True, exist_ok=True)
            (data_dir / ".env").write_text(
                "BAKLOG_SUPABASE_URL=https://stale.supabase.co\nBAKLOG_SUPABASE_ANON_KEY=stale-anon\n", encoding="utf-8"
            )
            with FrozenSmokeServer(exe, cwd=bundle_dir, env=env, port=port) as server:
                if not server.ok:
                    report["error"] = server.error
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
    parser.add_argument(
        "--port",
        type=int,
        default=MIGRATION_SMOKE_PORT,
        help=f"Port for the smoke server (default {MIGRATION_SMOKE_PORT})",
    )
    args = parser.parse_args()
    report = run_smoke(args.bundle_dir, port=args.port)
    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out:
        args.json_out.write_text(text + "\n", encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
