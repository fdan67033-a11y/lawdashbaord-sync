# -*- coding: utf-8 -*-
"""판례 연결기 (확장형): 법령군별 판례 참조조문 -> 현행 조문 인덱스.

확장 구조:
  LAW_GROUPS 에 '법령군'을 추가하면 다른 분야(예: 국세)로 확장된다.
  각 군은 {대상 현행법 목록, 전부개정 매핑표(파일), cutoff 날짜}로 정의된다.

처리:
  1) enumerate: 군의 각 법을 본문검색으로 페이지네이션하며 판례 목록을 모아
     precedent 테이블에 processed=0 으로 적재(중복무시) — 이어받기 기준
  2) process : processed=0 인 판례 상세를 받아 참조조문 파싱 -> (날짜인식) 해소
     -> article_prec 직접 링크 저장 -> processed=1
  --max-minutes 로 끊어 받고, 다시 실행하면 남은 것부터 이어받는다.

사용:
  py -3.12 scraper\\build_prec_index.py --group localtax --enumerate
  py -3.12 scraper\\build_prec_index.py --group localtax --max-minutes 180
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_jeonbu_map_v2 as bj  # fetch_articles, resolve_mst

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _load_oc() -> str:
    """OC 인증키: 환경변수 OPENLAW_OC > .env > 데모키 순."""
    v = os.environ.get("OPENLAW_OC")
    if v:
        return v.strip()
    envp = ROOT / ".env"
    if envp.exists():
        for line in envp.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENLAW_OC"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "sp-law-study"


OC = _load_oc()
DB_PATH = ROOT / "data" / "prec_index.db"
S = requests.Session()

# ===== 확장 지점: 법령군 정의 =====
LAW_GROUPS = {
    "localtax": {
        "label": "지방세",
        "laws": ["지방세법", "지방세기본법", "지방세징수법", "지방세특례제한법"],
        # 전부개정 매핑표: 구 법명 -> {cutoff(YYYYMMDD), 매핑파일}
        "mappings": {
            "지방세법": {"cutoff": "20110101", "file": "jeonbu_map.json"},
        },
    },
    # ── 세무사 시험 범위 ────────────────────────────────
    "nationaltax": {
        "label": "국세",
        "laws": [
            "국세기본법", "국세징수법", "조세범 처벌법",
            "소득세법", "법인세법", "부가가치세법",
            "상속세 및 증여세법", "종합부동산세법",
            "조세특례제한법", "국제조세조정에 관한 법률",
        ],
        "mappings": {},
    },
    "admin": {
        "label": "행정",
        "laws": ["행정소송법", "행정기본법", "행정심판법"],
        "mappings": {},
    },
    # ── 세무사·법무사 공통(상사) ────────────────────────
    "commercial": {
        "label": "상사",
        "laws": ["상법"],
        "mappings": {},
    },
    # ── 법무사 시험 범위 ────────────────────────────────
    "constitution": {
        "label": "헌법",
        "laws": ["대한민국헌법"],
        "mappings": {},
    },
    "civil": {
        "label": "민사",
        "laws": ["민법", "민사소송법", "민사집행법"],
        "mappings": {},
    },
    "criminal": {
        "label": "형사",
        "laws": ["형법", "형사소송법"],
        "mappings": {},
    },
    "registration": {
        "label": "등기·공탁·가족관계",
        "laws": [
            "부동산등기법", "상업등기법", "비송사건절차법",
            "공탁법", "가족관계의 등록 등에 관한 법률",
        ],
        "mappings": {},
    },
}

LAW_ANCHOR = re.compile(r"(구\s+)?([가-힣][가-힣·ㆍ]*법)(\s*시행령|\s*시행규칙)?\s*(\([^)]*\))?")
ART_RE = re.compile(r"제(\d+)조(?:의(\d+))?")
PARA_RE = re.compile(r"^\s*제(\d+)항")


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_maps(cfg) -> dict:
    """군의 매핑파일들을 {구법명: {old_art:[(law,art)]}} 로 로드."""
    maps = {}
    for old_law, m in cfg["mappings"].items():
        p = HERE / m["file"]
        table = {}
        if p.exists():
            d = json.load(open(p, encoding="utf-8"))
            for r in d.get("rows", []):
                if r.get("confidence") in ("high", "medium") and r.get("mapped"):
                    table[r["old_art"]] = [(x["law"], x["art"]) for x in r["mapped"]]
        maps[old_law] = table
    return maps


def parse_chamjo(text: str, target_laws: set):
    text = re.sub(r"<[^>]+>", " ", text or "")
    anchors = []
    for m in LAW_ANCHOR.finditer(text):
        law = (m.group(2) or "").strip()
        sub = (m.group(3) or "").strip()
        full = (law + " " + sub).strip() if sub else law
        paren = m.group(4) or ""
        is_old = bool(m.group(1)) or ("전의 것" in paren) or ("개정되기 전" in paren)
        dm = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", paren)
        old_date = f"{dm.group(1)}{int(dm.group(2)):02d}{int(dm.group(3)):02d}" if dm else None
        anchors.append((m.start(), m.end(), full, is_old, paren, old_date))
    refs = []
    for i, (s, e, full, is_old, paren, old_date) in enumerate(anchors):
        if full not in target_laws:
            continue
        nxt = anchors[i + 1][0] if i + 1 < len(anchors) else len(text)
        seg = text[e:nxt]
        for am in ART_RE.finditer(seg):
            art = "제" + am.group(1) + "조" + ("의" + am.group(2) if am.group(2) else "")
            pm = PARA_RE.match(seg[am.end():am.end() + 10])
            para = ("제" + pm.group(1) + "항") if pm else ""
            refs.append({"law": full, "art": art, "para": para, "is_old": is_old,
                         "paren": paren, "old_date": old_date})
    return refs


def resolve(ref, cfg, maps):
    """참조 -> [(law, art, confidence, via_old_art)] (날짜 인식 + 매핑표)."""
    if not ref["is_old"]:
        return [(ref["law"], ref["art"], "high", "")]
    mp = cfg["mappings"].get(ref["law"])
    if mp:
        pre = ("전부개정" in (ref.get("paren") or "")) or (ref.get("old_date") is None) \
            or (ref["old_date"] < mp["cutoff"])
        if pre and ref["art"] in maps.get(ref["law"], {}):
            return [(l, a, "high", ref["art"]) for (l, a) in maps[ref["law"]][ref["art"]]]
        conf = "high" if (ref.get("old_date") and ref["old_date"] >= mp["cutoff"]) else "medium"
        return [(ref["law"], ref["art"], conf, "")]
    # 매핑표 없는 법: 구판이면 같은 번호(일부개정 가정)
    return [(ref["law"], ref["art"], "medium", "")]


def init_db(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS precedent(
            prec_id TEXT PRIMARY KEY, "group" TEXT, case_name TEXT, case_no TEXT,
            court TEXT, decided TEXT, ptype TEXT, source TEXT, summary TEXT, link TEXT,
            processed INTEGER DEFAULT 0, has_chamjo INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS article_prec(
            law TEXT, art TEXT, prec_id TEXT, para TEXT, is_old INTEGER,
            via_old_art TEXT, confidence TEXT,
            PRIMARY KEY(law, art, prec_id, para));
        CREATE TABLE IF NOT EXISTS article_meta(
            law TEXT, art TEXT, semok TEXT, seq INTEGER, title TEXT,
            PRIMARY KEY(law, art));
        CREATE INDEX IF NOT EXISTS idx_ap ON article_prec(law, art);
        CREATE INDEX IF NOT EXISTS idx_pend ON precedent("group", processed);
        """
    )
    con.commit()


