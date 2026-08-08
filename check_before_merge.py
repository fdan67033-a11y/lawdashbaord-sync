# -*- coding: utf-8 -*-
import json, sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

# 1) 세무사 round 샘플 (year int 기준)
print("=== 기존 세무사 round 샘플 ===")
semu = [q for q in qs if q.get("exam")=="세무사"]
from collections import Counter
yr_pairs = []
for q in semu:
    y = q.get("year")
    r = q.get("round")
    if isinstance(y, int) and 2015 <= y <= 2026:
        yr_pairs.append((y, r))
yr = Counter(yr_pairs)
for (y,r), cnt in sorted(yr.items(), key=lambda x: x[0])[:15]:
    print(f"  {y} → round={r} ({cnt}문)")

# 2) 회계사 연도 분포 (2015-2026)
print("\n=== 기존 회계사 2015+ 연도별 문제 수 ===")
cpa = [q for q in qs if q.get("exam")=="회계사"]
yc = Counter()
for q in cpa:
    y = q.get("year")
    if isinstance(y, int) and y >= 2015:
        yc[y] += 1
for y in sorted(yc):
    print(f"  {y}: {yc[y]}문")

# 3) data/exams_updated에서 회계사 2015+ 파일들
print("\n=== exams_updated 회계사 2015+ 파일 ===")
UPDATED_DIR = "data/exams_updated"
for fname in sorted(os.listdir(UPDATED_DIR)):
    if "cpa" not in fname.lower():
        continue
    fpath = os.path.join(UPDATED_DIR, fname)
    try:
        with open(fpath, encoding="utf-8-sig") as f:
            d = json.load(f)
        if isinstance(d, dict):
            year_raw = d.get("meta",{}).get("year","?")
            nq = len(d.get("questions",[]))
        elif isinstance(d, list) and d:
            year_raw = d[0].get("year","?")
            nq = len(d)
        else:
            year_raw, nq = "?", 0
        try:
            y = int(str(year_raw)[:4])
        except:
            y = 0
        if y >= 2015:
            print(f"  {fname[:70]}  year={year_raw} {nq}문")
    except:
        pass
