# -*- coding: utf-8 -*-
"""data/exams_updated/에서 아직 병합 안 된 파일들 확인"""
import json, os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

UPDATED_DIR = "data/exams_updated"
QUESTIONS_PATH = "study/questions.json"

with open(QUESTIONS_PATH, encoding="utf-8-sig") as f:
    qs = json.load(f)

# 기존 questions.json의 (exam, subject, year) 조합
existing_keys = set()
for q in qs:
    y = q.get("year")
    if isinstance(y, str):
        try: y = int(y)
        except: pass
    existing_keys.add((q.get("exam",""), q.get("subject",""), y))

for fname in sorted(os.listdir(UPDATED_DIR)):
    if not fname.endswith(".json") or fname.startswith("_"):
        continue
    fpath = os.path.join(UPDATED_DIR, fname)
    try:
        with open(fpath, encoding="utf-8-sig") as f:
            d = json.load(f)
    except:
        continue

    if isinstance(d, list):
        items = d
    elif isinstance(d, dict):
        items = d.get("questions", [])
    else:
        continue

    if not items:
        continue

    # 대표 exam/subject/year
    sample = items[0]
    exam = sample.get("exam", "?")
    subj = sample.get("subject", "?")
    y = sample.get("year")
    if isinstance(y, str):
        try: y = int(y)
        except: pass

    in_existing = (exam, subj, y) in existing_keys
    status = "이미병합" if in_existing else "★미병합"
    print(f"[{status}] {fname[:60]}  ({exam} {subj} {y}, {len(items)}문)")
