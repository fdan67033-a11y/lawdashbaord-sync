# -*- coding: utf-8 -*-
"""포터블 통합 ZIP 생성: 법제처 대시보드 + 학습 대시보드 + 데이터.
제외: cache, 원본 exams, drm_staging, exams_text, exams_cards, __pycache__, .git, .claude.
출력: ../법령_기출_대시보드.zip
"""
import os, sys, zipfile, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(os.path.dirname(ROOT), "법령_기출_대시보드.zip")

EXCL_DIRS = {
    os.path.join("data", "cache"),
    os.path.join("data", "exams"),
    os.path.join("data", "exams_drm_staging"),
    os.path.join("data", "exams_text"),
    os.path.join("data", "exams_cards"),
}
EXCL_NAMES = {"__pycache__", ".git", ".claude", "node_modules", ".pytest_cache"}

def excluded(rel):
    parts = rel.replace("\\", "/").split("/")
    if any(p in EXCL_NAMES for p in parts):
        return True
    for d in EXCL_DIRS:
        if rel.replace("\\", "/").startswith(d.replace("\\", "/") + "/") or rel.replace("\\","/")==d.replace("\\","/"):
            return True
    return False

def main():
    if os.path.exists(OUT):
        os.remove(OUT)
    n = 0; total = 0; t0 = time.time()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for dp, dirs, files in os.walk(ROOT):
            rel_dp = os.path.relpath(dp, ROOT)
            dirs[:] = [d for d in dirs if not excluded(os.path.join(rel_dp, d) if rel_dp != "." else d)]
            for f in files:
                full = os.path.join(dp, f)
                rel = os.path.relpath(full, ROOT)
                if rel == os.path.basename(OUT) or excluded(rel):
                    continue
                if f.endswith(".zip"):
                    continue
                try:
                    z.write(full, os.path.join("법령_기출_대시보드", rel))
                    n += 1; total += os.path.getsize(full)
                    if n % 200 == 0:
                        print(f"  ...{n}개, 원본 {total/1024/1024:.0f}MB", flush=True)
                except Exception as e:
                    print("  skip", rel[:50], str(e)[:40], flush=True)
    sz = os.path.getsize(OUT)
    print(f"[완료] {n}개 파일 | 원본 {total/1024/1024:.0f}MB -> ZIP {sz/1024/1024:.0f}MB | {time.time()-t0:.0f}초")
    print("출력:", OUT)

if __name__ == "__main__":
    main()
