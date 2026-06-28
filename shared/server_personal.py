import json
import os
import sys
import threading
import time

from shared.profile_paths import personal_backup_dir, personal_dir, personal_path

PERSONAL_BACKUP_KEEP = 10
PERSONAL_MAX_BYTES = 32 * 1024 * 1024
_personal_lock = threading.RLock()
_personal_last_backup_at = 0.0
BAKLOG_ALLOW_EMPTY_HEADER = "X-BAKLOG-Allow-Empty"


class PersonalCorruptError(RuntimeError):
    pass


class PersonalEmptyOverwriteError(RuntimeError):
    pass


def _empty_personal_doc():
    return {"personal": {}, "prefs": {}, "manual": [], "libraryFirstSeen": {}, "updated_at": None, "schema_version": 1}


def _personal_doc_is_meaningful(doc):
    personal = doc.get("personal")
    if isinstance(personal, dict):
        if any((k != "__migrated_v3" for k in personal)):
            return True
    manual = doc.get("manual")
    if isinstance(manual, list) and manual:
        return True
    library_first_seen = doc.get("libraryFirstSeen")
    if isinstance(library_first_seen, dict) and library_first_seen:
        return True
    return False


def _personal_payload_is_empty(validated):
    personal = validated.get("personal") or {}
    if not isinstance(personal, dict):
        return True
    if any((k != "__migrated_v3" for k in personal)):
        return False
    manual = validated.get("manual") or []
    if isinstance(manual, list) and manual:
        return False
    library_first_seen = validated.get("libraryFirstSeen") or {}
    if isinstance(library_first_seen, dict) and library_first_seen:
        return False
    return True


def _normalize_personal_doc(doc):
    doc.setdefault("personal", {})
    doc.setdefault("prefs", {})
    doc.setdefault("manual", [])
    doc.setdefault("libraryFirstSeen", {})
    doc.setdefault("updated_at", None)
    doc.setdefault("schema_version", 1)
    return doc


def _restore_personal_from_backup():
    backup_dir = personal_backup_dir()
    if not backup_dir.is_dir():
        return None
    backups = sorted(backup_dir.glob("personal-*.json"), reverse=True)
    for backup in backups:
        try:
            with backup.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            return _normalize_personal_doc(doc)
    return None


def load_personal_doc():
    with _personal_lock:
        path = personal_path()
        if not path.exists():
            return _empty_personal_doc()
        try:
            with path.open("r", encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            restored = _restore_personal_from_backup()
            if restored is not None:
                print(f"[personal] primary file corrupt ({exc!r}); serving newest backup", file=sys.stderr, flush=True)
                return restored
            raise PersonalCorruptError(f"personal data at {path} is corrupt and no backup could be read") from exc
        if not isinstance(doc, dict):
            raise PersonalCorruptError(f"personal data at {path} is not a JSON object")
        return _normalize_personal_doc(doc)


def _validate_personal_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    personal = payload.get("personal", {})
    prefs = payload.get("prefs", {})
    manual = payload.get("manual", [])
    library_first_seen = payload.get("libraryFirstSeen", {})
    if not isinstance(personal, dict):
        raise ValueError("personal must be an object")
    if not isinstance(prefs, dict):
        raise ValueError("prefs must be an object")
    if not isinstance(manual, list):
        raise ValueError("manual must be an array")
    if not isinstance(library_first_seen, dict):
        raise ValueError("libraryFirstSeen must be an object")
    return {"personal": personal, "prefs": prefs, "manual": manual, "libraryFirstSeen": library_first_seen}


def _rotate_personal_backup():
    global _personal_last_backup_at
    now = time.time()
    if now - _personal_last_backup_at < 300:
        return
    path = personal_path()
    if not path.exists():
        return
    backup_dir = personal_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    backup = backup_dir / f"personal-{stamp}.json"
    try:
        backup.write_bytes(path.read_bytes())
    except OSError as exc:
        print(f"[personal] backup failed: {exc!r}", file=sys.stderr)
        return
    _personal_last_backup_at = now
    backups = sorted(backup_dir.glob("personal-*.json"))
    for old in backups[:-PERSONAL_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass


def _rebind_after_save():
    import server as mod

    mod._refresh_personal_paths()


def save_personal_doc(payload, *, allow_empty=False):
    with _personal_lock:
        validated = _validate_personal_payload(payload)
        if not allow_empty and _personal_payload_is_empty(validated):
            existing = load_personal_doc()
            if _personal_doc_is_meaningful(existing):
                path = personal_path()
                print(f"[personal] refusing empty overwrite of populated doc at {path}", file=sys.stderr, flush=True)
                raise PersonalEmptyOverwriteError("refusing empty overwrite")
        doc = _empty_personal_doc()
        doc.update(validated)
        doc["updated_at"] = time.time()
        pdir = personal_dir()
        pdir.mkdir(parents=True, exist_ok=True)
        path = personal_path()
        _rotate_personal_backup()
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        _rebind_after_save()
        return doc
