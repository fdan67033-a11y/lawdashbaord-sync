# -*- coding: utf-8 -*-
"""지방세법 2010 전부개정 매핑표 빌더 v2 (세목 문맥 + 큐레이션).

개선점: 각 조문에 소속 '장(세목)'을 태깅하여, '과세표준/세율/신고 및 납부'처럼
제목이 충돌하는 경우 같은 세목의 현행 조문으로 정확히 매칭한다.
구 세목명은 별칭으로 현행 세목에 정규화(등록세->등록면허세 등).

산출물: jeonbu_map.json  (덮어씀)
"""
from __future__ import annotations
import io
import json
import re
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
import os
OC = os.getenv("OPENLAW_OC", "")  # .env 또는 환경변수 OPENLAW_OC 로 설정
HERE = Path(__file__).resolve().parent
OLD_MST = "102490"
CURRENT_LAWS = ["지방세법", "지방세기본법", "지방세징수법", "지방세특례제한법"]
S = requests.Session()

# 구 세목 -> 현행 세목 별칭
SEMOK_ALIAS = {
    "등록세": "등록면허세", "면허세": "등록면허세",
    "도시계획세": "재산세", "공동시설세": "지역자원시설세", "지역개발세": "지역자원시설세",
    "사업소세": "주민세", "주행세": "자동차세",
    "경주·마권세": "레저세", "경주마권세": "레저세", "경주ㆍ마권세": "레저세",
    "농업소득세": "지방소득세", "도축세": "도축세",
}

# 세목 키워드(긴 것 먼저 매칭). 장/절 제목에 이 단어가 있으면 그 세목으로 태깅.
SEMOK_KEYWORDS = [
    "등록면허세", "등록세", "면허세", "취득세", "레저세", "경주ㆍ마권세", "경주·마권세",
    "지방소비세", "지방소득세", "주민세", "재산세", "자동차세", "주행세",
    "담배소비세", "지역자원시설세", "공동시설세", "지역개발세", "도시계획세",
    "사업소세", "지방교육세", "농업소득세", "도축세",
]

HDR_RE = re.compile(r"^\s*제\s*\d+\s*(장|절|관|편)(?:의\s*\d+)?\s*(.*)$")


def match_semok(title: str):
    for kw in SEMOK_KEYWORDS:
        if kw in title:
            return SEMOK_ALIAS.get(kw, kw)
    return None

# 큐레이션 보정(고신뢰)
CURATED = {
    "제105조": [("지방세법", "제7조", "납세의무자 등")],
    "제106조": [("지방세법", "제9조", "비과세")],
    "제111조": [("지방세법", "제10조", "과세표준")],
    "제112조": [("지방세법", "제11조", "부동산 취득의 세율"),
                ("지방세법", "제12조", "부동산 외 취득의 세율"),
                ("지방세법", "제13조", "과밀억제권역 등 취득 중과")],
    "제120조": [("지방세법", "제20조", "신고 및 납부")],
}


def _clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _strip(s: str) -> str:
    return re.sub(r"\s+", "", _clean(s))


def norm_semok(title: str) -> str:
    t = (title or "").strip()
    return SEMOK_ALIAS.get(t, t)


def _find_list(o):
    if isinstance(o, dict):
        for v in o.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
            rr = _find_list(v)
            if rr:
                return rr
    return None


# 검색 API로 해석 불가한 완고한 법령의 MST 직접 지정(법제처 색인 버그 우회).
# 예: '비송'으로 시작하는 쿼리는 n=0 반환하나 '사건절차'로는 정상 -> 직접 지정.
MST_OVERRIDE = {
    "비송사건절차법": "265395",
}


def resolve_mst(name: str) -> str:
    """법령명 -> MST. 법제처 검색 API quirk 보강:"""
    if name in MST_OVERRIDE:
        return MST_OVERRIDE[name]
    return _resolve_mst_search(name)


