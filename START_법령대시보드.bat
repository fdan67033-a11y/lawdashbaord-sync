@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Law Dashboard Server - close this window to stop
set "OPENLAW_OC=sp-law-study"

echo ============================================================
echo   Law Dashboard      http://127.0.0.1:6155
echo   (Close this window to stop the server)
echo ============================================================
echo.

set "PYEXE="
py -3.12 --version >nul 2>nul && set "PYEXE=py -3.12"
if not defined PYEXE (
  py --version >nul 2>nul && set "PYEXE=py"
)
if not defined PYEXE (
  python --version >nul 2>nul && set "PYEXE=python"
)
if not defined PYEXE (
  echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org
  echo         Check "Add Python to PATH" during setup, then run this again.
  pause
  exit /b 1
)
echo Using interpreter: %PYEXE%
echo.

echo [1/2] Installing required packages ^(first run only, needs internet^)...
%PYEXE% -m pip install -q flask requests python-dotenv
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":6155" ^| findstr "LISTENING"') do taskkill /F /PID %%a >nul 2>nul

echo [2/2] Starting server... a Chrome tab will open shortly.
start "" chrome "http://127.0.0.1:6155/"
%PYEXE% run_server.py

echo.
echo Server stopped.
pause
endlocal
