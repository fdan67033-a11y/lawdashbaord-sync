# -*- coding: utf-8 -*-
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

with open("study/questions.json", encoding="utf-8-sig") as f:
    qs = json.load(f)

# 같은 (exam, subject, year, q 첫 40자) 조합이 2개 이상인 경우 찾기
from collections import defaultdict
key_count = defaultdict(list)
for i, q in enumerate(qs):
    key = (q.get("exam",""), q.get("subject",""), q.get("year"), (q.get("q","") or "")[:40])
    key_count[key].append(i)

dupes = {k: v for k, v in key_count.items() if len(v) > 1}
print(f"중복 (exam,subj,year,q40) 조합: {len(dupes)}개")
if dupes:
    for (exam, subj, year, q40), idxs in list(dupes.items())[:10]:
        print(f"  {exam} {subj} {year} | q={q40[:30]}... -> ids={[qs[i]['id'] for i in idxs]}")

# 노무사 경영학개론 2018 상세 확인
print("\n--- 노무사 경영학개론 2018 ---")
for q in qs:
    if q.get("exam") == "노무사" and q.get("subject") == "경영학개론" and q.get("year") == 2018:
        print(f"  id={q['id']} q={str(q.get('q',''))[:50]}")
