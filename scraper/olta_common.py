# -*- coding: utf-8 -*-
"""olta.re.kr 공무원마당 수집 공통 모듈: 쿠키/세션/파서."""
from __future__ import annotations
import io
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

try:
    import olefile
except ImportError:
    olefile = None

HERE = Path(__file__).resolve().parent
COOKIE_FILE = HERE / "cookie.txt"

BASE = "https://www.olta.re.kr"
LIST_PATH = "/cop/bbs/selectBoardList.do"
DETAIL_PATH = "/cop/bbs/selectBoardArticle.do"

# 공무원마당 하위 게시판들
BOARDS = {
    "qa":      {"bbsId": "BBSMSTR_000000000151", "menuNo": "21200100",
                "upperMenuId": "21200000", "name": "질의응답"},
    "consult": {"bbsId": "BBSMSTR_000000000181", "menuNo": "21300000",
                "upperMenuId": "21000000", "name": "지방세상담"},
    "free":    {"bbsId": "BBSMSTR_000000000211", "menuNo": "21900000",
                "upperMenuId": "21000000", "name": "자유게시판"},
}

# 하위호환(질의응답 기본값)
BBS_ID = BOARDS["qa"]["bbsId"]
MENU_NO = BOARDS["qa"]["menuNo"]
UPPER_MENU = BOARDS["qa"]["upperMenuId"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

LOGIN_MARK = "egovLoginUsr.do"

CATEGORY_CODE = {
    "취득세": "acquire", "등록면허세": "license", "지방소득세": "income",
    "주민세": "resident", "자동차세": "car", "재산세": "property",
    "지방세징수법": "defer", "지방세기본법": "investigate",
    "지방세특례제한법": "special", "세외수입": "nontax",
    "과세표준": "taxbase", "기타": "etc",
}


# ----------------------------- 쿠키 -----------------------------
def _extract_cookie(text: str) -> str:
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    real = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    for i, ln in enumerate(real):
        if ln.strip().lower() == "cookie" and i + 1 < len(real):
            return real[i + 1].strip()
    for ln in real:
        if ln.strip().lower().startswith("cookie:"):
            return ln.split(":", 1)[1].strip()
    cand = [ln.strip() for ln in real if "JSESSIONID=" in ln]
    if cand:
        return max(cand, key=len)
    cand = [ln.strip() for ln in real if "=" in ln and ";" in ln]
    if cand:
        return max(cand, key=len)
    if len(real) == 1:
        return real[0].strip()
    return ""


def load_cookie() -> str:
    if COOKIE_FILE.exists():
        c = _extract_cookie(COOKIE_FILE.read_text(encoding="utf-8"))
        if c:
            return c
    return os.environ.get("OLTA_COOKIE", "").strip()


def make_session():
    import requests
    c = load_cookie()
    if not c or "JSESSIONID=" not in c:
        raise SystemExit(
            "[!] 유효한 쿠키가 없습니다. scraper/cookie.txt 에 olta 로그인 Cookie 헤더를 넣으세요 "
            "(JSESSIONID 포함). DevTools Network 탭 -> 요청의 Request Headers -> Cookie 복사."
        )
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": BASE + LIST_PATH,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Cookie": c,
    })
    return s


def is_login_redirect(resp) -> bool:
    return LOGIN_MARK in (resp.url or "") or ("로그아웃" not in resp.text and "egovLoginUsr" in resp.text)


