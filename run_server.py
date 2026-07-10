# -*- coding: utf-8 -*-
"""콘솔에서 법령 대시보드 서버를 실행하는 시작 스크립트.
app_law_notes_v20.pyw 를 __main__ 으로 실행하여 로그가 콘솔에 보이도록 한다."""
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
# API 인증키(OC)는 app_law_notes_v20.pyw 가 .env 의 OPENLAW_OC 로 로드합니다.
# .env 가 없으면 화면 상단 OC 입력란에 직접 넣어도 됩니다.

# ── 킬 때 동기화: auto 토글이 켜져 있으면 시작 시 pull, 종료 시 push ──
try:
    import atexit
    import sync_util
    if sync_util.load_config().get("auto"):
        print("[sync] 시작 동기화(pull)…", flush=True)
        print("  ->", sync_util.do_pull(), flush=True)

    def _sync_on_exit():
        try:
            if sync_util.load_config().get("auto"):
                print("[sync] 종료 동기화(push)…", flush=True)
                print("  ->", sync_util.do_push(), flush=True)
        except Exception as _e:
            print("[sync] 종료 push 실패:", _e, flush=True)
    atexit.register(_sync_on_exit)
except Exception as _e:
    print("[sync] 초기화 건너뜀:", _e, flush=True)

runpy.run_path(os.path.join(HERE, "app_law_notes_v20.pyw"), run_name="__main__")
