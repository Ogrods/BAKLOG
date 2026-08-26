#!/usr/bin/env bash
# Build BAKLOG Linux onedir bundle with PyInstaller + zip + sha256 sidecar.
# Run from repo root. Requires: Python 3.11+, Node 22+, pip install pyinstaller.
#
# Release artifacts use STABLE filenames (same pattern as build_macos.sh):
#   BAKLOG-linux64.zip
#   BAKLOG-linux64.sha256
#
# Linux MVP: server binary + Start BAKLOG.sh (no tray icon).
#
# Usage:
#   ./packaging/build_linux.sh

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
"${PYTHON}" -m pip install pyinstaller secretstorage jeepney

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found - install Node.js 22+ before building the frozen bundle" >&2
  exit 1
fi

echo "Building production frontend (esbuild dist/)..."
npm ci
npm run vendor:supabase
npm run build
npm run check:dist-integrity

mkdir -p "${RELEASE_DIR}"

echo "Building BAKLOG (onedir, server only)..."
"${PYTHON}" -m PyInstaller packaging/baklog.spec --noconfirm --distpath "${RELEASE_DIR}" --workpath "${ROOT}/build/pyinstaller"

SERVER_BIN="${OUT_DIR}/BAKLOG"
if [[ ! -x "${SERVER_BIN}" ]]; then
  echo "Build failed: ${SERVER_BIN} not found" >&2
  exit 1
fi

FALLBACK_JSON="${OUT_DIR}/_internal/curated/free_claims.fallback.json"
if [[ ! -f "${FALLBACK_JSON}" ]]; then
  echo "Build failed: bundled curated feed missing at ${FALLBACK_JSON}" >&2
  exit 1
fi

cp -f "${ROOT}/packaging/BETA-README.txt" "${OUT_DIR}/BETA-README.txt"
cp -f "${ROOT}/packaging/apply_update.sh" "${OUT_DIR}/apply_update.sh"
chmod +x "${OUT_DIR}/apply_update.sh" "${SERVER_BIN}"

echo "Writing bundled account-auth .env..."
if [[ -z "${BAKLOG_SUPABASE_URL:-}" || -z "${BAKLOG_SUPABASE_ANON_KEY:-}" ]]; then
  echo "  Auth env: BAKLOG_SUPABASE_URL=${BAKLOG_SUPABASE_URL:+set}${BAKLOG_SUPABASE_URL:-MISSING}, BAKLOG_SUPABASE_ANON_KEY=${BAKLOG_SUPABASE_ANON_KEY:+set}${BAKLOG_SUPABASE_ANON_KEY:-MISSING}" >&2
fi
"${PYTHON}" "${ROOT}/scripts/write_bundle_auth_env.py" "${OUT_DIR}"

cat > "${OUT_DIR}/Start BAKLOG.sh" <<'EOF'
#!/usr/bin/env bash
cd "$(dirname "$0")"
xdg-open "http://127.0.0.1:8765" >/dev/null 2>&1 || true
exec "./BAKLOG"
EOF
chmod +x "${OUT_DIR}/Start BAKLOG.sh"

VERSION="0.0.0"
if [[ -f "${ROOT}/pyproject.toml" ]]; then
  VERSION="$(grep -E '^version\s*=' "${ROOT}/pyproject.toml" | head -1 | sed -E 's/.*"([^"]+)".*/\1/')"
fi

ZIP_NAME="BAKLOG-linux64.zip"
ZIP_PATH="${RELEASE_DIR}/${ZIP_NAME}"
rm -f "${ZIP_PATH}"
(
  cd "${RELEASE_DIR}"
  zip -r -q "${ZIP_NAME}" BAKLOG
)

if command -v sha256sum >/dev/null 2>&1; then
  HASH="$(sha256sum "${ZIP_PATH}" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  HASH="$(shasum -a 256 "${ZIP_PATH}" | awk '{print $1}')"
else
  echo "sha256sum or shasum required" >&2
  exit 1
fi
HASH_FILE="${RELEASE_DIR}/BAKLOG-linux64.sha256"
printf '%s  %s' "${HASH}" "${ZIP_NAME}" > "${HASH_FILE}"

echo ""
echo "Done (Linux experimental zip - Ubuntu 22.04 / glibc 2.35+ recommended)."
echo "  Folder:  ${OUT_DIR}"
echo "  Zip:     ${ZIP_PATH}"
echo "  SHA256:  ${HASH_FILE}"
echo "  Version: ${VERSION} (embedded in bundle; zip filename is stable)"
echo "Upload both zip + .sha256 after CI smokes pass (workflow_dispatch preview first)."
