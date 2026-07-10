# -*- coding: utf-8 -*-
"""인내형 조문메타 필러: LAW_GROUPS 중 article_meta에 없는 법령만 골라
OC키 throttle를 견디며(긴 백오프) 끝까지 채운다. 멱등 — 반복 실행 안전.

사용: py -3.12 scraper\\fill_meta.py
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
import build_prec_index as bp  # LAW_GROUPS, DB_PATH, _safe_fetch_articles
import build_jeonbu_map_v2 as bj


def existing_laws(con) -> set:
    return {r[0] for r in con.execute("SELECT DISTINCT law FROM article_meta")}


def all_target_laws() -> list:
    seen, out = set(), []
    for g, cfg in bp.LAW_GROUPS.items():
        for law in cfg["laws"]:
            if law not in seen:
                seen.add(law)
                out.append(law)
    return out


def fill_one(con, name, max_attempts=15) -> bool:
    for k in range(max_attempts):
        try:
            mst = bj.resolve_mst(name)
            arts = bj.fetch_articles(mst) if mst else []
        except Exception:
            mst, arts = "", []
        if arts:
            for i, a in enumerate(arts):
                con.execute(
                    "INSERT OR REPLACE INTO article_meta(law,art,semok,seq,title) VALUES(?,?,?,?,?)",
                    (name, a["art"], a["semok"], i, a["title"]))
            con.commit()
            print(f"  [OK] {name}: {len(arts)}개 (시도 {k+1})", flush=True)
            return True
        wait = min(15 + k * 15, 90)  # 15s -> 최대 90s 백오프(throttle 회복 대기)
        print(f"  [..] {name}: 빈응답/throttle, {wait}s 대기 후 재시도 ({k+1}/{max_attempts})", flush=True)
        time.sleep(wait)
    print(f"  [FAIL] {name}: {max_attempts}회 실패 — 다음 실행에 재시도", flush=True)
    return False


def main():
    # 시작 전 쿨다운(초): throttle 회복용. 인자로 조절. 예: py fill_meta.py 300
    cooldown = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    con = sqlite3.connect(bp.DB_PATH)
    bp.init_db(con)
    have = existing_laws(con)
    todo = [l for l in all_target_laws() if l not in have]
    print(f"[fill_meta] 전체 {len(all_target_laws())}법 중 누락 {len(todo)}법: {todo}", flush=True)
    if cooldown and todo:
        print(f"[fill_meta] throttle 회복 위해 {cooldown}s 쿨다운...", flush=True)
        time.sleep(cooldown)
    ok = 0
    for name in todo:
        if fill_one(con, name):
            ok += 1
        time.sleep(6)  # 법령 간 간격
    still = [l for l in all_target_laws() if l not in existing_laws(con)]
    print(f"[fill_meta] 완료: {ok}/{len(todo)} 채움 | 남은 누락 {len(still)}법: {still}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
