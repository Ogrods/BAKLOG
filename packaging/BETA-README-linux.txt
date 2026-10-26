BAKLOG beta - quick start (Linux)
=================================

Experimental packaged zip (no tray icon, no .deb/AppImage installer). Prefer a
desktop session or GUI VM - store Connect needs a headed browser.

x86_64 only for now (glibc 2.35+, same baseline as Ubuntu 22.04).

1. Download BAKLOG-linux64.zip from GitHub Releases:
   https://github.com/Ogrods/BAKLOG/releases/latest
2. Unzip to a normal folder (not a temp extract). Some GUI unzippers strip
   execute bits - always re-run chmod after extract.
3. Run:
     chmod +x "BAKLOG/Start BAKLOG.sh" BAKLOG/BAKLOG BAKLOG/apply_update.sh
     ./BAKLOG/Start\ BAKLOG.sh
4. Your browser opens http://127.0.0.1:8765/ after the server is ready.
   Closing the terminal stops the server.
5. Open Connections and Connect each store.
   Prefer Google Chrome or Chromium installed as a normal package (not only Snap).
   If Chrome is missing, Connect can download a one-time browser (~150 MB).
   Override with BAKLOG_CHROME_PATH pointing at the Chrome *binary*, for example:
     export BAKLOG_CHROME_PATH=/opt/google/chrome/chrome
   Snap/Flatpak Chrome is skipped by default (set BAKLOG_ALLOW_SNAP_CHROME=1 to
   force it). In containers or hardened kernels you may need:
     export BAKLOG_CHROMIUM_NO_SANDBOX=1

Library data lives in ~/.local/share/baklog (or $XDG_DATA_HOME/baklog).
On Linux use GOG (web) and Amazon (Prime Gaming, web) - Galaxy local and
Amazon launcher DB are not available.

There is no Start-at-login toggle on Linux yet (that lives in the tray on
Windows/macOS). After an in-app Install & restart, the dashboard should reopen
in your browser; if not, run Start BAKLOG.sh again.

Your data stays on this PC. Nothing is uploaded to our servers.

If your build uses account sign-in, you will see a sign-in screen before the
dashboard. Create a free account on that screen, or sign in if you already
have one.

Bug reports: use the app menu (Report a bug...) or Discord #bug-reports.
Community: https://discord.gg/VFvxN5nCCB
