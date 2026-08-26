#!/usr/bin/env bash
# Build BAKLOG macOS onedir bundle with PyInstaller + zip + sha256 sidecar.
# Run from repo root. Requires: Python 3.11+, Node 22+, pip install pyinstaller.
#
# Release artifacts use STABLE filenames (same pattern as build_windows.ps1):
#   BAKLOG-macos.zip
#   BAKLOG-macos.sha256
#
# Usage:
#   ./packaging/build_macos.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RELEASE_DIR="${ROOT}/release"
OUT_DIR="${RELEASE_DIR}/BAKLOG"

if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
else
  PYTHON="python3"
fi

echo "Installing Python dependencies..."
"${PYTHON}" -m pip install -r requirements.txt
"${PYTHON}" -m pip install pyinstaller

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found — install Node.js 22+ before building the frozen bundle" >&2
  exit 1
fi

echo "Building production frontend (esbuild dist/)..."
npm ci
npm run vendor:supabase
npm run build
npm run check:dist-integrity

mkdir -p "${RELEASE_DIR}"

echo "Building BAKLOG + BAKLOG Tray (onedir)..."
"${PYTHON}" -m PyInstaller packaging/baklog.spec --noconfirm --distpath "${RELEASE_DIR}" --workpath "${ROOT}/build/pyinstaller"

SERVER_BIN="${OUT_DIR}/BAKLOG"
TRAY_BIN="${OUT_DIR}/BAKLOG Tray"
if [[ ! -x "${SERVER_BIN}" ]]; then
  echo "Build failed: ${SERVER_BIN} not found" >&2
  exit 1
fi
if [[ ! -x "${TRAY_BIN}" ]]; then
  echo "Build failed: ${TRAY_BIN} not found" >&2
  exit 1
fi

FALLBACK_JSON="${OUT_DIR}/_internal/curated/free_claims.fallback.json"
if [[ ! -f "${FALLBACK_JSON}" ]]; then
  echo "Build failed: bundled curated feed missing at ${FALLBACK_JSON}" >&2
  exit 1
fi

# pyproject.toml must be at bundle root for frozen version detection: bundle_root()
# is the exe directory, while PyInstaller puts the packaged copy under _internal/.
cp -f "${ROOT}/pyproject.toml" "${OUT_DIR}/pyproject.toml"
cp -f "${ROOT}/packaging/BETA-README.txt" "${OUT_DIR}/BETA-README.txt"
cp -f "${ROOT}/packaging/apply_update.sh" "${OUT_DIR}/apply_update.sh"
chmod +x "${OUT_DIR}/apply_update.sh" "${SERVER_BIN}" "${TRAY_BIN}"

echo "Writing bundled account-auth .env..."
if [[ -z "${BAKLOG_SUPABASE_URL:-}" || -z "${BAKLOG_SUPABASE_ANON_KEY:-}" ]]; then
  echo "  Auth env: BAKLOG_SUPABASE_URL=${BAKLOG_SUPABASE_URL:+set}${BAKLOG_SUPABASE_URL:-MISSING}, BAKLOG_SUPABASE_ANON_KEY=${BAKLOG_SUPABASE_ANON_KEY:+set}${BAKLOG_SUPABASE_ANON_KEY:-MISSING}" >&2
fi
"${PYTHON}" "${ROOT}/scripts/write_bundle_auth_env.py" "${OUT_DIR}"

cat > "${OUT_DIR}/Start BAKLOG.command" <<'EOF'
#!/bin/bash
cd "$(dirname "$0")"
open -a "Google Chrome" "http://127.0.0.1:8765" 2>/dev/null || true
exec "./BAKLOG Tray"
EOF
chmod +x "${OUT_DIR}/Start BAKLOG.command"

VERSION="0.0.0"
if [[ -f "${ROOT}/pyproject.toml" ]]; then
  VERSION="$(grep -E '^version\s*=' "${ROOT}/pyproject.toml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

ZIP_NAME="BAKLOG-macos.zip"
ZIP_PATH="${RELEASE_DIR}/${ZIP_NAME}"
rm -f "${ZIP_PATH}"
(
  cd "${RELEASE_DIR}"
  zip -r -q "${ZIP_NAME}" BAKLOG
)

HASH="$(shasum -a 256 "${ZIP_PATH}" | awk '{print $1}')"
HASH_FILE="${RELEASE_DIR}/BAKLOG-macos.sha256"
printf '%s  %s' "${HASH}" "${ZIP_NAME}" > "${HASH_FILE}"

echo ""
echo "Done (macOS unsigned beta — Gatekeeper may prompt on first launch or after in-app update)."
echo "  Folder:  ${OUT_DIR}"
echo "  Zip:     ${ZIP_PATH}"
echo "  SHA256:  ${HASH_FILE}"
echo "  Version: ${VERSION} (embedded in bundle; zip filename is stable)"
echo "Upload both zip + .sha256 to the GitHub Release tag alongside Windows assets."
