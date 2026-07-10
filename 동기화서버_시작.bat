@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 집 동기화 서버 (대시보드 + Cloudflare Tunnel)

echo ============================================================
echo   집 동기화 서버 시작
echo   - 대시보드(포트 6155) + Cloudflare Tunnel
echo   - 아래에 나오는 https://....trycloudflare.com 주소를
echo     회사컴 / 폰 브라우저에서 열면 같은 데이터로 동기화됩니다.
echo ============================================================
echo.

echo [1/2] 대시보드 서버 시작 (새 창)...
start "법제처 대시보드(6155)" cmd /c "py run_server.py"

echo      서버 기동 대기 (7초)...
timeout /t 7 >nul

echo.
echo [2/2] Cloudflare Tunnel 시작...
echo      ↓↓↓  이 아래에 뜨는 https 주소를 폰/회사컴에서 여세요  ↓↓↓
echo.
cloudflared tunnel --url http://localhost:6155

echo.
echo (터널이 종료되었습니다. 대시보드 창은 따로 닫아주세요.)
pause