def find_list(o):
    if isinstance(o, dict):
        for v in o.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
            r = find_list(v)
            if r:
                return r
    return None


def _get(url, params, tries=3):
    for k in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            return r
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(1.0 + k)
    return None


def _safe_fetch_articles(name, tries=4):
    """resolve_mst + fetch_articles 를 재시도로 감싸 간헐적 비JSON/throttle 응답에 견딘다.
    반환 (mst, arts). 영구 실패 시 (mst, [])."""
    mst = ""
    for k in range(tries):
        try:
            if not mst:
                mst = bj.resolve_mst(name)
            if not mst:
                time.sleep(1.5 * (k + 1))
                continue
            arts = bj.fetch_articles(mst)
            if arts:
                return mst, arts
        except Exception:
            pass
        time.sleep(2.0 * (k + 1))  # throttle 회복 대기(지수 백오프)
    return mst, []


def build_article_meta(con, cfg):
    failed = []
    for name in cfg["laws"]:
        mst, arts = _safe_fetch_articles(name)
        if not arts:
            failed.append(name)
            tag = "MST없음(법령명 확인)" if not mst else "응답실패(재시도要)"
            print(f"    meta {name}: 0개  [! {tag}]")
            time.sleep(0.3)
            continue
        for i, a in enumerate(arts):
            con.execute("INSERT OR REPLACE INTO article_meta(law,art,semok,seq,title) VALUES(?,?,?,?,?)",
                        (name, a["art"], a["semok"], i, a["title"]))
        con.commit()
        print(f"    meta {name}: {len(arts)}개")
        time.sleep(0.3)
    if failed:
        print(f"    [!] 메타 실패 {len(failed)}건: {failed} — 재실행하면 이어서 채움")
    return failed


