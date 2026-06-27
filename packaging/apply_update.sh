#!/usr/bin/env bash
# Apply a verified BAKLOG release zip over an existing install (macOS).
# Invoked by the local server after security checks — not for manual arbitrary use.
set -euo pipefail

fail() {
  echo "apply_update.sh: $*" >&2
  exit 1
}

MANIFEST_PATH="${1:-}"
[[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]] || fail "Manifest not found"

if ! command -v python3 >/dev/null 2>&1; then
  fail "python3 required to parse manifest"
fi

read_manifest() {
  python3 - "$MANIFEST_PATH" <<'PY'
import json, sys
from pathlib import Path
raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
for key in ("install_dir", "zip_path", "sha256", "server_pid", "tray_pid"):
    print(raw.get(key, ""))
PY
}

mapfile -t MANIFEST_FIELDS < <(read_manifest)
INSTALL_DIR="${MANIFEST_FIELDS[0]}"
ZIP_PATH="${MANIFEST_FIELDS[1]}"
EXPECTED_SHA="${MANIFEST_FIELDS[2]}"
SERVER_PID="${MANIFEST_FIELDS[3]:-0}"
TRAY_PID="${MANIFEST_FIELDS[4]:-0}"

[[ -n "$INSTALL_DIR" && -d "$INSTALL_DIR" ]] || fail "Install dir missing"
[[ -f "$INSTALL_DIR/BAKLOG" ]] || fail "Install dir is not a BAKLOG bundle"
[[ -n "$ZIP_PATH" && -f "$ZIP_PATH" ]] || fail "Update zip missing"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "Expected sha256 invalid"

if command -v shasum >/dev/null 2>&1; then
  ACTUAL_SHA="$(shasum -a 256 "$ZIP_PATH" | awk '{print tolower($1)}')"
elif command -v openssl >/dev/null 2>&1; then
  ACTUAL_SHA="$(openssl dgst -sha256 "$ZIP_PATH" | awk '{print tolower($2)}')"
else
  fail "shasum or openssl required"
fi
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "Update zip sha256 mismatch"

UPDATE_ROOT="$(python3 - <<'PY'
import os, tempfile
print(os.path.join(tempfile.gettempdir(), "BAKLOG-update"))
PY
)"
ZIP_FULL="$(python3 - <<PY
import os
print(os.path.realpath("$ZIP_PATH"))
PY
)"
UPDATE_FULL="$(python3 - <<PY
import os
print(os.path.realpath("$UPDATE_ROOT"))
PY
)"
case "$ZIP_FULL" in
  "$UPDATE_FULL"/*) ;;
  *) fail "Zip path outside trusted update workspace" ;;
esac

wait_pid_gone() {
  local pid="$1"
  local timeout="$2"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ "$pid" -le 0 ]] && return 0
  local i=0
  while kill -0 "$pid" 2>/dev/null; do
    if (( i >= timeout * 4 )); then
      kill -TERM "$pid" 2>/dev/null || true
      sleep 1
      kill -KILL "$pid" 2>/dev/null || true
      return 0
    fi
    sleep 0.25
    i=$((i + 1))
  done
}

wait_pid_gone "$SERVER_PID" 45
wait_pid_gone "$TRAY_PID" 15

STAGING="$UPDATE_ROOT/staging-$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
mkdir -p "$STAGING"
trap 'rm -rf "$STAGING"' EXIT

unzip -q "$ZIP_PATH" -d "$STAGING"

BUNDLE_ROOT=""
while IFS= read -r -d '' candidate; do
  parent="$(dirname "$candidate")"
  if [[ -f "$parent/BAKLOG Tray" ]]; then
    BUNDLE_ROOT="$parent"
    break
  fi
done < <(find "$STAGING" -name BAKLOG -type f -print0)
[[ -n "$BUNDLE_ROOT" ]] || fail "Extracted bundle layout invalid"

BACKUP_DIR="$(dirname "$INSTALL_DIR")/BAKLOG-backup-$(date +%Y%m%d-%H%M%S)"
cp -R "$INSTALL_DIR" "$BACKUP_DIR"

shopt -s dotglob nullglob
for item in "$BUNDLE_ROOT"/*; do
  name="$(basename "$item")"
  dest="$INSTALL_DIR/$name"
  rm -rf "$dest"
  cp -R "$item" "$dest"
done

[[ -f "$INSTALL_DIR/BAKLOG Tray" ]] || fail "Updated bundle missing tray launcher"
chmod +x "$INSTALL_DIR/BAKLOG" "$INSTALL_DIR/BAKLOG Tray" 2>/dev/null || true

cd "$INSTALL_DIR"
exec "./BAKLOG Tray" >/dev/null 2>&1 &

exit 0
