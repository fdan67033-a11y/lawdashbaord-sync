# -*- coding: utf-8 -*-
"""감정평가사 2019 HWP → 텍스트 추출 테스트"""
import zipfile, sys, io, os, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ZIP_PATH = 'data/exams/gampyeong/2019년 제30회 감정평가사 1차시험 기출문제/2019년 제30회 감정평가사 1차시험 문제지.zip'
OUT_DIR = 'data/_gamp2019_hwp'
os.makedirs(OUT_DIR, exist_ok=True)

# ZIP에서 HWP 추출
print("=== ZIP 추출 ===")
with zipfile.ZipFile(ZIP_PATH) as z:
    for info in z.infolist():
        # 파일명 디코딩 (CP949)
        try:
            fname = info.filename.encode('cp437').decode('cp949')
        except:
            fname = info.filename
        # 마지막 부분만 (디렉토리 제외)
        basename = fname.split('/')[-1]
        if not basename.endswith('.hwp'):
            continue
        out_path = os.path.join(OUT_DIR, basename)
        with z.open(info) as src, open(out_path, 'wb') as dst:
            dst.write(src.read())
        print(f"  추출: {basename} ({info.file_size:,} bytes)")

# hwp5로 텍스트 추출 시도
print("\n=== hwp5 텍스트 추출 ===")
try:
    from hwp5.hwpfile import HWPFile
    for fname in sorted(os.listdir(OUT_DIR)):
        if not fname.endswith('.hwp'):
            continue
        fpath = os.path.join(OUT_DIR, fname)
        print(f"\n[{fname}]")
        try:
            hwp = HWPFile(fpath)
            txt_path = fpath.replace('.hwp', '.txt')
            with open(txt_path, 'w', encoding='utf-8') as f:
                for body in hwp.bodytext:
                    for section in body.sections:
                        for para in section.paragraphs:
                            text = para.text
                            if text.strip():
                                f.write(text + '\n')
            print(f"  → 텍스트 저장: {txt_path}")
            # 앞부분 미리보기
            with open(txt_path, encoding='utf-8') as f:
                lines = [l.strip() for l in f.readlines()[:30] if l.strip()]
            for l in lines[:20]:
                print(f"  {l[:80]}")
        except Exception as e:
            print(f"  오류: {e}")
except ImportError as e:
    print(f"hwp5 import 오류: {e}")
    # hwp5txt CLI 시도
    import subprocess
    for fname in sorted(os.listdir(OUT_DIR)):
        if not fname.endswith('.hwp'):
            continue
        fpath = os.path.join(OUT_DIR, fname)
        txt_path = fpath.replace('.hwp', '.txt')
        print(f"\n[{fname}] CLI 시도")
        result = subprocess.run(
            ['hwp5txt', fpath],
            capture_output=True, text=True, encoding='utf-8', errors='replace'
        )
        if result.returncode == 0:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(result.stdout)
            print(f"  → 저장됨 ({len(result.stdout)} chars)")
            for l in result.stdout.split('\n')[:20]:
                if l.strip():
                    print(f"  {l[:80]}")
        else:
            print(f"  CLI 오류: {result.stderr[:200]}")
