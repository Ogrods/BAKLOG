@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo BAKLOG uninstall helper
echo.
echo  [Y] Keep library data (remove app autostart only)
echo  [N] Remove everything, including library data and saved sign-ins
echo.
choice /C YN /M "Choose"
if errorlevel 2 goto wipe
goto keep

:keep
set "ARGS=--uninstall-cleanup"
goto run

:wipe
set "ARGS=--uninstall-wipe-user-data"
goto run

:run
if not exist "BAKLOG Tray.exe" (
  echo BAKLOG Tray.exe was not found in this folder.
  pause
  exit /b 1
)
"BAKLOG Tray.exe" %ARGS%
echo.
echo Cleanup finished. You may delete this install folder now.
pause
