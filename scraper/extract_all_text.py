# -*- coding: utf-8 -*-
"""data/exams/<source>/<folder>/<file> -> 텍스트 추출 (한글 설치 불필요).
- PDF: PyMuPDF(fitz)
- HWP 5.x(OLE): olefile + zlib + PARA_TEXT 레코드 파싱
- ZIP: 풀어서 내부 pdf/hwp 재귀 추출
- HWP 3.x(구 'HWP ' 포맷)·스캔PDF: 미지원 표시(todo)
출력: data/exams_text_v2/<source>__<folder>__<file>.txt  +  _extract_index.json
사용: python scraper/extract_all_text.py
"""
import os, sys, glob, json, re, zlib, zipfile, tempfile, shutil
try: sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception: pass
import olefile, fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "exams")
OUT = os.path.join(ROOT, "data", "exams_text_v2")
os.makedirs(OUT, exist_ok=True)

# HWP5 PARA_TEXT(태그67) 제어문자 폭: 확장/인라인 컨트롤 = 8 wchar(16바이트)
EXT8 = {1,2,3,4,5,6,7,8,9,11,12,14,15,16,17,18,19,20,21,22,23}

def hwp5_text_from_record(data: bytes) -> str:
    out=[]; i=0; n=len(data)
    while i+1 < n:
        c = data[i] | (data[i+1] << 8)
        if c in (10,13): out.append("\n"); i+=2
        elif c == 0: i+=2
        elif c < 32:
            i += 16 if c in EXT8 else 2
        elif 0xD800 <= c <= 0xDBFF:  # high surrogate -> combine with low
            if i+3 < n:
                c2 = data[i+2] | (data[i+3] << 8)
                if 0xDC00 <= c2 <= 0xDFFF:
                    out.append(chr(0x10000 + ((c-0xD800)<<10) + (c2-0xDC00))); i+=4; continue
            i+=2  # lone surrogate, skip
        elif 0xDC00 <= c <= 0xDFFF:  # lone low surrogate, skip
            i+=2
        else:
            out.append(chr(c)); i+=2
    return "".join(out)

def parse_hwp5_section(buf: bytes) -> str:
    out=[]; i=0; n=len(buf)
    while i+4 <= n:
        header = int.from_bytes(buf[i:i+4],"little"); i+=4
        tag = header & 0x3FF
        size = (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = int.from_bytes(buf[i:i+4],"little"); i+=4
        rec = buf[i:i+size]; i+=size
        if tag == 67:  # HWPTAG_PARA_TEXT
            out.append(hwp5_text_from_record(rec))
    return "\n".join(out)

def extract_hwp5(path: str) -> str:
    ole = olefile.OleFileIO(path)
    secs=[]
    for entry in ole.listdir():
        if len(entry)==2 and entry[0]=="BodyText":
            secs.append(entry)
    secs.sort(key=lambda e: e[1])
    texts=[]
    for e in secs:
        raw = ole.openstream(e).read()
        try: dec = zlib.decompress(raw, -15)
        except Exception:
            try: dec = zlib.decompress(raw)
            except Exception: dec = raw
        texts.append(parse_hwp5_section(dec))
    ole.close()
    return "\n".join(texts)

def extract_pdf(path: str) -> str:
    d = fitz.open(path)
    t = "\n".join(pg.get_text() for pg in d); d.close()
    return t

def is_ole(path):
    with open(path,"rb") as f: return f.read(4)==b"\xd0\xcf\x11\xe0"

def extract_one(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pdf":
            t = extract_pdf(path)
            return ("ok" if len(re.sub(r"\s","",t))>80 else "scan_ocr", t)
        if ext in (".hwp",):
            if is_ole(path):
                t = extract_hwp5(path)
                return ("ok" if len(re.sub(r"\s","",t))>40 else "empty", t)
            return ("hwp3_unsupported", "")
        if ext == ".hwpx":
            # hwpx = zip; text in Contents/section*.xml
            t=""
            with zipfile.ZipFile(path) as z:
                for nm in z.namelist():
                    if re.search(r"section\d+\.xml$", nm):
                        x=z.read(nm).decode("utf-8","ignore")
                        t+=re.sub(r"<[^>]+>"," ", x)
            return ("ok" if len(re.sub(r"\s","",t))>40 else "empty", t)
        return ("skip_ext", "")
    except Exception as e:
        return ("error:"+type(e).__name__, "")

def safe(s): return re.sub(r"[\\/:*?\"<>|\r\n\t]+","_", s)[:150]

index=[]
def process_file(src, folder, fname, fpath):
    status, text = extract_one(fpath)
    rec={"source":src,"folder":folder,"file":fname,"status":status,"chars":len(text)}
    if text and status=="ok":
        text = text.encode("utf-8","replace").decode("utf-8")  # 잔여 서로게이트 방어
        out=os.path.join(OUT, safe(f"{src}__{folder}__{os.path.splitext(fname)[0]}")+".txt")
        with open(out,"w",encoding="utf-8") as f: f.write(text)
        rec["txt"]=os.path.basename(out)
    index.append(rec)

def main():
    tmpdir=tempfile.mkdtemp()
    n=0
    for src in ["cpa","semu","bupmu","gampyeong"]:
        base=os.path.join(SRC,src)
        if not os.path.isdir(base): continue
        for folder in os.listdir(base):
            fp=os.path.join(base,folder)
            if not os.path.isdir(fp): continue
            for fname in os.listdir(fp):
                fpath=os.path.join(fp,fname)
                if not os.path.isfile(fpath): continue
                ext=os.path.splitext(fname)[1].lower()
                if ext==".zip":
                    try:
                        with zipfile.ZipFile(fpath) as z:
                            for nm in z.namelist():
                                if nm.lower().endswith((".pdf",".hwp",".hwpx")):
                                    dest=os.path.join(tmpdir, safe(os.path.basename(nm)))
                                    with z.open(nm) as zf, open(dest,"wb") as o: shutil.copyfileobj(zf,o)
                                    process_file(src, folder, "[zip]"+os.path.basename(nm), dest)
                                    os.remove(dest)
                    except Exception as e:
                        index.append({"source":src,"folder":folder,"file":fname,"status":"zip_error:"+type(e).__name__})
                else:
                    process_file(src, folder, fname, fpath)
                n+=1
                if n%100==0: print(f"  처리 {n} ...", flush=True)
    shutil.rmtree(tmpdir, ignore_errors=True)
    json.dump(index, open(os.path.join(OUT,"_extract_index.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=0)
    from collections import Counter
    c=Counter(r["status"].split(":")[0] for r in index)
    print("\n[완료] 추출 결과:", dict(c), "| 출력:", OUT, flush=True)

if __name__=="__main__":
    main()
