@echo off
chcp 65001 >nul
cd /d "%~dp0study"
echo [기출 학습 대시보드] 서버 시작 (포트 6160)...
echo 브라우저에서 http://localhost:6160 이 열립니다. 창을 닫으면 종료됩니다.
start "" http://localhost:6160
py -m http.server 6160
pause
