#!/usr/bin/env bash
# Apply a verified BAKLOG release zip over an existing install (macOS).
# Invoked by the local server after security checks — not for manual arbitrary use.
set -uo pipefail

UPDATE_ROOT="${TMPDIR:-/tmp}/BAKLOG-update"
mkdir -p "$UPDATE_ROOT"
APPLY_LOG="$UPDATE_ROOT/apply.log"
KILLED_APPS=0
INSTALL_DIR=""
BACKUP_DIR=""
COPY_STARTED=0
RESULT_WRITTEN=0
VERSION=""

write_apply_log() {
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "[$ts] $*" | tee -a "$APPLY_LOG" >&2
}

write_apply_started() {
  cat >"$UPDATE_ROOT/apply-started.json" <<EOF
{
  "pid": $$,
  "written_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "version": "$VERSION"
}
EOF
}

clear_apply_started() {
  rm -f "$UPDATE_ROOT/apply-started.json"
}

touch_applying_lock() {
  if [[ -f "$UPDATE_ROOT/applying.lock" ]]; then
    touch "$UPDATE_ROOT/applying.lock"
  else
    cat >"$UPDATE_ROOT/applying.lock" <<EOF
{
  "version": "$VERSION",
  "written_at": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
}
EOF
  fi
}

write_apply_result() {
  local ok="$1"
  local err="${2:-}"
  local version="${3:-}"
  local restored="${4:-false}"
  if [[ "$RESULT_WRITTEN" -eq 1 ]]; then
    return 0
  fi
  RESULT_WRITTEN=1
  local finished
  finished="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  # Escape quotes in error for JSON
  err="${err//\\/\\\\}"
  err="${err//\"/\\\"}"
  cat >"$UPDATE_ROOT/apply-result.json" <<EOF
{
  "ok": $ok,
  "error": "$err",
  "version": "$version",
  "restored_from_backup": $restored,
  "finished_at": "$finished"
}
EOF
  rm -f "$UPDATE_ROOT/applying.lock"
  clear_apply_started
  write_apply_log "result ok=$ok version=$version error=$err restored=$restored"
}

fail() {
  write_apply_result false "$1" "$VERSION" false
  write_apply_log "fail: $*"
  if [[ "$KILLED_APPS" -eq 1 ]]; then
    start_tray_if_present
  fi
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
  (cd "$(dirname "$target")" && pwd -P)/$(basename "$target")
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

is_linux() {
  [[ "$(uname -s 2>/dev/null || true)" == "Linux" ]]
}

start_app_if_present() {
  if [[ -z "$INSTALL_DIR" ]]; then
    return 0
  fi
  if [[ -x "$INSTALL_DIR/BAKLOG Tray" ]]; then
    write_apply_log "relaunching tray"
    (
      cd "$INSTALL_DIR"
      exec "./BAKLOG Tray" >/dev/null 2>&1 &
    )
  elif is_linux && [[ -x "$INSTALL_DIR/BAKLOG" ]]; then
    # Linux MVP ships without a tray; relaunch the server in a new session.
    write_apply_log "relaunching server (linux MVP, no tray)"
    (
      cd "$INSTALL_DIR"
      if command -v setsid >/dev/null 2>&1; then
        setsid ./BAKLOG >/dev/null 2>&1 &
      else
        ./BAKLOG >/dev/null 2>&1 &
      fi
    )
  else
    write_apply_log "tray/server binary missing; cannot relaunch"
  fi
}

# Back-compat alias for fail()/early-exit paths that still call the old name.
start_tray_if_present() {
  start_app_if_present
}

wait_pid_gone() {
  local pid="$1"
  local timeout="$2"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ "$pid" -le 0 ]] && return 0
  [[ "$pid" -eq $$ ]] && return 0
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

