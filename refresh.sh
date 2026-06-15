#!/usr/bin/env bash
# POSIX (macOS / Linux) counterpart to refresh.ps1 — runs the fetch sequence in
# order and tees output to refresh.log. The Windows launcher DB path is omitted
# here; run fetchers/fetch_amazon.py --source web manually after connecting Prime Gaming
# (web) on Connections if you use Amazon on macOS/Linux.
set -uo pipefail

cd "$(dirname "$0")"
export PYTHONPATH="$(pwd)"
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

run fetchers/fetch_games.py
run fetchers/fetch_gog.py
run fetchers/fetch_psn.py
run fetchers/fetch_epic.py
run fetchers/fetch_xbox.py --skip-hltb
run fetchers/fetch_battlenet.py --skip-hltb
run fetchers/fetch_ubisoft.py --skip-hltb
run fetchers/fetch_nintendo.py --skip-hltb
run fetchers/fetch_humble.py --skip-hltb
run fetchers/fetch_ea.py --skip-hltb
run fetchers/fetch_itch.py --only-new --skip-hltb
run enrichers/enrich_steam_reviews.py --stores itch
run fetchers/fetch_wishlist.py --skip-hltb
run fetchers/fetch_psn_wishlist.py
run fetchers/fetch_ubisoft_wishlist.py
run fetchers/fetch_nintendo_wishlist.py
run fetchers/fetch_humble_wishlist.py
run fetchers/fetch_itad.py
run fetchers/fetch_free_claims.py
run enrichers/enrich_cross_store_images.py
