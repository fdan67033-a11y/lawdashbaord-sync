# -*- coding: utf-8 -*-
"""지방세법 2010 전부개정 매핑표 빌더 (1단계: 후보 자동 생성).

구 지방세법(전부개정 직전, MST=102490)의 각 조문을, 현행 4개 법
(지방세법/지방세기본법/지방세징수법/지방세특례제한법)의 조문들과
'조문제목 + 본문 유사도'로 매칭하여 상위 후보를 뽑는다.

산출물:
  samples/jeonbu_candidates.json  - 구조문별 상위 후보 + 점수 (사람/LLM 검토용)

이후 2단계에서 이 후보를 보고 최종 jeonbu_map.json 을 확정한다.
"""
from __future__ import annotations
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OC = "sp-law-study"
HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"
SAMPLES.mkdir(exist_ok=True)

OLD_TAXLAW_MST = "102490"   # 구 지방세법 (2010.3.31 전부개정 직전, 검증됨)
CURRENT_LAWS = ["지방세법", "지방세기본법", "지방세징수법", "지방세특례제한법"]

S = requests.Session()


def _strip(s: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s or ""))


def resolve_mst(name: str) -> str:
    r = S.get("https://www.law.go.kr/DRF/lawSearch.do",
              params={"OC": OC, "target": "law", "type": "JSON", "query": name, "display": "20"}, timeout=25)
    d = r.json()

    def find_list(o):
        if isinstance(o, dict):
            for v in o.values():
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    return v
                rr = find_list(v)
                if rr:
                    return rr
        return None
    for it in (find_list(d) or []):
        if str(it.get("법령명한글") or it.get("법령명") or "").strip() == name:
            return str(it.get("법령일련번호") or it.get("MST"))
    return ""


def fetch_articles(mst: str) -> list:
    """법령 본문에서 조문 단위 [{art, title, body}] 추출."""
    r = S.get("https://www.law.go.kr/DRF/lawService.do",
              params={"OC": OC, "target": "law", "MST": str(mst), "type": "JSON"}, timeout=40)
    d = r.json()

    def find_units(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "조문단위":
                    return v if isinstance(v, list) else [v]
                rr = find_units(v)
                if rr:
                    return rr
        elif isinstance(o, list):
            for x in o:
                rr = find_units(x)
                if rr:
                    return rr
        return None

    units = find_units(d) or []
    out = []
    for u in units:
        if not isinstance(u, dict):
            continue
        if str(u.get("조문여부") or "조문") != "조문":
            continue
        no = str(u.get("조문번호") or "").strip()
        if not no:
            continue
        branch = str(u.get("조문가지번호") or "").strip()
        art = f"제{no}조" + (f"의{branch}" if branch and branch != "0" else "")
        title = str(u.get("조문제목") or "").strip()
        # 본문: 조문단위 내 모든 문자열 수집
        chunks = []

        def walk(o):
            if isinstance(o, str):
                t = re.sub(r"<[^>]+>", "", o).strip()
                if t:
                    chunks.append(t)
            elif isinstance(o, dict):
                for kk, vv in o.items():
                    if kk in ("조문번호", "조문가지번호", "조문여부", "조문제목", "조문시행일자"):
                        continue
                    walk(vv)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(u)
        body = " ".join(chunks)
        out.append({"art": art, "title": title, "body": body[:2000]})
    return out


def ngrams(s: str, n: int = 3) -> set:
    s = _strip(s)
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def sim(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main():
    print("[1] 현행 법령 MST 확인")
    cur_mst = {}
    for name in CURRENT_LAWS:
        mst = resolve_mst(name)
        cur_mst[name] = mst
        print(f"    {name}: MST={mst}")
        time.sleep(0.2)

    print("[2] 조문 수집")
    old = fetch_articles(OLD_TAXLAW_MST)
    print(f"    구 지방세법: {len(old)}개 조문")
    pool = []  # (law, art, title, body, ngram_title, ngram_body)
    for name in CURRENT_LAWS:
        arts = fetch_articles(cur_mst[name])
        print(f"    현행 {name}: {len(arts)}개 조문")
        for a in arts:
            pool.append({
                "law": name, "art": a["art"], "title": a["title"], "body": a["body"],
                "nt": ngrams(a["title"], 3), "nb": ngrams(a["body"], 4),
            })
        time.sleep(0.2)

    print("[3] 후보 매칭")
    results = []
    for o in old:
        ot, ob = ngrams(o["title"], 3), ngrams(o["body"], 4)
        on = _strip(o["title"])
        scored = []
        for p in pool:
            ts = sim(ot, p["nt"])
            # 제목 완전일치(공백무시) 가산점
            if on and on == _strip(p["title"]):
                ts = max(ts, 0.95)
            bs = sim(ob, p["nb"])
            score = 0.55 * ts + 0.45 * bs
            if score > 0.12:
                scored.append((score, ts, bs, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        cands = [{
            "law": p["law"], "art": p["art"], "title": p["title"],
            "score": round(s, 3), "title_sim": round(ts, 3), "body_sim": round(bs, 3),
        } for s, ts, bs, p in scored[:4]]
        results.append({
            "old_art": o["art"], "old_title": o["title"],
            "old_body_head": o["body"][:120], "candidates": cands,
        })

    out = {
        "meta": {
            "old_law": "지방세법", "old_mst": OLD_TAXLAW_MST,
            "old_upto": "2010-05-05 (2010.3.31 전부개정 직전)",
            "current_mst": cur_mst, "old_article_count": len(old),
        },
        "rows": results,
    }
    path = SAMPLES / "jeonbu_candidates.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[완료] -> {path}  (구조문 {len(results)}건)")

    # 요약 통계
    strong = sum(1 for r in results if r["candidates"] and r["candidates"][0]["score"] >= 0.6)
    none = sum(1 for r in results if not r["candidates"])
    print(f"    1순위 점수>=0.6: {strong}건 / 후보없음: {none}건")


if __name__ == "__main__":
    main()
