BAKLOG beta - quick start (Linux)
=================================

Experimental packaged build (no tray icon yet). Prefer a desktop session or
GUI VM - store Connect needs a headed browser.

1. Download BAKLOG-linux64.zip from GitHub Releases:
   https://github.com/Ogrods/BAKLOG/releases/latest
2. Unzip to a normal folder (not a temp extract).
3. Run:
     chmod +x "BAKLOG/Start BAKLOG.sh" BAKLOG/BAKLOG
     ./BAKLOG/Start\ BAKLOG.sh
4. Your browser opens http://127.0.0.1:8765/
   Closing the terminal stops the server.
5. Open Connections and Connect each store. Prefer Google Chrome or Chromium.
   If neither is installed, Connect can download a one-time browser (~150 MB).

Library data lives in ~/.local/share/baklog (or $XDG_DATA_HOME/baklog).
On Linux use GOG (web) and Amazon (Prime Gaming, web) - Galaxy local and
Amazon launcher DB are not available.

Needs a modern glibc (2.35+), same baseline as Ubuntu 22.04.

Your data stays on this PC. Nothing is uploaded to our servers.

If your build uses account sign-in, you will see a sign-in screen before the
dashboard. Create a free account on that screen, or sign in if you already
have one.

Bug reports: use the app menu (Report a bug...) or Discord #bug-reports.
Community: https://discord.gg/VFvxN5nCCB
