# -*- coding: utf-8 -*-
"""기출문제 수집기 (공식 문제+정답만, 회차별 폴더, 멱등 이어받기).

대상:
  cpa   금융감독원 공인회계사 기출 (cpa.fss.or.kr) — 세법/상법 포함 전과목
  bupmu 합격의법학원 자료센터의 '법무사 시험 문제/확정정답' (대법원 공식 문제 미러)
  semu  큐넷 세무사 — 목록이 JS 로드라 별도(미구현, --semu 시 안내)

저장: data/exams/<source>/<회차_제목>/<파일>
사용:
  py -3.12 scraper\\exam_scraper.py --cpa
  py -3.12 scraper\\exam_scraper.py --bupmu
  py -3.12 scraper\\exam_scraper.py --cpa --bupmu --max 0   # 전체
"""
from __future__ import annotations
import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "exams"
H = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
S = requests.Session()
S.headers.update(H)


def sanitize(s: str, maxlen=120) -> str:
    s = re.sub(r"<[^>]+>", "", s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen].strip(" ._") or "untitled"


def fname_from_headers(resp, fallback) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd)
    if m:
        return sanitize(unquote(m.group(1)))
    return fallback


def download(url, folder: Path, fallback_name, delay=0.8, referer=None, prefer_name=False) -> str | None:
    folder.mkdir(parents=True, exist_ok=True)
    hdr = {"Referer": referer} if referer else {}
    try:
        with S.get(url, timeout=60, stream=True, headers=hdr) as r:
            if r.status_code != 200:
                print(f"      [skip {r.status_code}] {url[:80]}")
                return None
            # 차단/오류 페이지(외부링크 alert, WAF 등)는 text/html로 옴 -> 건너뜀
            ct = r.headers.get("Content-Type", "")
            if "text/html" in ct.lower():
                print(f"      [차단/비첨부 html] {fallback_name} ({ct[:30]})")
                return None
            name = fallback_name if prefer_name else fname_from_headers(r, fallback_name)
            dest = folder / name
            if dest.exists() and dest.stat().st_size > 0:
                print(f"      [있음] {name}")
                return name
            total = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk); total += len(chunk)
            print(f"      [받음] {name} ({total} bytes)")
            time.sleep(delay)
            return name
    except Exception as e:
        print(f"      [오류] {type(e).__name__}: {str(e)[:60]}")
        return None


# ───────────────────────── CPA (금융감독원) ─────────────────────────
CPA_BASE = "https://cpa.fss.or.kr"
CPA_LIST = CPA_BASE + "/cpa/bbs/B0000368/list.do?menuNo=1200078&pageIndex={p}"
CPA_VIEW = CPA_BASE + "/cpa/bbs/B0000368/view.do?nttId={n}&menuNo=1200078"


def cpa_run(maxitems, delay):
    print("\n=== [CPA] 공인회계사 기출 (금융감독원) ===")
    base = OUT / "cpa"
    posts = []  # (nttId, title)
    p = 1
    while True:
        r = S.get(CPA_LIST.format(p=p), timeout=40)
        found = re.findall(
            r'href="([^"]*view\.do\?nttId=(\d+)[^"]*)"[^>]*>\s*([^<]+?)\s*</a>', r.text)
        if not found:
            break
        for href, nid, title in found:
            posts.append((nid, title.strip()))
        print(f"  목록 p{p}: 누적 {len(posts)}")
        p += 1
        if p > 30:
            break
        time.sleep(delay)
    # 중복 제거(순서 유지)
    seen = set(); uniq = []
    for nid, t in posts:
        if nid not in seen:
            seen.add(nid); uniq.append((nid, t))
    print(f"  게시글 {len(uniq)}건")
    if maxitems:
        uniq = uniq[:maxitems]
    for nid, title in uniq:
        folder = base / sanitize(f"{title}")
        r = S.get(CPA_VIEW.format(n=nid), timeout=40)
        dls = re.findall(r'(/cpa/cmmn/file/fileDown\.do\?[^"\']+)', r.text)
        dls = list(dict.fromkeys(dls))
        if not dls:
            continue
        print(f"  · {title} ({len(dls)}첨부)")
        for d in dls:
            download(urljoin(CPA_BASE, d.replace("&amp;", "&")), folder, f"{nid}.bin", delay)
        time.sleep(delay)


# ───────────────────── 법무사 (합격의법학원 = 공식 문제 미러) ─────────────────────
JUD_BASE = "https://judicial.lawschool.co.kr"
JUD_LIST = JUD_BASE + "/nlawschool/board/infomation/list.asp?field=12&mnNum=5&subMnNum=1&bbsCode=303&pageNo={p}"
JUD_VIEW = JUD_BASE + "/nlawschool/board/infomation/view.asp?num={n}&field=12&mnNum=5&subMnNum=1&bbsCode=303"
# 공식 시험 문제/정답만 (모의고사·해설·교재·강사자료·총평 제외)
JUD_KEEP = re.compile(r"법무사.*(시험\s*문제|차\s*시험|확정정답|정답가안|기출문제|출제문제|문제\s*및\s*정답)")
JUD_DROP = re.compile(r"(모의고사|해설|총평|교재|교수|적중|판례|수정표|특강|안내문|자료|테마|정리|요약|핵심|강의|첨삭|채점|동영상)")


