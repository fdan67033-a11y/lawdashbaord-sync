# -*- coding: utf-8 -*-
"""DOCX에서 텍스트 추출 및 미리보기"""
import docx, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

HWP_DIR = 'data/_gamp2019_hwp'

for fname in ['2019년도 제30회 감정평가사 1차 1교시 A형.docx',
              '2019년도 제30회 감정평가사 1차 2교시 A형.docx']:
    fpath = os.path.join(HWP_DIR, fname)
    print(f"\n{'='*70}")
    print(f"[{fname}]")
    doc = docx.Document(fpath)
    paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    print(f"  단락 수: {len(paras)}")
    print("\n  --- 앞 60줄 ---")
    for i, t in enumerate(paras[:60]):
        print(f"  {i+1:3d}: {t[:100]}")
