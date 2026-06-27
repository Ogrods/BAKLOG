#!/usr/bin/env bash
# Apply a verified BAKLOG release zip over an existing install (macOS).
# Invoked by the local server after security checks — not for manual arbitrary use.
set -euo pipefail

UPDATE_ROOT="${TMPDIR:-/tmp}/BAKLOG-update"
mkdir -p "$UPDATE_ROOT"

write_apply_result() {
  local ok="$1"
  local err="${2:-}"
  local version="${3:-}"
  local restored="${4:-false}"
  local finished
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  cat >"$UPDATE_ROOT/apply-result.json" <<EOF
{
  "ok": $ok,
  "error": "$err",
  "version": "$version",
  "restored_from_backup": $restored,
  "finished_at": "$finished"
}
EOF
}

fail() {
  write_apply_result false "$1" "" false
  echo "apply_update.sh: $*" >&2
  exit 1
}

json_field() {
  local file="$1"
  local key="$2"
  sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"\\([^\"]*\\)\".*/\\1/p" "$file" | head -1
}

json_field_int() {
  local file="$1"
  local key="$2"
  sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\\([0-9][0-9]*\\).*/\\1/p" "$file" | head -1
}

realpath_safe() {
  local target="$1"
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$target"
  else
    (cd "$(dirname "$target")" && pwd -P)/$(basename "$target")
  fi
}

restore_install_from_backup() {
  local install_dir="$1"
  local backup_dir="$2"
  [[ -d "$backup_dir" ]] || return 1
  rm -rf "${install_dir:?}/"*
  cp -R "$backup_dir/." "$install_dir/"
}

remove_old_backups() {
  local parent="$1"
  local keep="$2"
  local dir
  for dir in "$parent"/BAKLOG-backup-*; do
    [[ -d "$dir" ]] || continue
    [[ "$dir" == "$keep" ]] && continue
    rm -rf "$dir"
  done
}

MANIFEST_PATH="${1:-}"
[[ -n "$MANIFEST_PATH" && -f "$MANIFEST_PATH" ]] || fail "Manifest not found"

INSTALL_DIR="$(json_field "$MANIFEST_PATH" install_dir)"
ZIP_PATH="$(json_field "$MANIFEST_PATH" zip_path)"
EXPECTED_SHA="$(json_field "$MANIFEST_PATH" sha256 | tr '[:upper:]' '[:lower:]')"
VERSION="$(json_field "$MANIFEST_PATH" version)"
SERVER_PID="$(json_field_int "$MANIFEST_PATH" server_pid)"
TRAY_PID="$(json_field_int "$MANIFEST_PATH" tray_pid)"
SERVER_PID="${SERVER_PID:-0}"
TRAY_PID="${TRAY_PID:-0}"

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

ZIP_FULL="$(realpath_safe "$ZIP_PATH")"
UPDATE_FULL="$(realpath_safe "$UPDATE_ROOT")"
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

STAGING="$UPDATE_ROOT/staging-$$-$RANDOM"
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

INSTALL_PARENT="$(dirname "$INSTALL_DIR")"
BACKUP_DIR="$INSTALL_PARENT/BAKLOG-backup-$(date +%Y%m%d-%H%M%S)"
cp -R "$INSTALL_DIR" "$BACKUP_DIR"

if ! (
  shopt -s dotglob nullglob
  for item in "$BUNDLE_ROOT"/*; do
    name="$(basename "$item")"
    dest="$INSTALL_DIR/$name"
    rm -rf "$dest"
    cp -R "$item" "$dest"
  done
); then
  restored=false
  if restore_install_from_backup "$INSTALL_DIR" "$BACKUP_DIR"; then
    restored=true
  fi
  write_apply_result false "Failed to copy update files" "$VERSION" "$restored"
  exit 1
fi

if [[ ! -f "$INSTALL_DIR/BAKLOG Tray" ]]; then
  restored=false
  if restore_install_from_backup "$INSTALL_DIR" "$BACKUP_DIR"; then
    restored=true
  fi
  write_apply_result false "Updated bundle missing tray launcher" "$VERSION" "$restored"
  exit 1
fi

chmod +x "$INSTALL_DIR/BAKLOG" "$INSTALL_DIR/BAKLOG Tray" 2>/dev/null || true
remove_old_backups "$INSTALL_PARENT" "$BACKUP_DIR"
write_apply_result true "" "$VERSION" false

cd "$INSTALL_DIR"
exec "./BAKLOG Tray" >/dev/null 2>&1 &

exit 0