def jud_run(maxitems, delay):
    print("\n=== [법무사] 합격의법학원 자료센터 (공식 문제/정답) ===")
    base = OUT / "bupmu"
    posts = []
    for p in range(1, 16):
        r = S.get(JUD_LIST.format(p=p), timeout=40); r.encoding = r.apparent_encoding
        found = re.findall(
            r'href="([^"]*view\.asp\?[^"]*num=(\d+)[^"]*)"[^>]*>\s*([^<]+?)\s*</a>', r.text)
        if not found:
            break
        for href, num, title in found:
            t = re.sub(r"\s+", " ", title).strip()
            if JUD_KEEP.search(t) and not JUD_DROP.search(t):
                posts.append((num, t))
        time.sleep(delay)
    seen = set(); uniq = []
    for num, t in posts:
        if num not in seen:
            seen.add(num); uniq.append((num, t))
    print(f"  공식 문제/정답 게시글 {len(uniq)}건")
    for num, t in uniq[:10]:
        print("    -", t)
    if maxitems:
        uniq = uniq[:maxitems]
    for num, title in uniq:
        folder = base / sanitize(title)
        view_url = JUD_VIEW.format(n=num)
        r = S.get(view_url, timeout=40); r.encoding = r.apparent_encoding
        # <a href='/nlawschool/board/Download.asp?...fileIdx=..'> 파일명.hwp</a>
        atts = re.findall(
            r"href=['\"]([^'\"]*Download\.asp[^'\"]+)['\"][^>]*>(?:<img[^>]*>)?\s*([^<]+?\.(?:hwp|hwpx|pdf|zip|doc|docx))",
            r.text, re.I)
        if not atts:
            continue
        print(f"  · {title} ({len(atts)}첨부)")
        for href, fn in atts:
            # 핫링크 차단 우회: Referer=상세페이지, 파일명은 앵커텍스트 사용
            download(urljoin(JUD_BASE, href.replace("&amp;", "&")), folder, sanitize(fn),
                     delay, referer=view_url, prefer_name=True)
        time.sleep(delay)


# ───────────────────────── 세무사 (큐넷) ─────────────────────────
QNET = "https://www.q-net.or.kr"
QNET_REF = QNET + "/cst003.do?id=cst00309&gSite=L&gId=22"
QNET_LIST = QNET + "/cst003.do?id=cst00301s01&gSite=L&gId=22&page={p}&schText=&schType=&boardId=Q004&code=1008"
QNET_POST = QNET + "/cst003.do"


def semu_run(maxitems, delay):
    print("\n=== [세무사] 큐넷 기출 (q-net.or.kr) ===")
    base = OUT / "semu"
    S.get(QNET_REF, timeout=30)  # 세션 쿠키
    ref = {"Referer": QNET_REF}
    posts = []  # (artlSeq, title)
    for p in range(1, 30):
        r = S.get(QNET_LIST.format(p=p), headers=ref, timeout=40)
        found = re.findall(r"goNext\('(\d+)'\s*,[^>]*>\s*([^<]+?)\s*</a>", r.text)
        if not found:
            break
        for seq, title in found:
            t = re.sub(r"\s+", " ", title).strip()
            if "세무사" in t and ("문제" in t or "시험" in t):  # 공지 제외
                posts.append((seq, t))
        print(f"  목록 p{p}: 누적 {len(posts)}")
        time.sleep(delay)
    seen = set(); uniq = []
    for seq, t in posts:
        if seq not in seen:
            seen.add(seq); uniq.append((seq, t))
    print(f"  기출 게시글 {len(uniq)}건")
    if maxitems:
        uniq = uniq[:maxitems]
    for seq, title in uniq:
        folder = base / sanitize(title)
        data = {"id": "cst00302", "gSite": "L", "gId": "22", "page": "1",
                "schType": "", "schText": "", "artlSeq": seq, "boardId": "Q004", "code": "1008"}
        r = S.post(QNET_POST, data=data, headers=ref, timeout=40)
        atts = re.findall(r"fileDown\('([^']+)'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\)", r.text)
        if not atts:
            continue
        print(f"  · {title} ({len(atts)}첨부)")
        for filePath, fileName, fileSeq in atts:
            params = {"id": "cst00302s01", "gSite": "L", "gId": "22", "fileCode": "R001",
                      "filePath": filePath, "fileName": fileName, "fileSeq": fileSeq,
                      "artlSeq": seq, "href": "0"}
            from urllib.parse import urlencode
            url = QNET_POST + "?" + urlencode(params)
            download(url, folder, sanitize(fileName), delay)
        time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpa", action="store_true")
    ap.add_argument("--bupmu", action="store_true")
    ap.add_argument("--semu", action="store_true")
    ap.add_argument("--max", type=int, default=0, help="소스별 최대 게시글(0=전체)")
    ap.add_argument("--delay", type=float, default=0.8)
    args = ap.parse_args()
    if not any([args.cpa, args.bupmu, args.semu]):
        print("대상 지정: --cpa --bupmu (--semu는 큐넷 JS 목록이라 미구현)"); return
    OUT.mkdir(parents=True, exist_ok=True)
    if args.cpa:
        cpa_run(args.max, args.delay)
    if args.bupmu:
        jud_run(args.max, args.delay)
    if args.semu:
        semu_run(args.max, args.delay)
    print("\n[완료] 저장 위치:", OUT)


if __name__ == "__main__":
    main()
