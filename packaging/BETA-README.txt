BAKLOG beta — quick start (Windows)
===================================

Recommended: run BAKLOG-v*-Setup.exe from your invite link.

1. If Windows SmartScreen warns "Unknown publisher":
   click More info, then Run anyway.
   (This build is not code-signed yet.)
2. Finish the installer. BAKLOG installs to your user folder
   (%LOCALAPPDATA%\BAKLOG) with a Start Menu shortcut.
3. Launch BAKLOG from the Start Menu (or the optional desktop shortcut).
   A tray icon appears. Your browser opens to http://127.0.0.1:8765/
4. Open the Connections tab and click Connect on each store you use.
   Sign-in requires Google Chrome or Microsoft Edge.
5. After connecting, fetcher chips import your libraries automatically.

Portable zip fallback:
- Unzip to a normal folder (Desktop or Documents), not from the zip temp folder.
- Double-click Start BAKLOG.bat (launches the tray) or BAKLOG Tray.exe.
- For support, Start BAKLOG (server console).bat opens a visible server window.

Quit BAKLOG from the tray icon (right-click, Quit). Do not close a console
window unless you launched the server-console shortcut.

Your data stays on this PC. Nothing is uploaded to our servers.

If your invite build uses account sign-in (Supabase), you will see a sign-in
screen before the dashboard. Store Connect still requires Chrome or Edge.

Bug reports: use the app menu (Report a bug…) or Discord #bug-reports.
Version: see the About line in the app or BAKLOG-*.sha256 next to the zip.
