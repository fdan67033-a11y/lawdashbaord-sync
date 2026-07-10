# -*- coding: utf-8 -*-
"""olta 보드 순회 러너 (단일 프로세스).

bash 체인(`A ; B`)은 중간 프로세스를 죽이면 다음 명령이 새로 떠서 중복 실행→DB 잠금이
발생한다. 이 래퍼는 한 파이썬 프로세스 안에서 보드를 순서대로 돌리므로,
프로세스 하나만 죽이면 전체가 깔끔히 멈춘다.

사용: py -3.12 -u scraper\\run_olta.py qa,consult 0.25
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import olta_scraper as o

boards = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["qa", "consult"])
delay = (sys.argv[2] if len(sys.argv) > 2 else "0.25")

for b in [x.strip() for x in boards if x.strip()]:
    print(f"\n######## BOARD {b} (delay {delay}) ########", flush=True)
    sys.argv = ["olta_scraper.py", "--board", b, "--delay", delay]
    try:
        rc = o.main()
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else 0
    print(f"[{b}] 종료코드 {rc}", flush=True)
    if rc == 2:
        print("세션 만료 감지 — 전체 중단(쿠키 갱신 후 다시 실행).", flush=True)
        break
print("\n[run_olta] 끝.", flush=True)
