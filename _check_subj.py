# -*- coding: utf-8 -*-
import json, sys, io
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

# 세무사 과목명 목록
semu = [q for q in qs if q.get("exam") == "세무사"]
print(f"세무사 총: {len(semu)}문")

subj_year = Counter()
for q in semu:
    y = q.get("year")
    if isinstance(y, int) and 2015 <= y <= 2026:
        subj_year[(q.get("subject","?"), y)] += 1

print("\n=== 세무사 과목×연도별 문제 수 (2015-2026) ===")
for (s, y), cnt in sorted(subj_year.items(), key=lambda x: (x[0][0], x[0][1])):
    print(f"  {s} / {y}: {cnt}문")

# 법무사 2019 헌법 확인
bupmu = [q for q in qs if q.get("exam") == "법무사"]
bupmu_2019 = [q for q in bupmu if q.get("year") == 2019]
subj_cnt = Counter(q.get("subject","?") for q in bupmu_2019)
print(f"\n=== 법무사 2019 과목별 ===")
for s, c in sorted(subj_cnt.items()):
    print(f"  {s}: {c}문")

# 법무사 2023 공탁법 확인
bupmu_2023 = [q for q in bupmu if q.get("year") == 2023]
subj_cnt2 = Counter(q.get("subject","?") for q in bupmu_2023)
print(f"\n=== 법무사 2023 과목별 ===")
for s, c in sorted(subj_cnt2.items()):
    print(f"  {s}: {c}문")