def _resolve_mst_search(name: str) -> str:
    """검색 기반 MST 해석.
    - display 부족(상위 20개 한계) -> display=100
    - 공백 포함 전체명 쿼리가 n=0 반환하는 버그(예 '조세범 처벌법') -> 접두어로 폭넓게 받아
      결과 내에서 공백무시 정확매칭. (예 query='조세범' 또는 '조세')"""
    key = name.replace(" ", "")
    # 쿼리 후보: 전체명 -> 첫 어절 -> 앞 2글자 (중복 제거, 순서 유지)
    cands = [name]
    if " " in name:
        cands.append(name.split()[0])
    if len(key) >= 2:
        cands.append(key[:2])
    seen = set()
    queries = [q for q in cands if not (q in seen or seen.add(q))]
    for q in queries:
        try:
            r = S.get("https://www.law.go.kr/DRF/lawSearch.do",
                      params={"OC": OC, "target": "law", "type": "JSON",
                              "query": q, "search": "1", "display": "100"}, timeout=25)
            items = _find_list(r.json()) or []
        except Exception:
            items = []
        for it in items:
            nm = str(it.get("법령명한글") or it.get("법령명") or "").strip()
            if nm.replace(" ", "") == key:
                return str(it.get("법령일련번호") or it.get("MST"))
    return ""


CHAP_RE = re.compile(r"제\s*\d+\s*장(?:의\s*\d+)?\s+(.+)")


def fetch_articles(mst: str) -> list:
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
    cur_chap = ""
    for u in units:
        if not isinstance(u, dict):
            continue
        if str(u.get("조문여부")) == "전문":
            m = HDR_RE.match(_clean(str(u.get("조문내용") or "")))
            if m:
                level, title = m.group(1), m.group(2).strip()
                kw = match_semok(title)
                if level in ("장", "편"):
                    cur_chap = kw if kw else ("총칙" if "총칙" in title else "")
                elif level == "절":
                    if kw:
                        cur_chap = kw
                # 관 단위는 세목을 바꾸지 않음
            continue
        no = str(u.get("조문번호") or "").strip()
        if not no:
            continue
        branch = str(u.get("조문가지번호") or "").strip()
        art = f"제{no}조" + (f"의{branch}" if branch and branch != "0" else "")
        title = _clean(str(u.get("조문제목") or ""))
        chunks = []

        def walk(o):
            if isinstance(o, str):
                t = _clean(o)
                if t:
                    chunks.append(t)
            elif isinstance(o, dict):
                for kk, vv in o.items():
                    if kk in ("조문번호", "조문가지번호", "조문여부", "조문제목",
                              "조문시행일자", "조문키", "조문변경여부", "조문이동이전", "조문이동이후"):
                        continue
                    walk(vv)
            elif isinstance(o, list):
                for x in o:
                    walk(x)
        walk(u)
        out.append({"art": art, "title": title, "body": " ".join(chunks)[:2000],
                    "semok": norm_semok(cur_chap)})
    return out


def ngrams(s, n):
    s = _strip(s)
    return {s[i:i + n] for i in range(len(s) - n + 1)} if len(s) >= n else ({s} if s else set())