def enumerate_precedents(con, group, cfg, per_law_max, delay):
    print("[enumerate] 판례 목록 적재")
    total_new = 0
    for law in cfg["laws"]:
        page, got = 1, 0
        while True:
            # 빈/오류 응답은 throttle일 수 있으므로 백오프 재시도. 회복 후에도 비면 '끝'으로 간주.
            items = None
            for attempt in range(6):
                r = _get("https://www.law.go.kr/DRF/lawSearch.do",
                         {"OC": OC, "target": "prec", "type": "JSON", "query": law,
                          "search": "2", "display": "100", "page": str(page)})
                try:
                    items = find_list(r.json()) or []
                except Exception:
                    items = []
                if items:
                    break
                wait = min(10 + attempt * 15, 90)
                print(f"    {law} p{page}: 빈응답/throttle, {wait}s 후 재시도({attempt+1}/6)")
                time.sleep(wait)
            if not items:
                break
            for it in items:
                pid = str(it.get("판례일련번호") or "")
                if not pid:
                    continue
                cur = con.execute(
                    """INSERT OR IGNORE INTO precedent(prec_id,"group",case_name,case_no,court,
                       decided,ptype,source,processed) VALUES(?,?,?,?,?,?,?,?,0)""",
                    (pid, group, it.get("사건명", ""), it.get("사건번호", ""), it.get("법원명", ""),
                     str(it.get("선고일자", "")), it.get("판결유형", ""), it.get("데이터출처명", "")))
                total_new += cur.rowcount
                got += 1
            con.commit()
            print(f"    {law} p{page}: 누적 {got}")
            page += 1
            if per_law_max and got >= per_law_max:
                break
            time.sleep(delay)
    print(f"[enumerate] 신규 적재 {total_new}건")


