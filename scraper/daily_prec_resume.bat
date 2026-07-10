@echo off
chcp 65001 >nul
cd /d "C:\todo_manual_dashboard\law_dashboard_work"
echo. >> "scraper\prec_resume.log"
echo ============ %date% %time% 판례 인덱스 이어받기 ============ >> "scraper\prec_resume.log"
py -3.12 -u scraper\build_prec_index.py --group localtax --skip-meta --skip-enum --court-only --max-minutes 180 >> "scraper\prec_resume.log" 2>&1
echo ---- end %date% %time% ---- >> "scraper\prec_resume.log"
