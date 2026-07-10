# -*- coding: utf-8 -*-
"""olta.re.kr 공무원마당 게시판 수집기 (질의응답 / 지방세상담 / 자유게시판).

- 목록을 페이지 순회하며 글을 찾고, 각 글의 상세(본문+답변)를 받아
  data/olta_qa.db (SQLite) 의 olta_qa 테이블에 저장한다. (board 컬럼으로 구분)
- 이미 받은 글(detail_fetched=1)은 건너뛴다 -> 중단 후 다시 실행하면 이어받기.
- --max-minutes 로 정해진 시간이 지나면 깔끔히 멈춘다(3시간씩 끊어 받기용).
- 세션이 만료되면(로그인 페이지로 튕김) 즉시 멈추고 안내한다.

사용 예:
    py -3.12 scraper\\olta_scraper.py --board qa --max-minutes 180   # 질의응답 3시간
    py -3.12 scraper\\olta_scraper.py --board consult --max-minutes 180
    py -3.12 scraper\\olta_scraper.py --board free                   # 자유게시판 전체
    py -3.12 scraper\\olta_scraper.py --board qa --limit 15          # 맛보기
"""
from __future__ import annotations
import argparse
import json
import random
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import olta_common as oc

# 콘솔 인코딩(cp949)에서 zero-width space 등으로 print 가 죽지 않도록 UTF-8 고정
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "olta_qa.db"


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db(con: sqlite3.Connection) -> None:
    # 동시 접근(진행상황 조회 등)에도 안전하게: WAL + 대기시간
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    cols = [r[1] for r in con.execute("PRAGMA table_info(olta_qa)").fetchall()]
    if cols and "board" not in cols:
        # 구버전(질의응답 전용, board 컬럼 없음) -> 새 스키마로 재생성
        con.execute("DROP TABLE olta_qa")
        con.commit()
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS olta_qa (
            board           TEXT NOT NULL,
            ntt_id          INTEGER NOT NULL,
            list_no         INTEGER,
            is_notice       INTEGER DEFAULT 0,
            category        TEXT,
            category_code   TEXT,
            title           TEXT,
            author          TEXT,
            created_at      TEXT,
            hits            INTEGER,
            comment_count   INTEGER,
            body_text       TEXT,
            body_html       TEXT,
            answers_json    TEXT,
            answer_count    INTEGER,
            law_links_json  TEXT DEFAULT '[]',
            detail_fetched  INTEGER DEFAULT 0,
            scraped_at      TEXT,
            PRIMARY KEY (board, ntt_id)
        )
        """
    )
    for col in ("attachments_json TEXT", "attach_text TEXT"):
        try:
            con.execute("ALTER TABLE olta_qa ADD COLUMN " + col)
        except sqlite3.OperationalError:
            pass
    con.commit()


def existing_done(con: sqlite3.Connection, board: str) -> set:
    return {r[0] for r in con.execute(
        "SELECT ntt_id FROM olta_qa WHERE board=? AND detail_fetched=1", (board,)).fetchall()}


def upsert_list_row(con: sqlite3.Connection, board: str, row: dict) -> None:
    con.execute(
        """
        INSERT INTO olta_qa(board, ntt_id, list_no, is_notice, category, category_code,
                            title, author, created_at, hits, comment_count, scraped_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(board, ntt_id) DO UPDATE SET
            list_no=excluded.list_no, category=excluded.category,
            category_code=excluded.category_code, title=excluded.title,
            author=excluded.author, created_at=excluded.created_at,
            hits=excluded.hits, comment_count=excluded.comment_count
        """,
        (board, row["nttId"], row["list_no"], 1 if row["is_notice"] else 0,
         row["category"], oc.CATEGORY_CODE.get(row["category"], ""),
         row["title"], row["author"], row["created_at"], row["hits"],
         row["comment_count"], now()),
    )


def save_detail(con: sqlite3.Connection, board: str, ntt: int, detail: dict, atts=None) -> None:
    answers = detail.get("answers", [])
    atts = atts or []
    attach_text = "\n\n".join(f"[{a['name']}]\n{a['text']}" for a in atts)
    con.execute(
        """
        UPDATE olta_qa SET
            title=COALESCE(NULLIF(?,''), title),
            category=COALESCE(NULLIF(?,''), category),
            author=COALESCE(NULLIF(?,''), author),
            created_at=COALESCE(NULLIF(?,''), created_at),
            body_text=?, body_html=?, answers_json=?, answer_count=?,
            attachments_json=?, attach_text=?,
            detail_fetched=1, scraped_at=?
        WHERE board=? AND ntt_id=?
        """,
        (detail.get("title", ""), detail.get("category", ""),
         detail.get("author", ""), detail.get("created_at", ""),
         detail.get("body_text", ""), detail.get("body_html", ""),
         json.dumps(answers, ensure_ascii=False), len(answers),
         json.dumps(atts, ensure_ascii=False), attach_text,
         now(), board, ntt),
    )


import threading


def _nap(base: float):
    """빠른 프로파일(속도 우선 + 최소한의 랜덤성으로 완전 기계적 패턴만 회피).
    0.5% 짧은 휴식(3~7s) · 5% 중간 휴지(1.0~2.5s) · 평소 base의 0.3~1.5배."""
    r = random.random()
    if r < 0.005:
        time.sleep(random.uniform(3.0, 7.0))
    elif r < 0.055:
        time.sleep(random.uniform(1.0, 2.5))
    else:
        time.sleep(max(0.0, base) * random.uniform(0.3, 1.5))


def _safe_get(s, url, params, tries=3, hard=15):
    """trickle-throttle(응답 찔끔 전송)까지 막는 하드(벽시계) 타임아웃 + 재시도.

    요청마다 '1회용 데몬 스레드'에서 실행하고 hard초 안에 안 끝나면 그 스레드를
    버린다(daemon이라 프로세스와 함께 소멸). 풀을 쓰지 않으므로 멈춘 요청이 쌓여도
    새 요청이 막히지 않는다(이전 ThreadPoolExecutor 고갈 버그 수정).
    """
    for k in range(tries):
        box = {}

        def _work():
            try:
                box["r"] = s.get(url, params=params, timeout=(8, 12))
            except Exception as ex:
                box["e"] = ex

        th = threading.Thread(target=_work, daemon=True)
        th.start()
        th.join(hard)
        if "r" in box:
            return box["r"]
        if "e" in box:
            print(f"    [retry {k+1}/{tries}] {type(box['e']).__name__}")
        else:
            print(f"    [hard-timeout {k+1}/{tries}] {hard}s 초과 -> 재시도(스레드 포기)")
        time.sleep(1.0 * (k + 1))
    return None


def fetch_list_page(s, cfg, page: int, pageunit: int):
    params = {
        "bbsId": cfg["bbsId"], "menuNo": cfg["menuNo"], "upperMenuId": cfg["upperMenuId"],
        "pageIndex": str(page), "pageUnit": str(pageunit),
        "searchCnd": "", "searchWrd": "", "sdate": "", "edate": "", "orderBy": "",
    }
    return _safe_get(s, oc.BASE + oc.LIST_PATH, params)


def fetch_detail_page(s, cfg, ntt: int):
    params = {
        "nttId": str(ntt), "bbsId": cfg["bbsId"],
        "menuNo": cfg["menuNo"], "upperMenuId": cfg["upperMenuId"], "pageIndex": "1",
    }
    return _safe_get(s, oc.BASE + oc.DETAIL_PATH, params)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", choices=list(oc.BOARDS.keys()), default="qa",
                    help="qa=질의응답 consult=지방세상담 free=자유게시판")
    ap.add_argument("--delay", type=float, default=0.5, help="요청 간 대기(초)")
    ap.add_argument("--pageunit", type=int, default=30, help="페이지당 글 수(최대 30)")
    ap.add_argument("--start-page", type=int, default=1)
    ap.add_argument("--max-pages", type=int, default=0, help="0=끝까지")
    ap.add_argument("--max-minutes", type=float, default=0, help="이 시간(분) 지나면 종료. 0=무제한")
    ap.add_argument("--limit", type=int, default=0, help="이번 실행 새로 받을 글 최대 수(0=무제한)")
    ap.add_argument("--refresh", action="store_true", help="이미 받은 글도 다시 받기")
    ap.add_argument("--no-attachments", action="store_true", help="HWP 첨부 텍스트 추출 끄기")
    args = ap.parse_args()

    cfg = oc.BOARDS[args.board]
    bbs_id = cfg["bbsId"]
    deadline = (time.monotonic() + args.max_minutes * 60) if args.max_minutes else None

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    done = set() if args.refresh else existing_done(con, args.board)
    print(f"[init] 게시판={args.board}({cfg['name']})  DB={DB_PATH}")
    print(f"[init] 이미 받은 글={len(done):,}건"
          + (f"  / 제한시간 {args.max_minutes:.0f}분" if deadline else ""))

    # 이어받기: 받은 글이 게시판 상단을 채우므로 프런티어 페이지부터 시작
    # (상단 수백 페이지 재방문 = 서버 throttle 유발 → 회피)
    if args.start_page == 1 and done and not args.refresh:
        fp = max(1, len(done) // args.pageunit - 3)
        if fp > 1:
            args.start_page = fp
            print(f"[resume] 프런티어 페이지 {fp}부터 시작(상단 {len(done):,}건 재방문 생략)")

    s = oc.make_session()

    r0 = fetch_list_page(s, cfg, args.start_page, args.pageunit)
    if r0 is None:
        print("[!] 목록 첫 요청 실패(네트워크/차단). 잠시 후 다시 실행하세요.")
        return 3
    if oc.is_login_redirect(r0):
        print("[!] 로그인 세션 만료/무효. cookie.txt 를 갱신하고 다시 실행하세요.")
        return 2
    total = oc.parse_total_count(r0.text)
    total_pages = ((total + args.pageunit - 1) // args.pageunit) if total else None
    print(f"[init] 게시판 총 {total:,}건" + (f" / 약 {total_pages:,}페이지" if total_pages else ""))

    new_count = 0
    page = args.start_page
    pages_done = 0
    first_html = r0.text
    stop_reason = "완료"

    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                stop_reason = f"제한시간({args.max_minutes:.0f}분) 도달"
                print(f"\n[time] {stop_reason} -> 종료")
                break
            if pages_done == 0:
                html = first_html
            else:
                resp = fetch_list_page(s, cfg, page, args.pageunit)
                if resp is None:
                    con.commit()
                    stop_reason = "목록 요청 실패(차단/네트워크)"
                    print(f"\n[!] page {page} 목록 요청 실패 -> 중단(이어받기 가능)")
                    break
                if oc.is_login_redirect(resp):
                    con.commit()
                    stop_reason = "세션 만료"
                    print(f"\n[!] 세션 만료(page {page}) -> 중단. cookie.txt 갱신 후 재실행")
                    break
                html = resp.text
            first_html = None
            rows = oc.parse_list(html, bbs_id=bbs_id)
            if not rows:
                stop_reason = "글 없음(마지막 페이지)"
                print(f"[page {page}] 글 없음 -> 종료")
                break

            for row in rows:
                ntt = row["nttId"]
                upsert_list_row(con, args.board, row)
                if ntt in done:
                    continue
                if deadline and time.monotonic() >= deadline:
                    con.commit()
                    stop_reason = f"제한시간({args.max_minutes:.0f}분) 도달"
                    print(f"\n[time] {stop_reason} -> 종료")
                    raise StopIteration
                rd = fetch_detail_page(s, cfg, ntt)
                if rd is None:
                    continue  # 상세 요청 실패 -> done 미추가, 다음 실행에 재시도
                if oc.is_login_redirect(rd):
                    con.commit()
                    print(f"\n[!] 세션 만료 감지(글 {ntt}). 지금까지 저장됨. "
                          f"cookie.txt 갱신 후 다시 실행하면 이어받습니다.")
                    return 2
                detail = oc.parse_detail(rd.text)
                # 첨부 추출은 본문이 HWP인 consult 게시판에서만 (qa/free는 생략 = 빠름)
                atts = (oc.fetch_attachments(s, rd.text)
                        if (not args.no_attachments and args.board == "consult") else [])
                save_detail(con, args.board, ntt, detail, atts)
                done.add(ntt)
                new_count += 1
                tag = "공지" if row["is_notice"] else (row["list_no"] or "?")
                cat = f"[{row['category']}] " if row["category"] else ""
                att = f" 첨부{len(atts)}" if atts else ""
                print(f"  + [{new_count}] ntt={ntt} ({tag}) {cat}{row['title'][:32]} "
                      f"/ 답변{len(detail.get('answers', []))}{att}")
                con.commit()
                if args.limit and new_count >= args.limit:
                    stop_reason = f"--limit {args.limit} 도달"
                    print(f"\n[done] {stop_reason}.")
                    raise StopIteration
                _nap(args.delay)

            con.commit()
            pages_done += 1
            page += 1
            saved = con.execute(
                "SELECT COUNT(*) FROM olta_qa WHERE board=? AND detail_fetched=1",
                (args.board,)).fetchone()[0]
            print(f"[page {page-1} 완료] 누적 신규 {new_count}건  (이 게시판 저장 총 {saved:,}건)")
            if args.max_pages and pages_done >= args.max_pages:
                stop_reason = f"--max-pages {args.max_pages} 도달"
                print(f"[done] {stop_reason}.")
                break
            if total_pages and page > total_pages:
                stop_reason = "마지막 페이지까지 완료"
                print("[done] 마지막 페이지까지 완료.")
                break
            _nap(args.delay)
    except StopIteration:
        pass
    except KeyboardInterrupt:
        con.commit()
        stop_reason = "사용자 중지"
        print("\n[중단] 사용자 중지. 지금까지 저장됨. 다시 실행하면 이어받습니다.")
    finally:
        con.commit()
        saved = con.execute(
            "SELECT COUNT(*) FROM olta_qa WHERE board=? AND detail_fetched=1",
            (args.board,)).fetchone()[0]
        remain = (total - saved) if total else None
        print(f"\n[요약] 사유={stop_reason} | 이번 신규 {new_count}건 | "
              f"{cfg['name']} 저장 {saved:,}건"
              + (f" / 남은 {remain:,}건" if remain is not None else "")
              + f"  -> {DB_PATH}")
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
