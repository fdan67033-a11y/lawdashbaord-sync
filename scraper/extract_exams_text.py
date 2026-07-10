# -*- coding: utf-8 -*-
"""기출 파일(DRM해제 staging) -> 텍스트 추출.
- HWP: 한글 2018 COM(GetTextFile). 배포용 문서는 빈 텍스트 -> 'blocked'로 분류.
- PDF: pypdf. 텍스트층 없으면 'scan'으로 분류(OCR 대상).
출력: data/exams_text/<staged이름>.txt  +  _index.json(상태)  +  _todo_ocr.json(배포용/스캔 목록)
txt는 프로젝트 내에서도 재암호화 안 됨(검증됨).
사용: py -3.12 scraper\\extract_exams_text.py
"""
import os, sys, glob, json, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGE = os.path.join(ROOT, "data", "exams_drm_staging")
OUT = os.path.join(ROOT, "data", "exams_text")
os.makedirs(OUT, exist_ok=True)
manifest = json.load(open(os.path.join(ROOT, "data", "exams_staging_manifest.json"), encoding="utf-8"))

index = {}   # staged -> {origin, kind, status, chars}
todo = []    # 배포용/스캔/오류

def save_txt(staged, text):
    name = os.path.splitext(staged)[0] + ".txt"
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(text)
    return name

# ---- PDF (pypdf) ----
def do_pdfs():
    from pypdf import PdfReader
    for p in glob.glob(os.path.join(STAGE, "*.pdf")):
        staged = os.path.basename(p)
        try:
            r = PdfReader(p)
            text = "\n".join((pg.extract_text() or "") for pg in r.pages)
        except Exception as e:
            index[staged] = {"origin": manifest.get(staged,""), "kind":"pdf","status":"error","err":str(e)[:60]}
            todo.append(staged); continue
        if len(re.sub(r"\s","",text)) > 80:
            save_txt(staged, text)
            index[staged] = {"origin": manifest.get(staged,""), "kind":"pdf","status":"ok","chars":len(text)}
        else:
            index[staged] = {"origin": manifest.get(staged,""), "kind":"pdf","status":"scan_ocr_needed","chars":len(text)}
            todo.append(staged)
    print(f"[pdf] 완료. 누적 index {len(index)}", flush=True)

# ---- HWP (한글 COM) ----
def do_hwps():
    import win32com.client as w
    hwp = w.gencache.EnsureDispatch("HWPFrame.HwpObject")
    try:
        hwp.RegisterModule("FilePathCheckDLL", "FilePathCheckerModule")
    except Exception:
        pass
    files = glob.glob(os.path.join(STAGE, "*.hwp")) + glob.glob(os.path.join(STAGE, "*.hwpx"))
    n = 0
    for p in files:
        staged = os.path.basename(p)
        text = ""
        try:
            hwp.Open(os.path.abspath(p), "HWP", "forceopen:true")
            text = hwp.GetTextFile("TEXT", "") or ""
            hwp.Clear(1)
        except Exception as e:
            index[staged] = {"origin": manifest.get(staged,""),"kind":"hwp","status":"error","err":str(e)[:60]}
            todo.append(staged);
            n += 1; continue
        if len(re.sub(r"\s","",text)) > 40:
            save_txt(staged, text)
            index[staged] = {"origin": manifest.get(staged,""),"kind":"hwp","status":"ok","chars":len(text)}
        else:
            index[staged] = {"origin": manifest.get(staged,""),"kind":"hwp","status":"distribution_blocked","chars":len(text)}
            todo.append(staged)
        n += 1
        if n % 25 == 0:
            print(f"[hwp] {n}/{len(files)} | ok누적 {sum(1 for v in index.values() if v.get('status')=='ok')}", flush=True)
            json.dump(index, open(os.path.join(OUT,"_index.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    try: hwp.Quit()
    except Exception: pass
    print(f"[hwp] 완료 {n}", flush=True)

if __name__ == "__main__":
    do_pdfs()
    do_hwps()
    json.dump(index, open(os.path.join(OUT,"_index.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(todo, open(os.path.join(OUT,"_todo_ocr.json"),"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    ok=sum(1 for v in index.values() if v.get("status")=="ok")
    print(f"\n[완료] 텍스트추출 성공 {ok} | 추가처리(배포용/스캔/오류) {len(todo)} | 출력 {OUT}", flush=True)