def sim(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def main():
    print("[1] MST")
    cur_mst = {n: resolve_mst(n) for n in CURRENT_LAWS}
    for n, m in cur_mst.items():
        print("   ", n, m)
        time.sleep(0.15)

    print("[2] 조문 수집 + 세목 태깅")
    old = fetch_articles(OLD_MST)
    print("    구 지방세법:", len(old))
    pool = []
    for n in CURRENT_LAWS:
        arts = fetch_articles(cur_mst[n])
        print(f"    현행 {n}: {len(arts)}")
        for a in arts:
            a["law"] = n
            a["nt"] = ngrams(a["title"], 3)
            a["nb"] = ngrams(a["body"], 4)
            pool.append(a)
        time.sleep(0.15)

    print("[3] 매칭(세목 문맥)")
    rows = []
    stats = {"curated": 0, "auto": 0, "review": 0, "none": 0}
    for o in old:
        oa, ot = o["art"], o["title"]
        ont, onb, on, osemok = ngrams(ot, 3), ngrams(o["body"], 4), _strip(ot), o["semok"]

        if oa in CURATED:
            rows.append({"old_art": oa, "old_title": ot, "old_semok": osemok,
                         "mapped": [{"law": l, "art": a, "title": t} for l, a, t in CURATED[oa]],
                         "confidence": "high", "method": "curated", "candidates": []})
            stats["curated"] += 1
            continue

        scored = []
        for p in pool:
            ts = sim(ont, p["nt"])
            if on and on == _strip(p["title"]):
                ts = max(ts, 0.95)
            bs = sim(onb, p["nb"])
            sm = 1 if (osemok and p["semok"] and osemok == p["semok"]) else 0
            score = 0.45 * ts + 0.35 * bs + 0.20 * sm
            if ts >= 0.3 or bs >= 0.2:
                scored.append((score, ts, bs, sm, p))
        scored.sort(key=lambda x: x[0], reverse=True)

        if not scored:
            rows.append({"old_art": oa, "old_title": ot, "old_semok": osemok,
                         "mapped": [], "confidence": "none", "method": "none", "candidates": []})
            stats["none"] += 1
            continue

        exact = [x for x in scored if x[1] >= 0.95]
        exact_semok = [x for x in exact if x[3] == 1]

        def m1(x):
            return [{"law": x[4]["law"], "art": x[4]["art"], "title": x[4]["title"]}]

        if len(exact_semok) == 1:
            row = {"mapped": m1(exact_semok[0]), "confidence": "high", "method": "auto-semok"}
            stats["auto"] += 1
        elif len(exact) == 1:
            row = {"mapped": m1(exact[0]), "confidence": "high", "method": "auto"}
            stats["auto"] += 1
        elif exact_semok:
            row = {"mapped": [{"law": x[4]["law"], "art": x[4]["art"], "title": x[4]["title"]} for x in exact_semok],
                   "confidence": "high", "method": "auto-semok"}
            stats["auto"] += 1
        elif scored[0][1] >= 0.95:  # 제목일치 다수, 세목 불명 -> 검토
            row = {"mapped": [{"law": x[4]["law"], "art": x[4]["art"], "title": x[4]["title"]} for x in exact[:4]],
                   "confidence": "medium", "method": "review"}
            stats["review"] += 1
        elif scored[0][0] >= 0.5 and scored[0][3] == 1:
            row = {"mapped": m1(scored[0]), "confidence": "medium", "method": "auto-semok"}
            stats["auto"] += 1
        else:
            row = {"mapped": [{"law": x[4]["law"], "art": x[4]["art"], "title": x[4]["title"]} for x in scored[:3]],
                   "confidence": "low", "method": "review"}
            stats["review"] += 1

        row.update({"old_art": oa, "old_title": ot, "old_semok": osemok})
        if row["method"] == "review":
            row["candidates"] = [{"law": x[4]["law"], "art": x[4]["art"], "title": x[4]["title"],
                                  "semok": x[4]["semok"], "score": round(x[0], 3)} for x in scored[:5]]
        else:
            row["candidates"] = []
        rows.append(row)

    out = {"meta": {"old_law": "지방세법", "old_mst": OLD_MST,
                    "old_upto": "2010-05-05 (2010.3.31 전부개정 직전)",
                    "current_mst": cur_mst, "old_article_count": len(old),
                    "stats": stats,
                    "note": "v2: 세목(장) 문맥 매칭. confidence high=신뢰, medium/low=검토, none=현행대응없음."},
           "rows": rows}
    path = HERE / "jeonbu_map.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[완료]", path)
    print("통계:", stats, "| high =", stats["curated"] + stats["auto"])


if __name__ == "__main__":
    main()
