# -*- coding: utf-8 -*-
"""olta.re.kr 공무원마당 게시판 '구조 탐침' 스크립트.

목적: 본격 수집기를 만들기 전에 아래 3가지를 확인한다.
  1) Chrome 에 저장된 olta.re.kr 로그인 쿠키를 파이썬이 읽을 수 있는가
  2) 그 쿠키로 목록 페이지가 '로그인된 상태'로 열리는가 (로그인 페이지로 안 튕기는가)
  3) 목록/상세 HTML 의 실제 구조 (링크/파라미터 형식)

이 스크립트는 데이터를 저장하지 않는다. 샘플 HTML 몇 개만 samples/ 에 떨군다.
실행:  py scraper\probe_olta.py
"""
from __future__ import annotations
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples"
SAMPLES.mkdir(exist_ok=True)

# 스크린샷의 주소창에서 읽은 공무원마당 질의응답 게시판 주소.
# (틀리면 이 부분만 고치면 됩니다)
BASE = "https://www.olta.re.kr"
LIST_PATH = "/cop/bbs/selectBoardList.do"
LIST_PARAMS = {
    "bbsId": "BBSMSTR_000000000151",
    "menuNo": "21200100",
    "upperMenuId": "21200000",
    "pageIndex": "1",
    "searchCnd": "",
    "searchWrd": "",
    "sdate": "",
    "edate": "",
    "pageUnit": "10",
    "orderBy": "",
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


def line(c="-"):
    print(c * 70)


import os

COOKIE_FILE = HERE / "cookie.txt"


def _extract_cookie(text: str) -> str:
    """cookie.txt 내용에서 실제 Cookie 헤더 값만 뽑아낸다.

    허용 형식:
      - 순수 쿠키 한 줄:  JSESSIONID=...; _ga=...
      - 'Cookie: ...' 한 줄
      - DevTools '요청 헤더 복사' 덤프 (이름줄 다음줄에 값):
            cookie
            JSESSIONID=...; ...
    """
    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    real = [ln for ln in lines if ln.strip() and not ln.strip().startswith("#")]

    # 1) 'cookie' 단독 줄 다음 줄
    for i, ln in enumerate(real):
        if ln.strip().lower() == "cookie" and i + 1 < len(real):
            return real[i + 1].strip()
    # 2) 'Cookie:' 접두 줄
    for ln in real:
        if ln.strip().lower().startswith("cookie:"):
            return ln.split(":", 1)[1].strip()
    # 3) JSESSIONID 가 들어있는 줄 (가장 그럴듯)
    cand = [ln.strip() for ln in real if "JSESSIONID=" in ln]
    if cand:
        return max(cand, key=len)
    # 4) '=' 와 ';' 가 있는 가장 긴 줄
    cand = [ln.strip() for ln in real if "=" in ln and ";" in ln]
    if cand:
        return max(cand, key=len)
    # 5) 한 줄짜리면 그대로
    if len(real) == 1:
        return real[0].strip()
    return ""


def manual_cookie() -> str:
    """scraper/cookie.txt 또는 환경변수 OLTA_COOKIE 에서 쿠키 문자열을 읽는다."""
    if COOKIE_FILE.exists():
        txt = _extract_cookie(COOKIE_FILE.read_text(encoding="utf-8"))
        if txt:
            has_sess = "JSESSIONID=" in txt
            print(f"[cookie] cookie.txt 사용 ({len(txt)} chars, JSESSIONID {'있음' if has_sess else '없음!'})")
            return txt
    env = os.environ.get("OLTA_COOKIE", "").strip()
    if env:
        print(f"[cookie] 환경변수 OLTA_COOKIE 사용 ({len(env)} chars)")
        return env
    return ""


def load_cookies():
    """1순위: 수동 쿠키(cookie.txt/OLTA_COOKIE). 없으면 browser_cookie3 시도."""
    manual = manual_cookie()
    if manual:
        return ("header", manual)

    try:
        import browser_cookie3 as bc3
    except ImportError:
        print("[!] 수동 쿠키도 없고 browser_cookie3 도 미설치.")
        return (None, None)

    for name, fn in (("chrome", bc3.chrome), ("edge", bc3.edge)):
        try:
            cj = fn(domain_name="olta.re.kr")
            names = [c.name for c in cj]
            print(f"[cookie] {name}: {len(names)}개 -> {names}")
            if names:
                return ("jar", cj)
        except Exception as e:
            print(f"[cookie] {name} 읽기 실패: {e!r}")
    print("[!] 자동 쿠키 읽기 실패(Chrome ABE). scraper/cookie.txt 에 쿠키를 붙여넣으세요.")
    return (None, None)


def main():
    line("=")
    print("olta.re.kr 공무원마당 게시판 구조 탐침")
    line("=")

    kind, cookie = load_cookies()

    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        print(f"[!] 필수 패키지 미설치: {e}. 먼저 requirements_scraper.txt 설치하세요.")
        sys.exit(1)

    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": BASE + "/main.do",
        "Accept-Language": "ko-KR,ko;q=0.9",
    })
    if kind == "jar":
        s.cookies.update(cookie)
    elif kind == "header":
        s.headers["Cookie"] = cookie
    else:
        print("[!] 쿠키 없이 진행 -> 로그인 페이지가 떨어질 것임 (구조 확인용으로만 의미)")

    list_url = BASE + LIST_PATH
    line()
    print(f"[GET] {list_url}  params={LIST_PARAMS}")
    try:
        r = s.get(list_url, params=LIST_PARAMS, timeout=20)
    except Exception:
        print("[!] 요청 자체가 실패했습니다 (네트워크/보안SW 차단 가능):")
        traceback.print_exc()
        sys.exit(1)

    print(f"  status={r.status_code}  final_url={r.url}")
    print(f"  length={len(r.text):,} bytes")

    html = r.text
    (SAMPLES / "list_page1.html").write_text(html, encoding="utf-8")
    print(f"  -> 저장: {SAMPLES / 'list_page1.html'}")

    # 로그인 상태 진단
    logged_in = ("로그아웃" in html) or ("마이페이지" in html)
    login_form = ("로그인" in html and not logged_in) or ("/login" in r.url.lower()) or ("login.do" in r.url.lower())
    print(f"  로그인된 화면으로 보임? {'예' if logged_in else '아니오'}"
          f"   (로그인페이지로 튕김 추정? {'예' if login_form else '아니오'})")

    # 상세 링크 후보 추출
    soup = BeautifulSoup(html, "html.parser")
    print("\n[목록에서 발견한 상세글 링크 후보 (최대 8개)]")
    found = 0
    seen = set()
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        onclick = a.get("onclick") or ""
        blob = href + " || " + onclick
        if ("selectBoardArticle" in blob) or ("nttId" in blob) or ("fn_egov" in onclick):
            key = blob.strip()
            if key in seen:
                continue
            seen.add(key)
            text = a.get_text(strip=True)[:30]
            print(f"  - text={text!r}")
            print(f"      href={href!r}")
            print(f"      onclick={onclick!r}")
            found += 1
            if found >= 8:
                break
    if not found:
        print("  (selectBoardArticle/nttId 패턴을 못 찾음. list_page1.html 을 직접 봐야 함)")

    # 페이징 함수 흔적
    print("\n[페이징/스크립트 흔적]")
    for kw in ("fn_egov_select", "linkPage", "pageIndex", "selectBoardArticle", "totalCnt", "total"):
        print(f"  '{kw}' 등장 횟수: {html.count(kw)}")

    # nttId 후보 추출 (목록에서)
    import re
    ntt_ids = re.findall(r"nttId['\"]?\s*[=:,]?\s*['\"]?(\d{3,})", html)
    ntt_ids = list(dict.fromkeys(ntt_ids))
    print(f"\n[목록에서 추출한 nttId 후보] {ntt_ids[:15]}")

    # 상세 페이지 한 건 받아보기
    detail_id = ntt_ids[0] if ntt_ids else "73864"
    detail_url = BASE + "/cop/bbs/selectBoardArticle.do"
    detail_params = {
        "nttId": detail_id,
        "bbsId": "BBSMSTR_000000000151",
        "menuNo": "21200100",
        "upperMenuId": "21200000",
        "pageIndex": "1",
    }
    line()
    print(f"[GET 상세] nttId={detail_id}")
    try:
        rd = s.get(detail_url, params=detail_params, timeout=20)
        print(f"  status={rd.status_code} final_url={rd.url} length={len(rd.text):,}")
        (SAMPLES / f"detail_{detail_id}.html").write_text(rd.text, encoding="utf-8")
        print(f"  -> 저장: {SAMPLES / f'detail_{detail_id}.html'}")
        dlogged = ("로그아웃" in rd.text) or ("마이페이지" in rd.text)
        print(f"  상세도 로그인 상태? {'예' if dlogged else '아니오'}")
    except Exception:
        print("  [!] 상세 요청 실패:")
        traceback.print_exc()

    line("=")
    print("끝. 아래 파일을 Claude 에게 보여주면 본 수집기를 만들 수 있습니다:")
    print(f"  {SAMPLES / 'list_page1.html'}")
    line("=")


if __name__ == "__main__":
    main()