def process_pending(con, group, cfg, maps, max_minutes, delay, sources=None):
    target = set(cfg["laws"])
    deadline = (time.monotonic() + max_minutes * 60) if max_minutes else None
    q = 'SELECT prec_id FROM precedent WHERE "group"=? AND processed=0'
    params = [group]
    if sources:
        q += " AND source IN (%s)" % ",".join("?" * len(sources))
        params += sources
    # 참조조문 수율이 높은 '대법원' 출처를 먼저 처리(쿼터 효율)
    q += " ORDER BY CASE source WHEN '대법원' THEN 0 WHEN '국세법령정보시스템' THEN 1 ELSE 2 END"
    pend = [r[0] for r in con.execute(q, params)]
    print(f"[process] 미처리 {len(pend)}건"
          + (f" (출처={','.join(sources)})" if sources else "")
          + (f" / 제한 {max_minutes:.0f}분" if deadline else ""))
    n = n_ch = n_link = 0
    fails = 0
    for pid in pend:
        if deadline and time.monotonic() >= deadline:
            print(f"[time] 제한시간 도달 -> 종료(이어받기 가능)")
            break
        try:
            r = _get("https://www.law.go.kr/DRF/lawService.do",
                     {"OC": OC, "target": "prec", "ID": pid, "type": "JSON"})
            svc = r.json().get("PrecService") or r.json()
        except Exception:
            svc = {}
        # 응답 실패(빈 본문/HTML 오류/한도)면 미처리로 남겨 다음 실행에 재시도
        if not isinstance(svc, dict) or not (svc.get("사건명") or svc.get("판례정보일련번호")):
            fails += 1
            if fails >= 15:
                con.commit()
                print(f"[!] 연속 응답 실패 {fails}회 — API 한도/차단 추정. 중단(이어받기 가능).")
                break
            time.sleep(1.0)
            continue
        fails = 0
        chamjo = svc.get("참조조문")
        summary = re.sub(r"<[^>]+>", " ", str(svc.get("판시사항") or ""))[:200]
        link = svc.get("판례상세링크") or ""
        has = 1 if chamjo else 0
        if chamjo:
            n_ch += 1
            done = set()
            for ref in parse_chamjo(str(chamjo), target):
                for (law, art, conf, via) in resolve(ref, cfg, maps):
                    key = (law, art, ref["para"])
                    if key in done:
                        continue
                    done.add(key)
                    con.execute("INSERT OR REPLACE INTO article_prec VALUES(?,?,?,?,?,?,?)",
                                (law, art, pid, ref["para"], 1 if ref["is_old"] else 0, via, conf))
                    n_link += 1
        con.execute("UPDATE precedent SET processed=1, has_chamjo=?, summary=?, link=? WHERE prec_id=?",
                    (has, summary, link, pid))
        n += 1
        if n % 50 == 0:
            con.commit()
            print(f"  ...{n}/{len(pend)} | 참조조문 {n_ch} | 링크 {n_link}")
        time.sleep(delay)
    con.commit()
    saved = con.execute(
        'SELECT COUNT(*) FROM precedent WHERE "group"=? AND processed=1', (group,)).fetchone()[0]
    print(f"[process] 이번 {n}건 처리(참조조문 {n_ch}) | 링크 +{n_link} | 누적 처리 {saved}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="localtax", choices=list(LAW_GROUPS.keys()))
    ap.add_argument("--enumerate", action="store_true", help="판례 목록 적재만")
    ap.add_argument("--per-law-max", type=int, default=0, help="법별 적재 상한(0=전체)")
    ap.add_argument("--max-minutes", type=float, default=0, help="처리 제한시간(분)")
    ap.add_argument("--delay", type=float, default=0.15)
    ap.add_argument("--skip-meta", action="store_true")
    ap.add_argument("--skip-enum", action="store_true", help="적재 건너뛰고 처리만")
    ap.add_argument("--oc", default="", help="법제처 OPEN API 인증키(미지정 시 .env/OPENLAW_OC 사용)")
    ap.add_argument("--sources", default="", help="처리할 출처 제한(쉼표). 예: 대법원")
    ap.add_argument("--court-only", action="store_true", help="대법원 출처만 처리(배치/스케줄용)")
    args = ap.parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or None
    if args.court_only:
        sources = ["대법원"]

    global OC
    if args.oc:
        OC = args.oc.strip()
    print(f"[init] OC키={'(본인키) ' if OC != 'sp-law-study' else '(데모키) '}{OC}")

    cfg = LAW_GROUPS[args.group]
    maps = load_maps(cfg)
    print(f"[init] 군={args.group}({cfg['label']}) | 대상법 {cfg['laws']}")
    print(f"[init] 매핑표 로드: " + ", ".join(f"{k}:{len(v)}건" for k, v in maps.items()))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)

    if not args.skip_meta:
        print("[meta] 현행 조문 메타 수집")
        build_article_meta(con, cfg)
    if not args.skip_enum:
        enumerate_precedents(con, args.group, cfg, args.per_law_max, args.delay)
    if not args.enumerate:
        process_pending(con, args.group, cfg, maps, args.max_minutes, args.delay, sources)
    con.close()


if __name__ == "__main__":
    main()
