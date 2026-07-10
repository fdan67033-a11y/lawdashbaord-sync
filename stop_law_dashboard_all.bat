@echo off
setlocal
cd /d "%~dp0"
echo [Law Dashboard Stop] Running PowerShell stop script...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_law_dashboard_all.ps1"
echo [Law Dashboard Stop] Finished.
endlocal
