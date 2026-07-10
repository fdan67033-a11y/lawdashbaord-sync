# -*- coding: utf-8 -*-
"""콘솔에서 법령 대시보드 서버를 실행하는 시작 스크립트.
app_law_notes_v20.pyw 를 __main__ 으로 실행하여 로그가 콘솔에 보이도록 한다."""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
# API 인증키(OC)는 app_law_notes_v20.pyw 가 .env 의 OPENLAW_OC 로 로드합니다.
# .env 가 없으면 화면 상단 OC 입력란에 직접 넣어도 됩니다.

runpy.run_path(os.path.join(HERE, "app_law_notes_v20.pyw"), run_name="__main__")
