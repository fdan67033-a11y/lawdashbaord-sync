# -*- coding: utf-8 -*-
"""세무사·법무사 법령군 판례인덱스 일괄 빌더 (자율·throttle 내성).

각 그룹에 대해:
  1) enumerate_precedents  — 판례 목록 적재(멱등, 빈응답 재시도 내장)
  2) process_pending 루프  — 대법원 출처 우선 처리. throttle로 멈추면 일시정지 후 재개.
     진전 없는 라운드가 연속 N회면 해당 그룹 보류하고 다음으로(무한루프 방지).

멱등 — 끊겨도 다시 실행하면 미처리분부터 이어받는다.
사용:
  py -3.12 scraper\\build_all.py                      # 기본: 작은 군 -> 큰 군 순서
  py -3.12 scraper\\build_all.py civil criminal       # 특정 군만
  py -3.12 scraper\\build_all.py --all-sources civil  # 대법원 외 출처까지 처리
"""
from __future__ import annotations
import sqlite3
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_prec_index as bp

# 기본 처리 순서: 작은 군 -> 큰 군(민법/형사 거대)
DEFAULT_ORDER = ["constitution", "admin", "registration", "commercial",
                 "nationaltax", "criminal", "civil"]

CHUNK_MINUTES = 20      # process 한 청크 시간
DELAY = 0.4            # 상세요청 간격
PAUSE_THROTTLE = 180   # 진전없음(throttle 추정) 시 대기
PAUSE_OK = 30         # 정상 청크 후 짧은 휴식
MAX_STAGNANT = 4       # 연속 무진전 라운드 허용치 -> 초과 시 군 보류


def now():
    return time.strftime("%H:%M:%S")


def count(con, group, sources):
    q = 'SELECT COUNT(*) FROM precedent WHERE "group"=? AND processed=0'
    p = [group]
    if sources:
        q += " AND source IN (%s)" % ",".join("?" * len(sources))
        p += sources
    pend = con.execute(q, p).fetchone()[0]
    done = con.execute(
        'SELECT COUNT(*) FROM precedent WHERE "group"=? AND processed=1', (group,)).fetchone()[0]
    return pend, done


def run_group(con, group, all_sources):
    cfg = bp.LAW_GROUPS[group]
    maps = bp.load_maps(cfg)
    sources = None if all_sources else ["대법원"]
    label = cfg["label"]
    print(f"\n========== [{now()}] 군={group}({label}) sources={sources or '전체'} ==========", flush=True)

    # 1) 적재(멱등). enumerate 자체가 빈응답 재시도 내장.
    try:
        bp.enumerate_precedents(con, group, cfg, 0, DELAY)
    except Exception as e:
        print(f"  [enumerate 예외] {e} — 처리 단계로 진행(이미 적재분 처리)", flush=True)

    # 2) 처리 루프
    stagn = 0
    while True:
        pend, done = count(con, group, sources)
        print(f"  [{now()}] {group}: 미처리 {pend} / 처리완료 {done} (stagn={stagn})", flush=True)
        if pend == 0:
            print(f"  [완료] {group} 처리 끝.", flush=True)
            break
        before = done
        try:
            bp.process_pending(con, group, cfg, maps, CHUNK_MINUTES, DELAY, sources)
        except Exception as e:
            print(f"  [process 예외] {e}", flush=True)
        _, after = count(con, group, sources)
        if after <= before:
            stagn += 1
            if stagn >= MAX_STAGNANT:
                print(f"  [보류] {group}: 연속 {stagn}회 무진전(throttle/영구실패 추정). 다음 군으로.", flush=True)
                break
            print(f"  [대기] 무진전 -> {PAUSE_THROTTLE}s 후 재개", flush=True)
            time.sleep(PAUSE_THROTTLE)
        else:
            stagn = 0
            time.sleep(PAUSE_OK)


def main():
    argv = [a for a in sys.argv[1:]]
    all_sources = False
    if "--all-sources" in argv:
        all_sources = True
        argv.remove("--all-sources")
    groups = argv or DEFAULT_ORDER
    bad = [g for g in groups if g not in bp.LAW_GROUPS]
    if bad:
        print("알 수 없는 군:", bad, "| 사용가능:", list(bp.LAW_GROUPS)); sys.exit(1)

    con = sqlite3.connect(bp.DB_PATH)
    bp.init_db(con)
    print(f"[build_all] 시작 {now()} | 순서: {groups} | OC={bp.OC}", flush=True)
    for g in groups:
        try:
            run_group(con, g, all_sources)
        except Exception as e:
            print(f"[군 예외] {g}: {e} — 다음 군 계속", flush=True)
    # 최종 요약
    print(f"\n[build_all] 전체 종료 {now()} — 요약:", flush=True)
    for g in groups:
        pend, done = count(con, g, None if all_sources else ["대법원"])
        links = con.execute(
            'SELECT COUNT(*) FROM article_prec ap JOIN precedent p ON ap.prec_id=p.prec_id WHERE p."group"=?',
            (g,)).fetchone()[0]
        print(f"  {g:13s}: 처리완료 {done:6d} | 미처리 {pend:6d} | 링크 {links:6d}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
