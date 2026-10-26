#!/usr/bin/env bash
# Launch the frozen Linux BAKLOG server and open the dashboard once ready.
# Closing this terminal stops the server (no tray on Linux MVP).
set -euo pipefail
cd "$(dirname "$0")"

# Let this script open the browser after the port is up (avoids a blank early
# tab and a second open from the frozen server).
export BAKLOG_NO_BROWSER=1

_wait_and_open() {
  local i
  for i in $(seq 1 60); do
    if command -v curl >/dev/null 2>&1; then
      if curl -sf "http://127.0.0.1:8765/api/config" >/dev/null 2>&1; then
        break
      fi
    elif (echo >/dev/tcp/127.0.0.1/8765) >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://127.0.0.1:8765/" >/dev/null 2>&1 || true
  fi
}

_wait_and_open &
exec "./BAKLOG"
