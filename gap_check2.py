# -*- coding: utf-8 -*-
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

print(f"총 문제: {len(qs)}")

TARGET_EXAMS = ["노무사", "세무사", "법무사", "감정평가사"]
TARGET_YEARS = list(range(2015, 2026))

from collections import defaultdict
buckets = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
for q in qs:
    exam = q.get("exam", "")
    if exam not in TARGET_EXAMS:
        continue
    subj = q.get("subject", "")
    y = q.get("year")
    if isinstance(y, str):
        try: y = int(y)
        except: continue
    if y not in TARGET_YEARS:
        continue
    buckets[exam][subj][y] += 1

for exam in TARGET_EXAMS:
    print(f"\n=== {exam} ===")
    for subj in sorted(buckets[exam]):
        ydata = buckets[exam][subj]
        total = sum(ydata.values())
        missing = [y for y in TARGET_YEARS if y not in ydata]
        status = "OK" if not missing else f"GAP:{','.join(str(y) for y in missing)}"
        years_str = " ".join(f"{y}({ydata[y]})" for y in sorted(ydata))
        print(f"  [{total}] {subj}  {status}")
        print(f"    {years_str}")
