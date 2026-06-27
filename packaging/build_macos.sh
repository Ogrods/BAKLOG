#!/usr/bin/env bash
# macOS frozen build script (stub — not run as part of Phase 5).
# Mirrors packaging/build_windows.ps1: PyInstaller onedir + copy apply helper.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-$ROOT/release/BAKLOG}"

echo "BAKLOG macOS build is not automated in CI yet."
echo "When ready:"
echo "  1. pip install pyinstaller"
echo "  2. pyinstaller packaging/baklog.spec --distpath release --workpath build/pyinstaller"
echo "  3. cp packaging/apply_update.sh \"\$OUT_DIR/apply_update.sh\""
echo "  4. chmod +x \"\$OUT_DIR/apply_update.sh\""
echo "  5. zip release/BAKLOG -> BAKLOG-macos.zip + sha256 sidecar"
echo ""
echo "Target output dir: $OUT_DIR"

# cp "$ROOT/packaging/apply_update.sh" "$OUT_DIR/apply_update.sh"
# chmod +x "$OUT_DIR/apply_update.sh"
