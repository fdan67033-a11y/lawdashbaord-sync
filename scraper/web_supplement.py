# -*- coding: utf-8 -*-
"""웹 보완(막힌 배포용/스캔 기출): 학원 사이트의 '읽히는' PDF를 받아 텍스트화.
1단계 법무사: 합격의법학원 자료센터(bbsCode=303)에서 '기출해설/문제 및 해설' 글의
  PDF 첨부(배포용 아님)를 핫링크 우회로 받아 pypdf 추출 -> data/exams_text/web_bupmu__*.txt
멱등(있으면 skip). 사용: py -3.12 scraper\\web_supplement.py
"""
import sys, os, re, io, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests, urllib3
urllib3.disable_warnings()
from pypdf import PdfReader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "exams_text")
os.makedirs(OUT, exist_ok=True)
S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                  "Accept-Language": "ko-KR,ko;q=0.9"})
BASE = "https://judicial.lawschool.co.kr"
LIST = BASE + "/nlawschool/board/infomation/list.asp?field=12&mnNum=5&subMnNum=1&bbsCode=303&pageNo={p}"
VIEW = BASE + "/nlawschool/board/infomation/view.asp?num={n}&field=12&mnNum=5&subMnNum=1&bbsCode=303"
KEEP = re.compile(r"법무사.*(해설|문제\s*및\s*해설|기출해설)")  # 읽히는 해설 위주
DROP = re.compile(r"(모의고사|특강|교재|동영상|수정표|안내)")

def sanitize(s, m=120):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", re.sub(r"<[^>]+>", "", s or "")).strip()
    return re.sub(r"\s+", " ", s)[:m].strip(" ._") or "x"

def run():
    S.get(LIST.format(p=1), timeout=30, verify=False)
    posts = []
    for p in range(1, 20):
        r = S.get(LIST.format(p=p), timeout=30, verify=False); r.encoding = r.apparent_encoding
        found = re.findall(r'href="([^"]*view\.asp\?[^"]*num=(\d+)[^"]*)"[^>]*>\s*([^<]+?)\s*</a>', r.text)
        if not found: break
        for _, num, title in found:
            t = re.sub(r"\s+", " ", title).strip()
            if KEEP.search(t) and not DROP.search(t):
                posts.append((num, t))
        time.sleep(0.5)
    seen = set(); uniq = [(n, t) for n, t in posts if not (n in seen or seen.add(n))]
    print(f"[법무사 해설] 대상 글 {len(uniq)}개", flush=True)
    ok = 0
    for num, title in uniq:
        v = VIEW.format(n=num)
        r = S.get(v, timeout=30, verify=False); r.encoding = r.apparent_encoding
        atts = re.findall(r"(Download\.asp\?[^'\"]+)", r.text)
        for i, a in enumerate(atts):
            durl = BASE + "/nlawschool/board/" + a.replace("&amp;", "&")
            try:
                c = S.get(durl, timeout=60, verify=False, headers={"Referer": v}).content
            except Exception:
                continue
            if c[:4] != b"%PDF":   # 배포용/HWP/비PDF 제외(읽히는 PDF만)
                continue
            try:
                rd = PdfReader(io.BytesIO(c))
                txt = "\n".join((pg.extract_text() or "") for pg in rd.pages)
            except Exception:
                continue
            if len(re.sub(r"\s", "", txt)) < 100:
                continue
            name = "web_bupmu__" + sanitize(f"{num}_{title}_{i}") + ".txt"
            dest = os.path.join(OUT, name)
            if os.path.exists(dest):
                ok += 1; continue
            open(dest, "w", encoding="utf-8").write(txt)
            ok += 1
            print(f"  [받음] {title[:40]} p{len(rd.pages)} ({len(txt)}자)", flush=True)
        time.sleep(0.6)
    print(f"\n[완료] 법무사 해설 텍스트 {ok}개 -> {OUT}", flush=True)

if __name__ == "__main__":
    run()
