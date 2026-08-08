# -*- coding: utf-8 -*-
import json, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

EXAMS_DIR = "data/exams_updated"

# 2교시 파일들 확인
target_files = [f for f in os.listdir(EXAMS_DIR) if "2교시" in f and "semu" in f and f.endswith(".json")]
print(f"2교시 semu 파일: {len(target_files)}개\n")

for fname in sorted(target_files):
    fpath = os.path.join(EXAMS_DIR, fname)
    with open(fpath, encoding="utf-8-sig") as f:
        d = json.load(f)

    if isinstance(d, dict):
        meta = d.get("meta", {})
        subjects_norm = meta.get("subjects_norm") or meta.get("subjects") or []
        qs = d.get("questions", [])
        nos = [q.get("no") for q in qs[:3]]
        print(f"[{fname[:80]}]")
        print(f"  subjects_norm: {subjects_norm}")
        print(f"  문제 수: {len(qs)}, 첫 3개 no: {nos}")
        if qs:
            print(f"  첫 문제 stem[:40]: {str(qs[0].get('stem',''))[:40]}")
        print()
