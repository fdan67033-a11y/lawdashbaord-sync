# -*- coding: utf-8 -*-
"""%TEMP%\\exam_unzip (zip을 프로젝트 밖에 푼 클린 파일들)에서 텍스트 추출.
재암호화 없음(프로젝트 밖). PDF=pypdf, HWP5=olefile 본문. 배포용/스캔/한글97은 건너뜀.
출력: data/exams_text/zip_<source>__<원파일>.txt  (source: bupmu/semu/cpa)
사용: py -3.12 scraper\\extract_zip_recovered.py  (이후 build_cards 재실행)
"""
import os, sys, glob, re, zlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import olefile
from pypdf import PdfReader

SRCDIR = os.path.join(os.path.expandvars(r"%TEMP%"), "exam_unzip")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "exams_text")
KEEP = re.compile(r"[^가-힣A-Za-z0-9 \t.,()\[\]{}<>:;%~\-+/'\"?!①-⑩]+")

def src_of(name):
    if "법무사" in name: return "bupmu"
    if "세무사" in name: return "semu"
    if "회계사" in name: return "cpa"
    return "zip"

def clean(t):
    t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+", " ", t)
    t = KEEP.sub(" ", t)
    return re.sub(r"[ \t]{2,}", " ", t)

def pdf_text(f):
    try:
        r = PdfReader(f)
        return "\n".join((p.extract_text() or "") for p in r.pages)
    except Exception:
        return ""

def hwp5_text(f):
    try:
        ole = olefile.OleFileIO(f)
        comp = bool(int.from_bytes(ole.openstream("FileHeader").read()[36:40], "little") & 1)
        secs = sorted('/'.join(s) for s in ole.listdir() if s[0] == "BodyText")
        out = []
        for s in secs:
            raw = ole.openstream(s).read()
            try:
                dec = zlib.decompress(raw, -15) if comp else raw
                out.append(dec.decode("utf-16le", errors="ignore"))
            except Exception:
                pass
        ole.close()
        txt = "\n".join(out)
        if "배포용 문서" in txt:
            return ""
        return clean(txt)
    except Exception:
        return ""

def main():
    files = glob.glob(os.path.join(SRCDIR, "*"))
    ok = scan = skip = 0
    for f in files:
        head = open(f, "rb").read(8)
        base = re.sub(r"^\d+_", "", os.path.basename(f))
        if head[:4] == b"%PDF":
            t = pdf_text(f)
            kind = "pdf"
        elif head == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            t = hwp5_text(f); kind = "hwp5"
        else:
            skip += 1; continue
        if len(re.sub(r"\s", "", t)) < 100:
            scan += 1; continue
        name = f"zip_{src_of(base)}__{re.sub(r'[\\/:*?\"<>|]+','_',base)}"
        name = os.path.splitext(name)[0][:130] + ".txt"
        with open(os.path.join(OUT, name), "w", encoding="utf-8") as o:
            o.write(t)
        ok += 1
    print(f"[zip복구] 텍스트저장 {ok} | 스캔/빈약 {scan} | 건너뜀(한글97/배포용) {skip} | -> {OUT}")

if __name__ == "__main__":
    main()
