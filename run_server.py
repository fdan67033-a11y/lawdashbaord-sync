# -*- coding: utf-8 -*-
"""콘솔에서 법령 대시보드 서버를 실행하는 시작 스크립트.
app_law_notes_v20.pyw 를 __main__ 으로 실행하여 로그가 콘솔에 보이도록 한다."""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
# API 인증키 안전망(런처/.env 가 없어도 동작)
os.environ.setdefault("OPENLAW_OC", "sp-law-study")

runpy.run_path(os.path.join(HERE, "app_law_notes_v20.pyw"), run_name="__main__")