# ----------------------------- 파서 -----------------------------
def _txt(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _digits(s: str) -> Optional[int]:
    m = re.search(r"\d[\d,]*", s or "")
    return int(m.group(0).replace(",", "")) if m else None


def parse_total_count(html: str) -> Optional[int]:
    m = re.search(r"검색총건수\s*<span>\s*([\d,]+)\s*</span>", html)
    return int(m.group(1).replace(",", "")) if m else None


def parse_list(html: str, bbs_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """목록 페이지 한 장의 글 행들을 dict 리스트로 반환.

    게시판마다 컬럼 구성이 다르므로 thead 라벨을 읽어 인덱스를 매핑한다.
    (질의응답: 번호/카테고리/제목/답변/아이디/작성일/조회수,
     지방세상담: 번호/카테고리/제목/아이디/작성일/조회수,
     자유게시판: 번호/제목/아이디/작성일/파일/조회수)
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, Any]] = []
    table = soup.select_one("table.basic_table")
    if not table:
        return rows
    headers = [th.get_text(strip=True) for th in table.select("thead th")]

    def hidx(label: str) -> Optional[int]:
        return headers.index(label) if label in headers else None

    i_no, i_cat = hidx("번호"), hidx("카테고리")
    i_ans, i_id = hidx("답변"), hidx("아이디")
    i_date, i_hits = hidx("작성일"), hidx("조회수")

    body = table.find("tbody")
    if not body:
        return rows
    for tr in body.find_all("tr"):
        a = tr.select_one('a[href*="selectBoardArticle"]')
        if not a:
            continue
        href = a.get("href", "")
        m = re.search(r"nttId=(\d+)", href)
        if not m:
            continue
        if bbs_id and ("bbsId=" + bbs_id) not in href:
            continue
        tds = tr.find_all("td", recursive=False)

        def cell(i: Optional[int]) -> str:
            return _txt(tds[i]) if (i is not None and i < len(tds)) else ""

        is_notice = ("notice" in (tr.get("class") or [])) or bool(tr.select_one("span.notice"))
        comment_td = tr.select_one("td.comment")
        if comment_td is not None:
            comment_cnt = _digits(_txt(comment_td))
        elif i_ans is not None:
            comment_cnt = _digits(cell(i_ans))
        else:
            comment_cnt = None
        rows.append({
            "nttId": int(m.group(1)),
            "list_no": None if is_notice else _digits(cell(i_no)),
            "is_notice": is_notice,
            "category": cell(i_cat),
            "title": _txt(a),
            "author": cell(i_id),
            "created_at": cell(i_date),
            "hits": _digits(cell(i_hits)),
            "comment_count": comment_cnt,
        })
    return rows


def _view_hd_map(soup) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for dl in soup.select("dl.view_hd"):
        dt = dl.find("dt")
        dd = dl.find("dd")
        if dt and dd:
            out[_txt(dt)] = _txt(dd)
    return out


DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2})?")


def parse_detail(html: str) -> Dict[str, Any]:
    """상세 페이지에서 제목/메타/본문/답변을 추출."""
    soup = BeautifulSoup(html, "html.parser")
    title = _txt(soup.select_one(".view_tt"))
    hd = _view_hd_map(soup)
    # 작성자: dd.writer 안의 data-id 우선
    writer_a = soup.select_one("dd.writer a[data-id]")
    author = writer_a.get("data-id") if writer_a else hd.get("작성자", "")

    cont = soup.select_one(".view_cont")
    body_html = cont.decode_contents().strip() if cont else ""
    body_text = cont.get_text("\n", strip=True) if cont else ""

    answers: List[Dict[str, str]] = []
    for view in soup.select("div.rp_txt.re_view"):
        li = view.find_parent("li")
        a_author, a_dt = "", ""
        if li:
            name_p = li.select_one("p.name")
            if name_p:
                a_id = name_p.select_one("a[data-id]")
                a_author = a_id.get("data-id") if a_id else ""
                m = DATETIME_RE.search(name_p.get_text(" ", strip=True))
                a_dt = m.group(0) if m else ""
        inner = view.select_one("div[style*='pre-line']") or view
        # 첨부파일 표시줄(.rp_file)은 본문에서 제외
        for f in inner.select("p.rp_file"):
            f.extract()
        a_text = inner.get_text("\n", strip=True)
        if a_text or a_author:
            answers.append({"author": a_author, "datetime": a_dt, "text": a_text})

    return {
        "title": title,
        "category": hd.get("카테고리", ""),
        "author": author,
        "created_at": hd.get("작성일", ""),
        "body_html": body_html,
        "body_text": body_text,
        "answers": answers,
    }


# ----------------------------- 첨부(HWP/HWPX) -----------------------------
FILEDOWN_PATH = "/cmm/fms/FileDown.do"
DOWNFILE_RE = re.compile(r"fn_egov_downFile\('([^']+)'\s*,\s*'([^']*)'\)[^>]*>([^<]*)")
# 빈 상담신청서(서식) 식별용 시그니처 — 매 글에 붙는 동일 양식 제외용
_TEMPLATE_SIGS = ("◆ 신속하고 정확한 답변작성", "갑설/을설/병설", "질의자 성명><홍길동", "><○○광역시 ○○구청>")


def attachment_params(html: str) -> List[Tuple[str, str, str]]:
    out, seen = [], set()
    for m in DOWNFILE_RE.finditer(html or ""):
        fid, sn = m.group(1), m.group(2)
        if (fid, sn) in seen:
            continue
        seen.add((fid, sn))
        out.append((fid, sn, re.sub(r"\s+", " ", m.group(3) or "").strip()))
    return out


def _decode(b: bytes) -> str:
    for enc in ("utf-8", "utf-16-le", "cp949"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", "replace")


def extract_doc_text(b: bytes) -> str:
    """HWPX(zip)/HWP5(ole) 바이트에서 미리보기 텍스트 추출(디스크 미사용)."""
    if not b:
        return ""
    if b[:2] == b"PK":
        try:
            z = zipfile.ZipFile(io.BytesIO(b))
            if "Preview/PrvText.txt" in z.namelist():
                return _decode(z.read("Preview/PrvText.txt")).strip()
        except Exception:
            return ""
    if b[:4] == b"\xd0\xcf\x11\xe0" and olefile is not None:
        try:
            ole = olefile.OleFileIO(io.BytesIO(b))
            if ole.exists("PrvText"):
                return ole.openstream("PrvText").read().decode("utf-16-le", "replace").strip()
        except Exception:
            return ""
    return ""


def is_blank_template(text: str) -> bool:
    t = text or ""
    return any(sig in t for sig in _TEMPLATE_SIGS)


def fetch_attachments(session, html: str, skip_template: bool = True) -> List[Dict[str, str]]:
    """첨부를 메모리로 받아 텍스트만 추출. [{name, kind, text}] (디스크에 저장하지 않음)."""
    out = []
    for fid, sn, name in attachment_params(html):
        try:
            b = session.get(BASE + FILEDOWN_PATH,
                            params={"atchFileId": fid, "fileSn": sn}, timeout=40).content
        except Exception:
            continue
        kind = "hwpx" if b[:2] == b"PK" else ("hwp" if b[:4] == b"\xd0\xcf\x11\xe0" else "other")
        text = extract_doc_text(b)
        if skip_template and is_blank_template(text):
            continue
        if text:
            out.append({"name": name, "kind": kind, "text": text})
    return out
