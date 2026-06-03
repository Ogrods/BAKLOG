#!/usr/bin/env bash
# POSIX (macOS / Linux) counterpart to refresh.ps1 — runs the fetch sequence in
# order and tees output to refresh.log. Amazon Games is Windows-only (DPAPI
# launcher DB), so fetch_amazon.py is intentionally omitted here.
set -uo pipefail

cd "$(dirname "$0")"
log="./refresh.log"
: > "$log"

# Prefer the project venv interpreter when present.
if [ -x ".venv/bin/python" ]; then
  py=".venv/bin/python"
elif [ -x ".venv/bin/python3" ]; then
  py=".venv/bin/python3"
else
  py="python3"
fi

run() {
  echo "=== $* ===" | tee -a "$log"
  "$py" "$@" 2>&1 | tee -a "$log"
}

run fetch_games.py
run fetch_gog.py
run fetch_psn.py
run fetch_epic.py
run fetch_xbox.py --skip-hltb
run fetch_battlenet.py --skip-hltb
run fetch_ubisoft.py --skip-hltb
run fetch_nintendo.py --skip-hltb
run fetch_humble.py --skip-hltb
run fetch_itch.py --only-new --skip-hltb
run enrich_steam_reviews.py --stores itch
run fetch_wishlist.py --skip-hltb
run fetch_psn_wishlist.py
run fetch_ubisoft_wishlist.py
run fetch_nintendo_wishlist.py
run fetch_humble_wishlist.py
run fetch_itad.py
run enrich_cross_store_images.py
