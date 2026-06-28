import json
import shutil
import sys
from datetime import UTC, datetime

MIGRATION_MARKER = ".legacy_migration_done"
_ROOT_FILES = ("itad_prices.json", "free_claims.json", "sponsors.json", ".env", "license.json", "refresh.log")
_SKIP_NAMES = frozenset({"BAKLOG.exe", "BAKLOG Tray.exe", "_internal", "dist", "portable.txt", MIGRATION_MARKER})


def _now_iso():
    return datetime.now(UTC).isoformat()


def migration_marker_path(target):
    return target / MIGRATION_MARKER


def target_has_meaningful_data(target):
    if (target / "profiles" / "index.json").is_file():
        return True
    default_prof = target / "profiles" / "default"
    if default_prof.is_dir():
        try:
            if any(default_prof.iterdir()):
                return True
        except OSError:
            pass
    try:
        for entry in target.iterdir():
            name = entry.name
            if name.startswith("games_") and name.endswith(".json"):
                return True
            if name.startswith("games_wishlist_") and name.endswith(".json"):
                return True
    except OSError:
        return False
    return False


def legacy_has_user_artifacts(legacy):
    for rel in ("profiles", "data", "cache"):
        if (legacy / rel).exists():
            return True
    for name in _ROOT_FILES:
        if (legacy / name).is_file():
            return True
    try:
        for entry in legacy.iterdir():
            name = entry.name
            if name in _SKIP_NAMES or name.startswith("."):
                continue
            if name.startswith("games_") and name.endswith(".json"):
                return True
            if name.startswith("games_wishlist_") and name.endswith(".json"):
                return True
    except OSError:
        return False
    return False


def _move_path(src, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite existing destination: {dest}")
    shutil.move(str(src), str(dest))
    return src.name


def _move_or_merge_path(src, dest, *, rel_prefix=""):
    moved = []
    if not src.exists():
        return moved
    label = rel_prefix or src.name
    if src.is_file():
        if dest.exists():
            return moved
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(label)
        return moved
    if not dest.exists():
        shutil.move(str(src), str(dest))
        moved.append(label)
        return moved
    dest.mkdir(parents=True, exist_ok=True)
    for child in list(src.iterdir()):
        child_label = f"{label}/{child.name}" if label else child.name
        moved.extend(_move_or_merge_path(child, dest / child.name, rel_prefix=child_label))
    try:
        if src.is_dir() and (not any(src.iterdir())):
            src.rmdir()
    except OSError:
        pass
    return moved


def _write_migration_marker(target, legacy, moved):
    migration_marker_path(target).write_text(
        json.dumps({"from": str(legacy), "at": _now_iso(), "moved": moved}, indent=2), encoding="utf-8"
    )


def migrate_legacy_colocated_data(legacy, target):
    legacy = legacy.resolve()
    target = target.resolve()
    notes = []
    if migration_marker_path(target).is_file():
        return notes
    if legacy == target:
        return notes
    if not legacy_has_user_artifacts(legacy):
        return notes
    target.mkdir(parents=True, exist_ok=True)
    moved = []
    try:
        for dirname in ("profiles", "data", "cache"):
            src = legacy / dirname
            if not src.exists():
                continue
            dest = target / dirname
            moved.extend(_move_or_merge_path(src, dest, rel_prefix=dirname))
        for name in _ROOT_FILES:
            src = legacy / name
            if not src.is_file():
                continue
            dest = target / name
            if dest.exists():
                continue
            moved.append(_move_path(src, dest))
        for entry in list(legacy.iterdir()):
            name = entry.name
            if name in _SKIP_NAMES or name.startswith("."):
                continue
            if not ((name.startswith("games_") or name.startswith("games_wishlist_")) and name.endswith(".json")):
                continue
            dest = target / name
            if dest.exists():
                continue
            moved.append(_move_path(entry, dest))
        if not legacy_has_user_artifacts(legacy):
            _write_migration_marker(target, legacy, moved)
            if moved:
                notes.append(f"migrated {len(moved)} item(s) from {legacy} to {target}")
                for item in moved:
                    print(f"[data_dir] moved {item}", file=sys.stderr, flush=True)
            else:
                notes.append(f"legacy migration complete at {target}")
        else:
            notes.append(
                f"migration incomplete; remaining legacy data at {legacy} ({len(moved)} item(s) moved this pass)"
            )
            for item in moved:
                print(f"[data_dir] moved {item}", file=sys.stderr, flush=True)
    except Exception as exc:
        notes.append(f"migration failed ({exc!r}); legacy data may still be at {legacy}")
        print(f"[data_dir] migration failed: {exc!r}", file=sys.stderr, flush=True)
    return notes
