# -*- coding: utf-8 -*-
"""olta(질의응답+지방세상담) ↔ 현행 조문 통합 인덱스.

build_consult_index 를 일반화: 두 게시판(qa, consult)을 함께 인덱싱한다.
prec_index.db 에 저장:
    article_meta    : 법+시행령+시행규칙 조문 메타(있으면 유지)
    olta_post       : (board, ntt_id) 상담/질의 글 메타 + 본문/첨부/답변
    article_olta    : (현행) 조문 -> olta 글 직접 링크 (board 구분 컬럼 보유)

판례(article_prec)와 같은 DB라 조문 하나에 판례+질의+상담 통합 표시 가능.
qa+consult 를 '구분없이' 합쳐 보여주되, 필요시 board 로 구분도 가능.
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
import build_jeonbu_map_v2 as bj

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PREC_DB = ROOT / "data" / "prec_index.db"
OLTA_DB = ROOT / "data" / "olta_qa.db"

BASE_LAWS = ["지방세법", "지방세기본법", "지방세징수법", "지방세특례제한법"]
META_LAWS = BASE_LAWS + [f"{l} 시행령" for l in BASE_LAWS] + [f"{l} 시행규칙" for l in BASE_LAWS]
BOARDS = ["qa", "consult"]

REF_RE = re.compile(
    r"(지방세법|지방세기본법|지방세징수법|지방세특례제한법)(\s*시행령|\s*시행규칙)?"
    r"\s*[^가-힣\n]{0,6}?제\s*(\d+)\s*조(?:의\s*(\d+))?(?:\s*제\s*(\d+)\s*항)?"
)


def parse_refs(text: str):
    out = []
    for m in REF_RE.finditer(text or ""):
        sub = (m.group(2) or "").strip()
        law = f"{m.group(1)} {sub}" if sub else m.group(1)
        art = "제" + m.group(3) + "조" + ("의" + m.group(4) if m.group(4) else "")
        para = ("제" + m.group(5) + "항") if m.group(5) else ""
        out.append({"law": law, "art": art, "para": para})
    return out


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
        CREATE TABLE IF NOT EXISTS olta_post(
            board TEXT, ntt_id INTEGER, list_no INTEGER, category TEXT, title TEXT,
            author TEXT, created_at TEXT, hits INTEGER, answer_count INTEGER,
            body_text TEXT, attach_text TEXT, answers_json TEXT,
            PRIMARY KEY(board, ntt_id));
        CREATE TABLE IF NOT EXISTS article_olta(
            law TEXT, art TEXT, board TEXT, ntt_id INTEGER, para TEXT, source TEXT,
            PRIMARY KEY(law, art, board, ntt_id, para));
        CREATE INDEX IF NOT EXISTS idx_ao ON article_olta(law, art);
        """
    )
    con.commit()


def main():
    con = sqlite3.connect(PREC_DB)
    init_tables(con)
    print("[1] 조문 메타(법+시행령+규칙)")
    ensure_meta(con)

    o = sqlite3.connect(OLTA_DB)
    o.row_factory = sqlite3.Row
    con.execute("DELETE FROM article_olta")
    con.execute("DELETE FROM olta_post")
    grand_post = grand_link = 0
    for board in BOARDS:
        rows = o.execute("SELECT * FROM olta_qa WHERE board=? AND detail_fetched=1", (board,)).fetchall()
        print(f"[2] {board}: {len(rows)}글")
        n_link = 0
        for r in rows:
            con.execute("INSERT OR REPLACE INTO olta_post VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (board, r["ntt_id"], r["list_no"], r["category"], r["title"], r["author"],
                         r["created_at"], r["hits"], r["answer_count"],
                         (r["body_text"] or "")[:600],
                         (r["attach_text"] if "attach_text" in r.keys() else "") or "",
                         r["answers_json"]))
            grand_post += 1
            ans = json.loads(r["answers_json"] or "[]")
            srcs = {
                "att": (r["attach_text"] if "attach_text" in r.keys() else "") or "",
                "body": r["body_text"] or "",
                "ans": " ".join(a.get("text", "") for a in ans),
            }
            seen = set()
            for src, txt in srcs.items():
                for ref in parse_refs(txt):
                    key = (ref["law"], ref["art"], ref["para"])
                    if key in seen:
                        continue
                    seen.add(key)
                    con.execute("INSERT OR REPLACE INTO article_olta VALUES(?,?,?,?,?,?)",
                                (ref["law"], ref["art"], board, r["ntt_id"], ref["para"], src))
                    n_link += 1
            if grand_post % 1000 == 0:
                con.commit()
                print(f"    ...{grand_post} | 링크 {grand_link + n_link}")
        grand_link += n_link
        print(f"    {board} 링크 {n_link}")
    con.commit()
    posts = con.execute("SELECT COUNT(DISTINCT board||ntt_id) FROM article_olta").fetchone()[0]
    arts = con.execute("SELECT COUNT(DISTINCT law||art) FROM article_olta").fetchone()[0]
    print(f"[완료] 글 {grand_post} | 링크 {grand_link} | 연결된 글 {posts} | 연결된 조문 {arts}")
    con.close()
    o.close()


if __name__ == "__main__":
    main()
