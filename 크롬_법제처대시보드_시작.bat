@echo off
rem ============================================================
rem  Law Dashboard launcher (Chrome)
rem  - Starts the Flask server on port 6155 if it is not running
rem  - Waits until the port is ready, then opens Chrome
rem  NOTE: keep this file ASCII-only. cmd.exe misparses UTF-8
rem        Korean text and it breaks control flow.
rem ============================================================
cd /d "%~dp0"
title Law Dashboard Launcher

set "PF86=%ProgramFiles(x86)%"
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%PF86%\Google\Chrome\Application\chrome.exe" set "CHROME=%PF86%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

rem --- already running? then just open the browser ---
netstat -an | findstr /c:":6155" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 goto open

echo.
echo   Starting Law Dashboard server (port 6155)...
echo   The server window is minimized. Close it to stop the server.
echo.
start "Law Dashboard Server - close to stop" /min py run_server.py

set /a TRIES=0
:wait
ping -n 2 127.0.0.1 >nul
netstat -an | findstr /c:":6155" | findstr /i "LISTENING" >nul 2>&1
if not errorlevel 1 goto open
set /a TRIES+=1
if %TRIES% lss 30 goto wait

echo   Server did not come up within 60 seconds.
echo   Check the server window for errors.
pause
exit /b 1

:open
if defined CHROME goto chrome
echo   Chrome not found. Opening default browser instead.
start "" "http://localhost:6155"
exit /b 0

:chrome
start "" "%CHROME%" "http://localhost:6155"
exit /b 0
