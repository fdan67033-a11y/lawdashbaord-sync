# -*- coding: utf-8 -*-
"""지방세상담 ↔ 현행 조문 인덱스 (근거법령/답변 인용 → 조문 연결).

- olta_qa.db 의 consult 글(attach_text=신청서 HWP본문 + answers=답변)에서
  지방세 4법 및 그 시행령·시행규칙 조문 인용을 파싱
- 현행 인용은 그대로, 구 지방세법은 jeonbu_map(전부개정 매핑표)로 날짜인식 해소
- prec_index.db 에 저장:
    article_meta   : 법 + 시행령 + 시행규칙 조문 메타(시행령 정밀 연결용으로 확장)
    consult_post   : 상담글 메타(대시보드 표시용)
    article_consult: (현행) 조문 -> 상담글 직접 링크

판례 인덱스(article_prec)와 같은 prec_index.db 에 넣어 '관련 자료(판례+상담)' 통합.
"""
from __future__ import annotations
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_jeonbu_map_v2 as bj  # resolve_mst, fetch_articles

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREC_DB = ROOT / "data" / "prec_index.db"
OLTA_DB = ROOT / "data" / "olta_qa.db"

BASE_LAWS = ["지방세법", "지방세기본법", "지방세징수법", "지방세특례제한법"]
# 정밀 연결을 위해 시행령·시행규칙까지 메타 인덱싱
META_LAWS = BASE_LAWS + [f"{l} 시행령" for l in BASE_LAWS] + [f"{l} 시행규칙" for l in BASE_LAWS]
JEONBU_CUTOFF = "20110101"

# 법(+시행령/규칙) + 제N조(의M) + (제N항)
REF_RE = re.compile(
    r"(지방세법|지방세기본법|지방세징수법|지방세특례제한법)(\s*시행령|\s*시행규칙)?"
    r"\s*[^가-힣\n]{0,6}?제\s*(\d+)\s*조(?:의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?"
)


def norm_law(base: str, sub: str) -> str:
    sub = (sub or "").strip()
    return f"{base} {sub}" if sub else base


def parse_refs(text: str):
    out = []
    for m in REF_RE.finditer(text or ""):
        law = norm_law(m.group(1), m.group(2))
        art = "제" + m.group(3) + "조" + ("의" + m.group(4) if m.group(4) else "")
        para = ("제" + m.group(5) + "항") if m.group(5) else ""
        out.append({"law": law, "art": art, "para": para})
    return out


def load_jeonbu():
    p = HERE / "jeonbu_map.json"
    m = {}
    if p.exists():
        for r in json.load(open(p, encoding="utf-8")).get("rows", []):
            if r.get("confidence") in ("high", "medium") and r.get("mapped"):
                m[r["old_art"]] = [(x["law"], x["art"]) for x in r["mapped"]]
    return m


def resolve(ref, jeonbu):
    """현행 조문으로. 상담은 대체로 현행 인용이라 Tier1 직접."""
    # 상담 인용엔 '구 ...' 날짜표기가 드물다 → 기본 현행
    if ref["law"] == "지방세법" and ref["art"] in jeonbu:
        # 단, 명시적 구법 표기가 없으면 현행 그대로 두는 게 안전(상담은 최신)
        return [(ref["law"], ref["art"], "high")]
    return [(ref["law"], ref["art"], "high")]


def ensure_meta(con):
    have = {r[0] for r in con.execute("SELECT DISTINCT law FROM article_meta")}
    for name in META_LAWS:
        if name in have:
            continue
        mst = bj.resolve_mst(name)
        if not mst:
            print(f"    [meta] {name}: MST 못찾음(건너뜀)")
            continue
        arts = bj.fetch_articles(mst)
        for i, a in enumerate(arts):
            con.execute("INSERT OR REPLACE INTO article_meta(law,art,semok,seq,title) VALUES(?,?,?,?,?)",
                        (name, a["art"], a["semok"], i, a["title"]))
        print(f"    [meta] {name}: {len(arts)}개")
        time.sleep(0.15)
    con.commit()


def init_tables(con):
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS consult_post(
            ntt_id INTEGER PRIMARY KEY, list_no INTEGER, category TEXT, title TEXT,
            author TEXT, created_at TEXT, hits INTEGER, answer_count INTEGER,
            body_text TEXT, attach_text TEXT, answers_json TEXT);
        CREATE TABLE IF NOT EXISTS article_consult(
            law TEXT, art TEXT, ntt_id INTEGER, para TEXT, source TEXT, confidence TEXT,
            PRIMARY KEY(law, art, ntt_id, para));
        CREATE INDEX IF NOT EXISTS idx_ac ON article_consult(law, art);
        """
    )
    con.commit()


def main():
    jeonbu = load_jeonbu()
    con = sqlite3.connect(PREC_DB)
    init_tables(con)
    print("[1] 조문 메타(법+시행령+규칙) 확장")
    ensure_meta(con)

    print("[2] 상담글 읽기")
    o = sqlite3.connect(OLTA_DB)
    o.row_factory = sqlite3.Row
    rows = o.execute("SELECT * FROM olta_qa WHERE board='consult' AND detail_fetched=1").fetchall()
    print(f"    상담글 {len(rows)}건")

    n_link = n_post = 0
    con.execute("DELETE FROM article_consult")
    con.execute("DELETE FROM consult_post")
    for r in rows:
        con.execute("INSERT OR REPLACE INTO consult_post VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (r["ntt_id"], r["list_no"], r["category"], r["title"], r["author"],
                     r["created_at"], r["hits"], r["answer_count"],
                     (r["body_text"] or "")[:500], r["attach_text"], r["answers_json"]))
        n_post += 1
        # 근거: 첨부본문(근거법령/질의) + 답변
        src_text = {"att": r["attach_text"] or ""}
        ans = json.loads(r["answers_json"] or "[]")
        src_text["ans"] = " ".join(a.get("text", "") for a in ans)
        seen = set()
        for src, txt in src_text.items():
            for ref in parse_refs(txt):
                for (law, art, conf) in resolve(ref, jeonbu):
                    key = (law, art, ref["para"])
                    if key in seen:
                        continue
                    seen.add(key)
                    con.execute("INSERT OR REPLACE INTO article_consult VALUES(?,?,?,?,?,?)",
                                (law, art, r["ntt_id"], ref["para"], src, conf))
                    n_link += 1
        if n_post % 500 == 0:
            con.commit()
            print(f"    ...{n_post}/{len(rows)} | 링크 {n_link}")
    con.commit()
    posts_linked = con.execute("SELECT COUNT(DISTINCT ntt_id) FROM article_consult").fetchone()[0]
    arts_linked = con.execute("SELECT COUNT(DISTINCT law||art) FROM article_consult").fetchone()[0]
    print(f"[완료] 상담글 {n_post} | 링크 {n_link} | 연결된 상담 {posts_linked} | 연결된 조문 {arts_linked}")
    con.close()
    o.close()


if __name__ == "__main__":
    main()
