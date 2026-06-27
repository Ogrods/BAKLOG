BAKLOG beta — quick start (Windows)
===================================

Recommended: run BAKLOG-Setup.exe from your invite link.

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

Your library data (profiles, games, connections) is stored separately at
%LOCALAPPDATA%\BAKLOG-Data. In-place upgrades keep that folder. Uninstall
offers a choice: keep your library for a future reinstall, or remove everything
(including saved sign-ins and login autostart).

Portable zip fallback:
- Unzip to a normal folder (Desktop or Documents), not from the zip temp folder.
- Double-click Start BAKLOG.bat (launches the tray) or BAKLOG Tray.exe.
- For support, Start BAKLOG (server console).bat opens a visible server window.
- To keep all data in the unzip folder (thumb drive), add an empty portable.txt
  file beside BAKLOG.exe before first launch.

Quit BAKLOG from the tray icon (right-click, Quit). Do not close a console
window unless you launched the server-console shortcut.

Your data stays on this PC. Nothing is uploaded to our servers.

If your invite build uses account sign-in (Supabase), you will see a sign-in
screen before the dashboard. Create a free account on that screen, or sign in
if you already have one. Store Connect still requires Chrome or Edge.

Bug reports: use the app menu (Report a bug…) or Discord #bug-reports.
Version: see the About line in the app or BAKLOG-*.sha256 next to the zip.