kill_pid_tree() {
  local pid="$1"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 0
  [[ "$pid" -le 0 ]] && return 0
  [[ "$pid" -eq $$ ]] && return 0
  # Best-effort: kill descendants then the root (tray owns the server child).
  # Skip our own PID so a new-session helper is never self-killed.
  if command -v pkill >/dev/null 2>&1; then
    pkill -TERM -P "$pid" 2>/dev/null || true
  fi
  kill -TERM "$pid" 2>/dev/null || true
  sleep 0.5
  if command -v pkill >/dev/null 2>&1; then
    pkill -KILL -P "$pid" 2>/dev/null || true
  fi
  kill -KILL "$pid" 2>/dev/null || true
}

write_apply_log "apply_update.sh start pid=$$"
write_apply_started
touch_applying_lock

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

write_apply_started
touch_applying_lock
write_apply_log "validate install=$INSTALL_DIR version=$VERSION"

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

write_apply_log "killing tray/server trees"
kill_pid_tree "$TRAY_PID"
kill_pid_tree "$SERVER_PID"
KILLED_APPS=1
wait_pid_gone "$SERVER_PID" 45
wait_pid_gone "$TRAY_PID" 15
kill_pid_tree "$TRAY_PID"
kill_pid_tree "$SERVER_PID"
touch_applying_lock

STAGING="$UPDATE_ROOT/staging-$$-$RANDOM"
mkdir -p "$STAGING"
cleanup_staging() {
  rm -rf "$STAGING"
}
trap cleanup_staging EXIT

write_apply_log "extracting zip"
if ! unzip -q "$ZIP_PATH" -d "$STAGING"; then
  fail "Failed to extract update zip"
fi
touch_applying_lock

BUNDLE_ROOT=""
while IFS= read -r -d '' candidate; do
  parent="$(dirname "$candidate")"
  # macOS/Windows bundles include BAKLOG Tray; Linux MVP is server-only.
  if [[ -f "$parent/BAKLOG Tray" ]] || { is_linux && [[ -f "$parent/BAKLOG" ]]; }; then
    BUNDLE_ROOT="$parent"
    break
  fi
done < <(find "$STAGING" -name BAKLOG -type f -print0)
[[ -n "$BUNDLE_ROOT" ]] || fail "Extracted bundle layout invalid"

INSTALL_PARENT="$(dirname "$INSTALL_DIR")"
BACKUP_DIR="$INSTALL_PARENT/BAKLOG-backup-$(date +%Y%m%d-%H%M%S)"
write_apply_log "backup to $BACKUP_DIR"
cp -R "$INSTALL_DIR" "$BACKUP_DIR"
touch_applying_lock

COPY_STARTED=1
write_apply_log "copying bundle overlay"
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
  start_tray_if_present
  exit 1
fi

if [[ ! -f "$INSTALL_DIR/BAKLOG" ]]; then
  restored=false
  if restore_install_from_backup "$INSTALL_DIR" "$BACKUP_DIR"; then
    restored=true
  fi
  write_apply_result false "Updated bundle missing BAKLOG server" "$VERSION" "$restored"
  start_app_if_present
  exit 1
fi

if [[ ! -f "$INSTALL_DIR/BAKLOG Tray" ]]; then
  if is_linux; then
    write_apply_log "no tray binary in bundle (linux MVP)"
  else
    restored=false
    if restore_install_from_backup "$INSTALL_DIR" "$BACKUP_DIR"; then
      restored=true
    fi
    write_apply_result false "Updated bundle missing tray launcher" "$VERSION" "$restored"
    start_app_if_present
    exit 1
  fi
fi

chmod +x "$INSTALL_DIR/BAKLOG" 2>/dev/null || true
chmod +x "$INSTALL_DIR/BAKLOG Tray" 2>/dev/null || true
remove_old_backups "$INSTALL_PARENT" "$BACKUP_DIR"
write_apply_result true "" "$VERSION" false
# Drop ready package so the relaunched app does not rehydrate Install & restart.
VERSION_DIR="$UPDATE_ROOT/$VERSION"
if [[ -d "$VERSION_DIR" ]]; then
  rm -f "$VERSION_DIR/ready.json" "$VERSION_DIR/package.zip" "$VERSION_DIR/apply-manifest.json"
  rmdir "$VERSION_DIR" 2>/dev/null || true
fi

write_apply_log "starting app after apply"
start_app_if_present

exit 0
