@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [법제처 대시보드] 서버 시작 (포트 6155)...
echo 브라우저에서 http://localhost:6155 이 열립니다. 창을 닫으면 종료됩니다.
start "" http://localhost:6155
py run_server.py
pause
