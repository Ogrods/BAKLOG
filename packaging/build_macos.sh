#!/usr/bin/env bash
# macOS frozen build checklist (manual — not run in CI yet).
# Mirrors packaging/build_windows.ps1: frontend build → PyInstaller onedir → zip + sha256.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/release/BAKLOG}"

cat <<'EOF'
BAKLOG macOS frozen build — maintainer checklist
==============================================

Status: DEFERRED — GitHub Releases ship BAKLOG-win64.zip + Setup.exe only.
macOS installs use update-check notify + release-page link until BAKLOG-macos.zip exists.

Prerequisites
  - macOS 13+ on Apple Silicon or Intel (match CI smoke target)
  - Python 3.11+ venv with pip install -r requirements.txt
  - pip install pyinstaller
  - Node.js 22+ (npm run build for dist/index.html parity)

Build steps
  1. cd "$ROOT" && npm ci && npm run build
  2. pyinstaller packaging/baklog.spec --distpath release --workpath build/pyinstaller
  3. cp packaging/apply_update.sh "$OUT_DIR/apply_update.sh"
  4. chmod +x "$OUT_DIR/apply_update.sh"
  5. (Optional) codesign ad-hoc or Developer ID — unsigned builds match current Windows beta policy
  6. cd release && zip -r BAKLOG-macos.zip BAKLOG
  7. shasum -a 256 BAKLOG-macos.zip | tee BAKLOG-macos.sha256

Release wiring (after first successful artifact)
  - Upload BAKLOG-macos.zip + .sha256 to GitHub Release (same tag as Windows)
  - Confirm shared/update_release.py picks mac asset on darwin
  - Run scripts/frozen_bundle_smoke.py against the onedir bundle
  - Add release.yml macOS job or manual upload step (see ARCHITECTURE.md rough edges)

Verify locally
  - open release/BAKLOG/BAKLOG (or BAKLOG.app if spec bundles one)
  - GET http://127.0.0.1:8765/api/config → frozen: true, runtime_label: installed
  - apply_update.sh present beside server binary

EOF

echo "Target output dir: $OUT_DIR"
echo "(Build commands are commented out until CI/mac maintainer capacity exists.)"

# Uncomment when running manually:
# cp "$ROOT/packaging/apply_update.sh" "$OUT_DIR/apply_update.sh"
# chmod +x "$OUT_DIR/apply_update.sh"
