import json

_SNOOZE_FILE = "update-dismiss.json"


def snooze_path(data_root):
    return data_root / _SNOOZE_FILE


def read_dismissed_version(data_root):
    path = snooze_path(data_root)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    version = raw.get("dismissed_version")
    if isinstance(version, str) and version.strip():
        return version.strip()
    return None


def write_dismissed_version(data_root, version):
    data_root.mkdir(parents=True, exist_ok=True)
    payload = {"dismissed_version": version.strip()}
    path = snooze_path(data_root)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_version_dismissed(data_root, latest_version):
    if not latest_version:
        return False
    dismissed = read_dismissed_version(data_root)
    return dismissed == latest_version.strip()
